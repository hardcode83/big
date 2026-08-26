"""SQLAlchemy adapter for `PropertyRepository` (`reservations` design D16).

Every query filters `tenant_id` explicitly. The session-level listener in
`app/core/db.py` also scopes ORM SELECTs, but its own docstring lists what it does not
cover, so the explicit filter stays the authoritative mechanism (design D5).

No method commits: the transactional boundary is the use case (design D4).
"""

import uuid
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encrypted_secret import EncryptedSecret
from app.core.tenancy import CrossTenantWriteError
from app.integrations.domain.enums import PMSProvider
from app.properties.domain.entities import Property, PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.exceptions import (
    AmbiguousPropertyExternalIdError,
    DuplicateInternalCodeError,
    DuplicatePmsExternalIdError,
    PropertyValidationError,
)
from app.properties.domain.repositories import (
    PATCHABLE_PROPERTY_FIELDS,
    Page,
    PropertyFilters,
)
from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel

INTERNAL_CODE_CONSTRAINT = "uq_properties_tenant_id_internal_code"
PMS_EXTERNAL_ID_CONSTRAINT = "uq_properties_tenant_id_pms_external_id"


class SqlAlchemyPropertyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID, property_id: uuid.UUID) -> Property | None:
        result = await self._session.execute(
            select(PropertyModel).where(
                PropertyModel.tenant_id == tenant_id, PropertyModel.id == property_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_property(model) if model is not None else None

    async def find_by_internal_code(
        self, tenant_id: uuid.UUID, internal_code: str
    ) -> Property | None:
        """`uq_properties_tenant_id_internal_code` guarantees at most one row."""
        result = await self._session.execute(
            select(PropertyModel).where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.internal_code == internal_code.strip(),
            )
        )
        model = result.scalar_one_or_none()
        return _to_property(model) if model is not None else None

    async def find_by_pms_external_id(
        self, tenant_id: uuid.UUID, pms_external_id: str
    ) -> Property | None:
        """Fails closed when the external id is ambiguous, with a DOMAIN error.

        `ix_properties_tenant_id_pms_external_id` is an index, NOT a unique constraint,
        so two properties of the same tenant *can* carry the same external id. Picking
        one would silently attach a booking — and a guest — to the wrong flat, so this
        refuses instead.

        It refuses by raising `AmbiguousPropertyExternalIdError`, never by letting
        SQLAlchemy's `MultipleResultsFound` escape: the port promises `Property | None`,
        and its caller (the PMS sync, R3.4) has to report the offending row and continue
        with the batch — which it could only do by catching an infrastructure exception,
        forbidden inside `application/` by the dependency rule.
        """
        rows = await self._session.execute(
            select(PropertyModel)
            .where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.pms_external_id == pms_external_id.strip(),
            )
            .limit(2)
        )
        models = list(rows.scalars())
        if len(models) > 1:
            raise AmbiguousPropertyExternalIdError(
                f"Two or more properties share pms_external_id {pms_external_id!r}",
                pms_external_id=pms_external_id,
            )
        return _to_property(models[0]) if models else None

    async def list_by_state(
        self, tenant_id: uuid.UUID, states: Collection[PropertyOperationalState]
    ) -> list[Property]:
        if not states:
            return []
        result = await self._session.execute(
            select(PropertyModel)
            .where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.current_operational_state.in_(list(states)),
            )
            # Stable order so a job processes the same properties in the same sequence on
            # every tick, which is what makes a failure reproducible from its log.
            .order_by(PropertyModel.id)
        )
        return [_to_property(model) for model in result.scalars()]

    async def list_by_status(
        self, tenant_id: uuid.UUID, status: PropertyStatus
    ) -> list[Property]:
        result = await self._session.execute(
            select(PropertyModel)
            .where(PropertyModel.tenant_id == tenant_id, PropertyModel.status == status)
            # `internal_code` and not `id` like the two neighbours: the order this method
            # returns is **promised by the port**, so it has to be the one a reader of a
            # sweep's log can reconstruct, and an operator knows a flat by its code.
            .order_by(PropertyModel.internal_code)
        )
        return [_to_property(model) for model in result.scalars().all()]

    async def list_all(self, tenant_id: uuid.UUID) -> list[Property]:
        result = await self._session.execute(
            select(PropertyModel)
            .where(PropertyModel.tenant_id == tenant_id)
            # Deterministic order so a grouped sync processes providers the same way twice, which
            # makes a failing run reproducible instead of order-dependent.
            .order_by(PropertyModel.internal_code)
        )
        return [_to_property(model) for model in result.scalars().all()]

    async def states_for(
        self, tenant_id: uuid.UUID, property_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, PropertyOperationalState]:
        if not property_ids:
            return {}
        result = await self._session.execute(
            select(PropertyModel.id, PropertyModel.current_operational_state).where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.id.in_(list(property_ids)),
            )
        )
        # Two columns and no entity, unlike every other read here: the caller needs one enum
        # per id, so there is nothing to gain from `_to_property` and the whole row it maps.
        # The rationale is narrowness — see the port docstring, which also says which security
        # rule this is NOT.
        return {row.id: row.current_operational_state for row in result}

    async def list_for_ids(
        self, tenant_id: uuid.UUID, property_ids: Collection[uuid.UUID]
    ) -> Sequence[Property]:
        """One statement for N properties (`reservation-property-identity` D2).

        Symmetric to `SqlAlchemyGuestRepository.list_for_ids`. Three rules from the port that
        this is the place to keep, not paraphrase:

        - Empty input returns `[]` without a SQL round-trip (no `IN ()`).
        - A property not of this tenant is simply absent from the result; the caller keys by
          `id`, so the neighbour's id and a nonexistent one look the same.
        - `None`/duplicate ids in the input are filtered out before the SQL, so the sequence
          cannot hold an `id = ANY(ARRAY[NULL::uuid])` surprise.

        Selects whole rows: this is the readable batch the listing uses to populate
        `property_name` and `property_internal_code`, not a narrow summary, so there is no
        narrower projection to defend than `_to_property` already does for `list_by_state`.
        """
        # De-`None` and dedupe here, not in the SQL: an `id = ANY(ARRAY[...])` over a
        # Python-level sequence with `None`s is exactly the surprise the port's docstring
        # warns against, and deduping also costs nothing — Python sets in microseconds.
        cleaned = {property_id for property_id in property_ids if property_id is not None}
        if not cleaned:
            return []
        result = await self._session.execute(
            select(PropertyModel).where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.id.in_(list(cleaned)),
            )
        )
        return [_to_property(model) for model in result.scalars()]

    async def save(self, tenant_id: uuid.UUID, property: Property) -> None:
        if property.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property",
                entity_tenant_id=property.tenant_id,
                acting_tenant_id=tenant_id,
            )
        await self._session.execute(
            update(PropertyModel)
            .where(PropertyModel.tenant_id == tenant_id, PropertyModel.id == property.id)
            .values(current_operational_state=property.current_operational_state)
        )


    async def set_pms_provider(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, provider: PMSProvider | None
    ) -> None:
        """One column, like `save`. See the port for why this is not a widening of it."""
        result = await self._session.execute(
            update(PropertyModel)
            .where(PropertyModel.tenant_id == tenant_id, PropertyModel.id == property_id)
            .values(pms_provider=provider)
        )
        if result.rowcount == 0:
            # Nothing matched, which within a tenant-filtered UPDATE means either "no such
            # property" or "it belongs to someone else" — indistinguishable here, and that is
            # the point: reporting which would leak a neighbour's property id (design D6 of
            # `reservations` answers the same question with 404 for the same reason).
            raise CrossTenantWriteError(
                entity="property",
                entity_tenant_id="unknown",
                acting_tenant_id=tenant_id,
            )

    async def add(
        self,
        tenant_id: uuid.UUID,
        property: Property,
        *,
        wifi_secret: EncryptedSecret | None = None,
    ) -> None:
        if property.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property",
                entity_tenant_id=property.tenant_id,
                acting_tenant_id=tenant_id,
            )
        if property.current_operational_state is not PropertyOperationalState.VACANT_READY:
            # A runtime guard, and it has to be one: unlike the other writers, `add` takes a whole
            # entity, so its SIGNATURE cannot forbid a state the way `update_details`' allowlist
            # can. Without this check the port would hand any future caller — `seed-data-demo` is
            # the next one queued — a way to land a property directly in `OCCUPIED` or `BLOCKED`
            # with no `property_state_transitions` row and no `AuditLog`, indistinguishable
            # afterwards from one the machine moved. That is exactly the bypass
            # `steering/backend.md` forbids and rule 9 of `steering/security.md` depends on.
            #
            # Refused rather than silently normalised, for the same reason `update_details`
            # refuses an unknown key: a caller that asked for a state must learn it was ignored.
            raise PropertyValidationError(
                "A property is created in VACANT_READY and nothing else; "
                f"{property.current_operational_state.value} was requested. Reaching any other "
                "state is a transition, and transitions belong to PropertyStateMachine, which "
                "records them in property_state_transitions."
            )
        self._session.add(
            PropertyModel(
                id=property.id,
                tenant_id=property.tenant_id,
                name=property.name,
                internal_code=property.internal_code,
                pms_external_id=property.pms_external_id,
                pms_provider=property.pms_provider,
                address_line1=property.address_line1,
                address_line2=property.address_line2,
                city=property.city,
                province=property.province,
                postal_code=property.postal_code,
                country=property.country,
                timezone=property.timezone,
                max_guests=property.max_guests,
                bedrooms=property.bedrooms,
                bathrooms=property.bathrooms,
                # `current_operational_state` is deliberately NOT set, so this INSERT has no way
                # to express a state at all and the guard above is what keeps the entity honest.
                #
                # Precise about the mechanism, because "the DDL default decides" is only half
                # true: the model also carries a Python-side `default=`, so SQLAlchemy fills the
                # column client-side here. Both values are `VACANT_READY`, and the DDL
                # `server_default` is what covers an INSERT that does not go through the ORM —
                # so the guarantee holds by either route, which is the point of having both.
                default_check_in_time=property.default_check_in_time,
                default_check_out_time=property.default_check_out_time,
                wifi_name=property.wifi_name,
                # The only route by which this column is written, and it can only carry
                # ciphertext: the entity has no such field (design D2) and `EncryptedSecret`
                # refuses to hold anything that is not a Fernet token.
                wifi_password_encrypted=wifi_secret.ciphertext if wifi_secret else None,
                access_notes=property.access_notes,
                cleaning_notes=property.cleaning_notes,
                emergency_notes=property.emergency_notes,
                status=property.status,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            _translate_duplicate(error)
            raise

    async def update_details(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, changes: Mapping[str, Any]
    ) -> bool:
        if not changes:
            raise PropertyValidationError(
                "update_details was called with no changes; deciding that nothing changed is "
                "the use case's job, because the same decision governs whether an AuditLog row "
                "is written."
            )
        rejected = sorted(set(changes) - PATCHABLE_PROPERTY_FIELDS)
        if rejected:
            # Refused rather than filtered out. Silently dropping an unknown key would let a
            # caller believe it wrote `current_operational_state`, and the whole point of the
            # allowlist is that a route around `PropertyStateMachine` is impossible, not merely
            # ineffective. A rejected key is a programming error, so it surfaces as one.
            raise PropertyValidationError(
                f"Fields {rejected} are not patchable on a property. Only "
                "PATCHABLE_PROPERTY_FIELDS may be written here; current_operational_state in "
                "particular belongs to PropertyStateMachine alone."
            )
        try:
            result = await self._session.execute(
                update(PropertyModel)
                .where(PropertyModel.tenant_id == tenant_id, PropertyModel.id == property_id)
                .values(**dict(changes))
            )
        except IntegrityError as error:
            # A PATCH collides on the same two constraints an insert does: renaming a property's
            # `internal_code` to one already taken, or claiming a neighbouring row's external id.
            _translate_duplicate(error)
            raise
        return result.rowcount > 0

    async def set_wifi_password(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, secret: EncryptedSecret | None
    ) -> bool:
        result = await self._session.execute(
            update(PropertyModel)
            .where(PropertyModel.tenant_id == tenant_id, PropertyModel.id == property_id)
            .values(wifi_password_encrypted=secret.ciphertext if secret else None)
        )
        return result.rowcount > 0

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        filters: PropertyFilters,
        page: int,
        per_page: int,
    ) -> Page:
        """The count runs over the same filtered statement, so `total_pages` cannot describe a
        different result set than `data`."""
        conditions = _conditions(tenant_id, filters)
        total = await self._session.scalar(
            select(func.count()).select_from(PropertyModel).where(*conditions)
        )
        rows = await self._session.execute(
            _ordered(select(PropertyModel).where(*conditions))
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return Page(
            items=tuple(_to_property(model) for model in rows.scalars()),
            total=int(total or 0),
        )


class SqlAlchemyPropertyStateTransitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, transition: PropertyStateTransition) -> None:
        if transition.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property state transition",
                entity_tenant_id=transition.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            PropertyStateTransitionModel(
                id=transition.id,
                tenant_id=transition.tenant_id,
                property_id=transition.property_id,
                from_state=transition.from_state,
                to_state=transition.to_state,
                triggered_by=transition.triggered_by,
                triggered_by_user_id=transition.triggered_by_user_id,
                reason=transition.reason,
                # `metadata` is taken by SQLAlchemy's declarative API, so the column named
                # `metadata` in Postgres is reached through `metadata_` — the same rename
                # `SqlAlchemyTimelineEventRepository` documents.
                metadata_=transition.metadata or None,
                created_at=transition.created_at,
            )
        )
        await self._session.flush()

    async def applied_clock_triggers(
        self, tenant_id: uuid.UUID, reservation_ids: Collection[uuid.UUID]
    ) -> set[tuple[uuid.UUID, str]]:
        """The `(reservation_id, trigger)` pairs already recorded (design D1, as amended).

        Reads the two values straight out of `metadata` as text. `metadata->>'trigger'` is
        never turned back into `PropertyStateTrigger` — see the port's docstring; the caller
        compares against `trigger.value`.

        No index covers `metadata->>'reservation_id'` (declared as debt in the design's
        *Risks*), so the `IN` on the reservation ids is what keeps this bounded: it asks only
        about stays the caller already loaded.
        """
        ids = [str(reservation_id) for reservation_id in reservation_ids]
        if not ids:
            return set()
        reservation_key = PropertyStateTransitionModel.metadata_["reservation_id"].astext
        trigger_key = PropertyStateTransitionModel.metadata_["trigger"].astext
        result = await self._session.execute(
            select(reservation_key, trigger_key).where(
                PropertyStateTransitionModel.tenant_id == tenant_id,
                reservation_key.in_(ids),
            )
        )
        return {
            (uuid.UUID(reservation_id), trigger)
            for reservation_id, trigger in result.all()
            if reservation_id is not None and trigger is not None
        }

    async def last_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> PropertyStateTransition | None:
        """The newest row for that property within the tenant (`dashboard-api` R3.1).

        `id DESC` as the tiebreaker for the same reason the timeline reader needs one: the
        transition and its `TimelineEvent` are written with the instant the use case decided
        on, not with `now()`, so two transitions of one operation can share `created_at` and
        "the last one" would otherwise be whichever the planner happened to return.

        `ix_property_state_transitions_property_id_created_at` covers the leading keys.
        """
        result = await self._session.execute(
            select(PropertyStateTransitionModel)
            .where(
                PropertyStateTransitionModel.tenant_id == tenant_id,
                PropertyStateTransitionModel.property_id == property_id,
            )
            .order_by(
                PropertyStateTransitionModel.created_at.desc(),
                PropertyStateTransitionModel.id.desc(),
            )
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _to_transition(model) if model is not None else None


def _to_transition(model: PropertyStateTransitionModel) -> PropertyStateTransition:
    return PropertyStateTransition(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        to_state=model.to_state,
        triggered_by=model.triggered_by,
        created_at=model.created_at,
        from_state=model.from_state,
        triggered_by_user_id=model.triggered_by_user_id,
        reason=model.reason,
        metadata=model.metadata_ or {},
    )


def _translate_duplicate(error: IntegrityError) -> None:
    """Raise the domain error for a known constraint, or return so the caller re-raises.

    The named constraint is the authority on duplicates, never a prior read: two concurrent
    creations of the same `internal_code` both pass a lookup and only one can pass the index, so
    translating here is what makes the `409` race-free (`user-management` recorded the same
    reasoning for `uq_users_lower_email`).

    Returning on anything else is deliberate — a `409` blamed on a foreign key the client cannot
    see would be a lie it has no way to act on.
    """
    message = str(error.orig)
    if INTERNAL_CODE_CONSTRAINT in message:
        raise DuplicateInternalCodeError(
            "A property with that internal_code already exists for this tenant"
        ) from error
    if PMS_EXTERNAL_ID_CONSTRAINT in message:
        raise DuplicatePmsExternalIdError(
            "Another property of this tenant already claims that pms_external_id"
        ) from error


def _conditions(tenant_id: uuid.UUID, filters: PropertyFilters) -> list:
    conditions = [PropertyModel.tenant_id == tenant_id]
    if filters.status is not None:
        conditions.append(PropertyModel.status == filters.status)
    if filters.current_operational_state is not None:
        conditions.append(
            PropertyModel.current_operational_state == filters.current_operational_state
        )
    return conditions


def _ordered(statement: Select) -> Select:
    """By name, `id` as the tie-break.

    Without the second key two properties sharing a name could swap places between pages, and a
    client paging through would see one twice and miss the other.
    """
    return statement.order_by(PropertyModel.name, PropertyModel.id)


def _to_property(model: PropertyModel) -> Property:
    return Property(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        internal_code=model.internal_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        pms_external_id=model.pms_external_id,
        pms_provider=model.pms_provider,
        address_line1=model.address_line1,
        address_line2=model.address_line2,
        city=model.city,
        province=model.province,
        postal_code=model.postal_code,
        country=model.country,
        timezone=model.timezone,
        max_guests=model.max_guests,
        bedrooms=model.bedrooms,
        bathrooms=model.bathrooms,
        current_operational_state=model.current_operational_state,
        default_check_in_time=model.default_check_in_time,
        default_check_out_time=model.default_check_out_time,
        wifi_name=model.wifi_name,
        # The PRESENCE of the secret, never the secret (R5.2). `wifi_password_encrypted` itself is
        # intentionally not mapped onto the entity (design D2): nothing reads it, and leaving it
        # off keeps it off every serialisation path.
        has_wifi_password=model.wifi_password_encrypted is not None,
        access_notes=model.access_notes,
        cleaning_notes=model.cleaning_notes,
        emergency_notes=model.emergency_notes,
        status=model.status,
    )
