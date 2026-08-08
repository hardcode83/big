"""Use cases of the access module (R1, R2, R3; design D1, D2, D9, D12, D14).

One use case is one business operation and one transaction (`reservations` design D4). No
business rule lives here — the state machine is `AccessRecord`'s — and no `sqlalchemy` import
either, which `tests/test_layering.py` enforces for this layer.

Every operator action writes four things in that single transaction: the record, the
projection onto `reservations.access_status` (which the repository does, design D1), a
`TimelineEvent` from PRD §15's list, and an `AuditLog` row, because rule 9 of
`sdd/steering/security.md` names `AccessRecord` explicitly.

**The plaintext code exists only as a parameter of `RegisterManualAccessCodeUseCase.execute`
and dies inside the entity** (design D9). It reaches no repository, no timeline event, no
audit diff and no log line.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessRecordStatus
from app.access.domain.exceptions import AccessRecordNotFoundError
from app.access.domain.ports import AccessProviderAdapter, LegalRegistrationInitialiser
from app.access.domain.repositories import (
    AccessRecordFilters,
    AccessRecordPage,
    AccessRecordRepository,
)
from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.core.unit_of_work import UnitOfWork
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

logger = logging.getLogger(__name__)

#: PRD §15: "Timeline events: `ACCESS_CODE_PENDING` → `ACCESS_CODE_CREATED_EXTERNAL` o
#: `ACCESS_CODE_MANUAL_ADDED` → `ACCESS_CODE_DELIVERED`". One per resulting status, so the
#: use cases cannot disagree with each other about which event a transition produces.
#:
#: `REVOKED` and `EXPIRED` have **no timeline event**, and that is not an omission: PRD §15
#: lists four and the enum has exactly four. Inventing `ACCESS_CODE_REVOKED` would put a value
#: in an append-only table that no reader knows, and the `AuditLog` row already records it.
_EVENT_FOR: dict[AccessRecordStatus, TimelineEventType] = {
    AccessRecordStatus.PENDING: TimelineEventType.ACCESS_CODE_PENDING,
    AccessRecordStatus.CREATED_EXTERNAL: TimelineEventType.ACCESS_CODE_CREATED_EXTERNAL,
    AccessRecordStatus.MANUAL_ADDED: TimelineEventType.ACCESS_CODE_MANUAL_ADDED,
    AccessRecordStatus.DELIVERED: TimelineEventType.ACCESS_CODE_DELIVERED,
}

_TITLE_FOR: dict[AccessRecordStatus, str] = {
    AccessRecordStatus.PENDING: "Access pending",
    AccessRecordStatus.CREATED_EXTERNAL: "Access managed by the provider",
    AccessRecordStatus.MANUAL_ADDED: "Access code registered",
    AccessRecordStatus.DELIVERED: "Access instructions delivered",
}

_ACTION_FOR: dict[AccessRecordStatus, str] = {
    AccessRecordStatus.CREATED_EXTERNAL: audit_actions.ACCESS_MARKED_EXTERNAL,
    AccessRecordStatus.MANUAL_ADDED: audit_actions.ACCESS_CODE_REGISTERED,
    AccessRecordStatus.DELIVERED: audit_actions.ACCESS_DELIVERED,
    AccessRecordStatus.REVOKED: audit_actions.ACCESS_REVOKED,
    AccessRecordStatus.EXPIRED: audit_actions.ACCESS_EXPIRED,
}


@dataclass(frozen=True)
class AccessActor:
    """Who is acting, and from where — the two things `audit_logs` records that nothing else
    does (rule 9). Same shape as `CleaningActor`, minus its row-level restriction: there is no
    role that sees only *some* of a tenant's accesses."""

    user_id: uuid.UUID
    ip: str | None = None


