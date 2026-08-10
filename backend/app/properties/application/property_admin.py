"""Use cases of property administration (`properties-crud` R1, R2, R3; design D1-D4, D7).

A module of its own rather than more of `use_cases.py`, following the split `auth` already
makes between `use_cases.py` (login, refresh, logout) and `user_admin.py` (administration).
`properties/application/use_cases.py` is entirely about clock-driven transitions and says so in
its docstring; putting CRUD there would make that docstring false.

One use case is one business operation and one transaction: it orchestrates the entity and its
ports and calls `commit()` exactly once. No `sqlalchemy` or `fastapi` import — `tests/test_layering.py`
enforces that for this layer by AST.

**Two things this layer is responsible for that are easy to miss:**

* **The wifi password never lands here as a stored value.** It arrives as cleartext from the
  request, is handed straight to `crypto.encrypt`, and reaches the port only as an
  `EncryptedSecret` (design D1, D2). Nothing reads it back; `has_wifi_password` is derived from
  the column being non-null, which is why the port exposes no getter.
* **`current_operational_state` is untouchable from here** (design D3, R4), but **not because the
  port cannot express it** — an earlier version of this paragraph said so and was wrong, the same
  way D8 and two docstrings were. `PATCHABLE_PROPERTY_FIELDS` excludes it, so `update_details`
  cannot carry it; `add` takes a whole entity and therefore *can*, and is stopped by a runtime
  guard in the adapter rather than by its signature. This module needs no guard of its own
  because neither route it uses can reach the column, which is a different statement.
  The obligation that accompanies writing that column lives in rule 9 of `steering/security.md`;
  cite it there rather than restating it here.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from app.audit.domain import actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.core import crypto
from app.core.unit_of_work import UnitOfWork
from app.integrations.domain.enums import PMSProvider
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.exceptions import PropertyNotFoundError
from app.properties.domain.repositories import (
    PATCHABLE_PROPERTY_FIELDS,
    Page,
    PropertyFilters,
    PropertyRepository,
    PropertyStateTransitionRepository,
)

# Free-text columns whose contents are recorded only as "it changed" (design D7). They are the
# analogue in this domain of the fields `specs/reservations.md` flags: an operator can paste a
# door code or a wifi key into "access notes", and `audit_logs.changes` is a plaintext sink under
# rule 11 of `steering/security.md`. Unlike `wifi_password_encrypted`, `ChangeSet` does NOT deny
# these by name, so the discipline has to live here.
REDACTED_ON_AUDIT = frozenset({"access_notes", "cleaning_notes", "emergency_notes"})

# The wifi password is not a patchable column: it goes through its own writer so the value is
# encrypted before it reaches SQL. The request schema accepts it under this name.
WIFI_PASSWORD_FIELD = "wifi_password"


@dataclass(frozen=True)
class CreatePropertyCommand:
    """What `POST /api/v1/properties` accepts (R2.1).

    No `current_operational_state` and no `id`: the first belongs to `PropertyStateMachine` and
    takes its DDL default of `VACANT_READY` on insert (R4.1), the second is generated here.

    `wifi_password` is cleartext in this command and nowhere else — it is encrypted before it
    reaches the repository, and no read path can return it.
    """

    name: str
    internal_code: str
    pms_external_id: str | None = None
    # Settable at INSERT time on purpose, and it matters (design D5): the partial unique index
    # keys on `coalesce(pms_provider, 'MOCK')`, so creating a property provider-less and moving
    # it afterwards passes through a state the index forbids. A caller placing two properties on
    # different providers with one external id has to say so up front.
    pms_provider: PMSProvider | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str = "ES"
    timezone: str = "Europe/Madrid"
    max_guests: int = 2
    bedrooms: int = 1
    bathrooms: int = 1
    default_check_in_time: time = time(15, 0)
    default_check_out_time: time = time(11, 0)
    wifi_name: str | None = None
    wifi_password: str | None = None
    access_notes: str | None = None
    cleaning_notes: str | None = None
    emergency_notes: str | None = None
    status: PropertyStatus = PropertyStatus.ACTIVE


class _AuditWriter:
    """Builds and appends an audit entry, so no use case constructs one by hand.

    Copied in shape from `app/auth/application/user_admin.py`, deliberately rather than shared:
    that module's copy is private to it, and hoisting one into `app/audit/` would be a change to
    a module this feature does not own.
    """

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        actor_ip: str | None,
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=actions.ENTITY_PROPERTY,
                entity_id=entity_id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=changes,
                now=now,
            ),
        )


def _record_field(record: ChangeSet, field: str, before: Any, after: Any) -> ChangeSet:
    """`.redacted()` for the plaintext sinks, `.diff()` for everything else (design D7)."""
    if field in REDACTED_ON_AUDIT:
        return record.redacted(field)
    return record.diff(field, before, after)


class CreatePropertyUseCase:
    def __init__(
        self,
        *,
        properties: PropertyRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._properties = properties
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        command: CreatePropertyCommand,
        now: datetime,
    ) -> Property:
        """Insert a property and record its creation (R2.1, R7.2).

        The order matters and mirrors `CreateUserUseCase`: `add` FLUSHES, so a duplicate
        `internal_code` or `pms_external_id` surfaces as a domain error BEFORE the audit row is
        built — a `409` therefore leaves no trace of a creation that did not happen.

        The stored row is re-read before returning, rather than the constructed entity being
        handed back: `created_at`/`updated_at` come from server defaults, so only the database
        knows their values, and a response carrying the timestamps this process guessed would be
        wrong by however long the flush took.
        """
        property_id = uuid.uuid4()
        wifi_secret = (
            crypto.encrypt(command.wifi_password) if command.wifi_password is not None else None
        )
        property = Property(
            id=property_id,
            tenant_id=tenant_id,
            name=command.name,
            internal_code=command.internal_code,
            created_at=now,
            updated_at=now,
            pms_external_id=command.pms_external_id,
            pms_provider=command.pms_provider,
            address_line1=command.address_line1,
            address_line2=command.address_line2,
            city=command.city,
            province=command.province,
            postal_code=command.postal_code,
            country=command.country,
            timezone=command.timezone,
            max_guests=command.max_guests,
            bedrooms=command.bedrooms,
            bathrooms=command.bathrooms,
            default_check_in_time=command.default_check_in_time,
            default_check_out_time=command.default_check_out_time,
            wifi_name=command.wifi_name,
            access_notes=command.access_notes,
            cleaning_notes=command.cleaning_notes,
            emergency_notes=command.emergency_notes,
            status=command.status,
        )

        await self._properties.add(tenant_id, property, wifi_secret=wifi_secret)

        record = (
            ChangeSet(actions.ENTITY_PROPERTY)
            .diff("name", None, command.name)
            .diff("internal_code", None, command.internal_code)
            .diff("status", None, command.status)
        )
        if wifi_secret is not None:
            # Never the value, not even masked: rule 3 of `steering/security.md` names
            # `wifi_password` first among the things that are never plaintext, and rule 11 is
            # explicit that a guest needing to see it does not buy a masked form either.
            record = record.redacted("wifi_password_encrypted")

        await self._audit.record(
            tenant_id=tenant_id,
            action=actions.PROPERTY_CREATED,
            entity_id=property_id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=record,
            now=now,
        )
        await self._uow.commit()

        stored = await self._properties.get(tenant_id, property_id)
        if stored is None:  # pragma: no cover - the row was just committed in this transaction
            raise PropertyNotFoundError("Property disappeared immediately after being created")
        return stored


class ListPropertiesUseCase:
    def __init__(self, *, properties: PropertyRepository) -> None:
        self._properties = properties

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: PropertyFilters,
        page: int,
        per_page: int,
    ) -> Page:
        return await self._properties.list(
            tenant_id, filters=filters, page=page, per_page=per_page
        )


class GetPropertyUseCase:
    def __init__(self, *, properties: PropertyRepository) -> None:
        self._properties = properties

    async def execute(self, *, tenant_id: uuid.UUID, property_id: uuid.UUID) -> Property:
        """One property, or `PropertyNotFoundError` (R1.5, R1.6).

        The port returns `None` both for "no such id" and for "belongs to another tenant", which
        is what lets the API answer one indistinguishable `404` for both instead of confirming a
        neighbour's property exists.
        """
        property = await self._properties.get(tenant_id, property_id)
        if property is None:
            raise PropertyNotFoundError("Property does not exist")
        return property


@dataclass(frozen=True)
class PropertyState:
    """What `GET /api/v1/properties/{id}/state` answers (`dashboard-api` R3.1).

    Two values that live in two different tables: the state is a column of `properties`,
    and the instant it began is the `created_at` of the newest
    `property_state_transitions` row. `last_transition_at` is `None` for a property that
    has never moved — it was created `VACANT_READY` by the DDL default and creation is not
    a transition, so there is genuinely no instant to report rather than a missing one.
    """

    current_operational_state: PropertyOperationalState
    last_transition_at: datetime | None


class GetPropertyStateUseCase:
    def __init__(
        self,
        *,
        properties: PropertyRepository,
        transitions: PropertyStateTransitionRepository,
    ) -> None:
        self._properties = properties
        self._transitions = transitions

    async def execute(
        self, *, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> PropertyState:
        """The stored state and when it began — **read, never recomputed** (R3.2).

        `steering/backend.md` forbids bypassing `PropertyStateMachine`, and R3.2 spells out
        the read-side half of that: "SHALL NOT reimplementar la resolución de estado en la
        capa de lectura". So this reports `properties.current_operational_state` as the
        machine last left it. It deliberately does NOT consult `ContextualStateResolver`:
        that answers "what state would this property be in now", which is a different
        question, and answering it here would make the endpoint disagree with every other
        reader of the same column.

        The two reads are consistent by construction rather than by luck: every writer of
        `current_operational_state` persists its transition row in the same transaction
        (rule 9 of `steering/security.md`).
        """
        property = await self._properties.get(tenant_id, property_id)
        if property is None:
            raise PropertyNotFoundError("Property does not exist")
        last = await self._transitions.last_for_property(tenant_id, property_id)
        return PropertyState(
            current_operational_state=property.current_operational_state,
            last_transition_at=last.created_at if last is not None else None,
        )


class UpdatePropertyUseCase:
    def __init__(
        self,
        *,
        properties: PropertyRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._properties = properties
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        property_id: uuid.UUID,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> Property:
        """Apply a partial update and record what changed (R3.1, R3.3, R7.2).

        A PATCH that changes nothing — no fields, or fields already holding the sent values —
        writes neither a row nor an audit entry: `audit_logs` is evidence of change, not of
        requests. `written` is what decides both, exactly as in `UpdateUserUseCase`.

        **`wifi_password` is the one field whose no-op cannot be detected**, and that is a
        consequence of design D1 rather than an oversight: there is no reader for the column, so
        this cannot compare the sent password with the stored one. Sending it therefore always
        counts as a change and always writes an audit row saying the secret changed. Comparing
        would require a decrypt-on-read path, which is the thing `app/core/crypto.py` exists to
        keep to a single audited call site.
        """
        property = await self._properties.get(tenant_id, property_id)
        if property is None:
            raise PropertyNotFoundError("Property does not exist")

        record = ChangeSet(actions.ENTITY_PROPERTY)
        written: dict[str, Any] = {}
        for field in PATCHABLE_PROPERTY_FIELDS & set(changes):
            new_value = changes[field]
            before = getattr(property, field)
            if new_value == before:
                continue
            written[field] = new_value
            record = _record_field(record, field, before, new_value)

        wifi_requested = WIFI_PASSWORD_FIELD in changes
        if not written and not wifi_requested:
            return property

        if written:
            found = await self._properties.update_details(tenant_id, property_id, written)
            if not found:  # pragma: no cover - the read above already proved the row is ours
                raise PropertyNotFoundError("Property does not exist")

        if wifi_requested:
            password = changes[WIFI_PASSWORD_FIELD]
            secret = crypto.encrypt(password) if password is not None else None
            await self._properties.set_wifi_password(tenant_id, property_id, secret)
            record = record.redacted("wifi_password_encrypted")

        await self._audit.record(
            tenant_id=tenant_id,
            action=actions.PROPERTY_UPDATED,
            entity_id=property_id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=record,
            now=now,
        )
        await self._uow.commit()

        updated = await self._properties.get(tenant_id, property_id)
        if updated is None:  # pragma: no cover - committed in this transaction
            raise PropertyNotFoundError("Property does not exist")
        return updated