class _AccessOperationBase:
    """The shared middle of every operator action on an access record.

    Load within the tenant, move the entity through its own state machine, persist, write the
    timeline event and the audit row, commit once. Written once because six copies would be
    six chances to forget the audit row that rule 9 requires.
    """

    def __init__(
        self,
        *,
        records: AccessRecordRepository,
        provider: AccessProviderAdapter,
        timeline: TimelineEventRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._records = records
        self._provider = provider
        self._timeline = timeline
        self._audit = audit
        self._uow = uow

    async def _load(self, tenant_id: uuid.UUID, record_id: uuid.UUID) -> AccessRecord:
        record = await self._records.get(tenant_id, record_id)
        if record is None:
            # R3.3: identical to "does not exist", so the endpoint is not an existence oracle
            # across tenants.
            raise AccessRecordNotFoundError(record_id)
        return record

    async def _persist(
        self,
        *,
        tenant_id: uuid.UUID,
        record: AccessRecord,
        previous: AccessRecordStatus,
        actor: AccessActor | None,
        notes_changed: bool,
        now: datetime,
    ) -> None:
        await self._records.save(tenant_id, record)
        await self._record_event(tenant_id=tenant_id, record=record, actor=actor, now=now)
        await self._record_audit(
            tenant_id=tenant_id,
            record=record,
            previous=previous,
            actor=actor,
            notes_changed=notes_changed,
            now=now,
        )

    async def _record_event(
        self,
        *,
        tenant_id: uuid.UUID,
        record: AccessRecord,
        actor: AccessActor | None,
        now: datetime,
    ) -> None:
        event_type = _EVENT_FOR.get(record.status)
        if event_type is None:
            # `REVOKED`/`EXPIRED`: PRD §15 declares no event and the audit row carries it.
            return
        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                TimelineEventData(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    property_id=record.property_id,
                    reservation_id=record.reservation_id,
                    actor_type=(
                        TimelineActorType.USER if actor is not None else TimelineActorType.SYSTEM
                    ),
                    actor_user_id=actor.user_id if actor is not None else None,
                    event_type=event_type,
                    title=_TITLE_FOR[record.status],
                    created_at=now,
                    # Ids and a status, never `code_masked`: the timeline is append-only, so
                    # anything written here can never be redacted afterwards.
                    metadata={"access_record_id": str(record.id), "status": record.status.value},
                )
            ),
        )

    async def _record_audit(
        self,
        *,
        tenant_id: uuid.UUID,
        record: AccessRecord,
        previous: AccessRecordStatus,
        actor: AccessActor | None,
        notes_changed: bool,
        now: datetime,
    ) -> None:
        changes = ChangeSet(audit_actions.ENTITY_ACCESS_RECORD).diff(
            "status", previous.value, record.status.value
        )
        if record.code_masked is not None and record.status is AccessRecordStatus.MANUAL_ADDED:
            # The masked form is what the entity stores and what rule 4 grants, so it may be
            # recorded as a diff — `code_masked` is deliberately absent from `REDACTED_FIELDS`
            # for exactly this. There is no plaintext anywhere to leak.
            changes = changes.diff("code_masked", None, record.code_masked)
        if notes_changed:
            # `redacted()`, not `diff()`: free text an operator types is where a door code
            # gets pasted. Same discipline `properties-crud` design D7 applies to its notes.
            changes = changes.redacted("notes")
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=_ACTION_FOR[record.status],
                entity_type=audit_actions.ENTITY_ACCESS_RECORD,
                entity_id=record.id,
                actor_user_id=actor.user_id if actor is not None else None,
                actor_ip=actor.ip if actor is not None else None,
                changes=changes,
                now=now,
            ),
        )


class RegisterManualAccessCodeUseCase(_AccessOperationBase):
    """R2.2 — the operator registers the code they arranged with the provider."""

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        record_id: uuid.UUID,
        code: str,
        notes: str | None,
        actor: AccessActor,
        now: datetime,
    ) -> AccessRecord:
        record = await self._load(tenant_id, record_id)
        previous = record.status
        # Through the adapter, not by calling the entity directly: PRD §3.3 puts every
        # external system behind one, and the day GrinPass or TTLock arrives this line does
        # not change.
        record = await self._provider.create_manual_access(
            record=record, code=code, notes=notes, now=now
        )
        await self._persist(
            tenant_id=tenant_id,
            record=record,
            previous=previous,
            actor=actor,
            notes_changed=notes is not None,
            now=now,
        )
        await self._uow.commit()
        return record


class MarkAccessExternallyManagedUseCase(_AccessOperationBase):
    """R2.3 — the provider created and owns this access."""

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        record_id: uuid.UUID,
        notes: str | None,
        actor: AccessActor,
        now: datetime,
    ) -> AccessRecord:
        record = await self._load(tenant_id, record_id)
        previous = record.status
        record = await self._provider.mark_external_managed(
            record=record, notes=notes, now=now
        )
        await self._persist(
            tenant_id=tenant_id,
            record=record,
            previous=previous,
            actor=actor,
            notes_changed=notes is not None,
            now=now,
        )
        await self._uow.commit()
        return record


class MarkAccessDeliveredUseCase(_AccessOperationBase):
    """R2.4 — the operator confirms the guest has the instructions."""

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        record_id: uuid.UUID,
        actor: AccessActor,
        now: datetime,
    ) -> AccessRecord:
        record = await self._load(tenant_id, record_id)
        previous = record.status
        record.mark_delivered(now=now)
        await self._persist(
            tenant_id=tenant_id,
            record=record,
            previous=previous,
            actor=actor,
            notes_changed=False,
            now=now,
        )
        await self._uow.commit()
        return record


class GetAccessRecordUseCase:
    def __init__(self, *, records: AccessRecordRepository) -> None:
        self._records = records

    async def execute(
        self, *, tenant_id: uuid.UUID, record_id: uuid.UUID
    ) -> AccessRecord:
        record = await self._records.get(tenant_id, record_id)
        if record is None:
            raise AccessRecordNotFoundError(record_id)
        return record


class ListAccessRecordsUseCase:
    def __init__(self, *, records: AccessRecordRepository) -> None:
        self._records = records

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: AccessRecordFilters,
        page: int,
        per_page: int,
    ) -> AccessRecordPage:
        return await self._records.list(tenant_id, filters, page=page, per_page=per_page)


@dataclass
class ProvisionReport:
    """What one reconciliation run did (design D2)."""

    created: int = 0
    revoked: int = 0
    expired: int = 0
    legal_status_initialised: int = 0


class ProvisionAccessRecordsUseCase(_AccessOperationBase):
    """The reconciler of design D2 — R1.1, R1.2, R1.3, R1.4 and R6.2.

    **A sweep, not a hook**, and the reason is not elegance: there are already confirmed
    reservations in the database. A hook on the confirmation transition would only ever cover
    future ones and leave the whole history without an access record. Confirmations also
    arrive by three different routes — the PATCH, the CSV import and the PMS sync, the last
    two through `ReservationStatus.parse_ingested`, which **defaults to `CONFIRMED`** — so
    hooking them is three places to forget.

    Idempotent by construction (R1.3): the work queue is "confirmed **without** a record", so
    a second pass finds nothing and writes nothing, without keeping any state of its own.
    That is the same mechanism `EscalateBreachedSlasUseCase` uses with `sla_breached`.

    **Actor `SYSTEM`, with `AuditLog` rows that carry no actor.** Rule 9 of
    `steering/security.md` names `AccessRecord` in its enumeration and its named exception is
    about *property state transitions*, so it does not extend here: the rows are written, they
    simply have no person to name — exactly like the credential-resolution rows of
    `pms-provider-resolution`. The volume is one row per reservation, once, not the repetitive
    pattern that exception was carved for.
    """

    def __init__(
        self,
        *,
        records: AccessRecordRepository,
        provider: AccessProviderAdapter,
        timeline: TimelineEventRepository,
        audit: AuditLogRepository,
        legal: LegalRegistrationInitialiser,
        uow: UnitOfWork,
        batch_size: int,
    ) -> None:
        super().__init__(
            records=records, provider=provider, timeline=timeline, audit=audit, uow=uow
        )
        self._legal = legal
        self._batch_size = batch_size

    async def execute(
        self, *, tenant_id: uuid.UUID, now: datetime
    ) -> ProvisionReport:
        report = ProvisionReport()
        await self._create_missing(tenant_id, now, report)
        await self._revoke_cancelled(tenant_id, now, report)
        await self._expire_elapsed(tenant_id, now, report)
        await self._uow.commit()
        return report

    async def _create_missing(
        self, tenant_id: uuid.UUID, now: datetime, report: ProvisionReport
    ) -> None:
        pending = await self._records.list_reservations_missing_records(
            tenant_id, limit=self._batch_size
        )
        for stay in pending:
            record = AccessRecord(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=stay.property_id,
                created_at=now,
                updated_at=now,
                reservation_id=stay.reservation_id,
            )
            if stay.cancelled:
                # A stay cancelled before this job first ran still gets a record, in
                # `REVOKED`. Without one the next run would find it again and create a
                # `PENDING` access for a booking that is off — a reconciler that never
                # converges.
                record.revoke(reason="reservation cancelled", now=now)
            await self._records.add(tenant_id, record)
            await self._record_event(
                tenant_id=tenant_id, record=record, actor=None, now=now
            )
            await self._audit.add(
                tenant_id,
                AuditLogFactory.build(
                    tenant_id=tenant_id,
                    action=(
                        audit_actions.ACCESS_REVOKED
                        if stay.cancelled
                        else audit_actions.ACCESS_RECORD_CREATED
                    ),
                    entity_type=audit_actions.ENTITY_ACCESS_RECORD,
                    entity_id=record.id,
                    actor_user_id=None,
                    actor_ip=None,
                    changes=ChangeSet(audit_actions.ENTITY_ACCESS_RECORD).diff(
                        "status", None, record.status.value
                    ),
                    now=now,
                ),
            )
            if stay.cancelled:
                report.revoked += 1
            else:
                report.created += 1
            # R6.2 — PRD §17 step 1: "Al confirmar reserva: `legal_registration_status =
            # PENDING_GUEST_DATA`". It rides along with this sweep because it answers the same
            # question ("what has this confirmed stay not been given yet?") and because a
            # second job over the same rows would be a second thing to get out of step.
            if not stay.cancelled and await self._legal.initialise(
                tenant_id=tenant_id, reservation_id=stay.reservation_id, now=now
            ):
                report.legal_status_initialised += 1

    async def _revoke_cancelled(
        self, tenant_id: uuid.UUID, now: datetime, report: ProvisionReport
    ) -> None:
        for record in await self._records.list_revocable(
            tenant_id, limit=self._batch_size
        ):
            previous = record.status
            record.revoke(reason="reservation cancelled", now=now)
            await self._persist(
                tenant_id=tenant_id,
                record=record,
                previous=previous,
                actor=None,
                notes_changed=True,
                now=now,
            )
            report.revoked += 1

    async def _expire_elapsed(
        self, tenant_id: uuid.UUID, now: datetime, report: ProvisionReport
    ) -> None:
        for record in await self._records.list_expirable(
            tenant_id, now=now, limit=self._batch_size
        ):
            previous = record.status
            record.expire(now=now)
            await self._persist(
                tenant_id=tenant_id,
                record=record,
                previous=previous,
                actor=None,
                notes_changed=False,
                now=now,
            )
            report.expired += 1
