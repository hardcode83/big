"""SQLAlchemy adapter for `AccessRecordRepository` (`access-notifications` design D1, D2).

Every statement filters `tenant_id` explicitly and both writes check it: the session listener
of `app/core/db.py` covers neither INSERTs nor the identity map (limits 3 and 4 of its own
docstring). No method commits — the use case owns the transaction.

**`save` writes two tables**, and the port says why: `reservations.access_status` is a
denormalised projection of `access_records.status` (design D1), and putting the projection
here is what stops a caller from persisting a transition without it.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessRecordStatus
from app.access.domain.exceptions import AccessRecordNotFoundError
from app.access.domain.repositories import (
    AccessRecordFilters,
    AccessRecordPage,
    ReservationNeedingAccess,
)
from app.access.infrastructure.models import AccessRecordModel
from app.core.tenancy import CrossTenantWriteError
from app.reservations.domain.enums import ReservationAccessStatus, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel

#: How `access_records.status` projects onto `reservations.access_status` (design D1).
#:
#: `REVOKED` has **no counterpart**: PRD §7.6 closes that enum at
#: `PENDING, CREATED_EXTERNAL, MANUAL_ADDED, DELIVERED, EXPIRED, NOT_REQUIRED` and the
#: project's convention is that the PRD's names are canonical, so it is not widened.
#: `NOT_REQUIRED` is what actually applies to the only thing that produces a revocation —
#: a cancelled stay needs no access — but it is an `ASSUMPTION` and it is recorded as one.
_PROJECTION: dict[AccessRecordStatus, ReservationAccessStatus] = {
    AccessRecordStatus.PENDING: ReservationAccessStatus.PENDING,
    AccessRecordStatus.CREATED_EXTERNAL: ReservationAccessStatus.CREATED_EXTERNAL,
    AccessRecordStatus.MANUAL_ADDED: ReservationAccessStatus.MANUAL_ADDED,
    AccessRecordStatus.DELIVERED: ReservationAccessStatus.DELIVERED,
    AccessRecordStatus.EXPIRED: ReservationAccessStatus.EXPIRED,
    AccessRecordStatus.REVOKED: ReservationAccessStatus.NOT_REQUIRED,  # ASSUMPTION
}

_TERMINAL = (AccessRecordStatus.REVOKED, AccessRecordStatus.EXPIRED)


class SqlAlchemyAccessRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: uuid.UUID, record_id: uuid.UUID
    ) -> AccessRecord | None:
        row = await self._session.execute(
            select(AccessRecordModel).where(
                AccessRecordModel.tenant_id == tenant_id,
                AccessRecordModel.id == record_id,
            )
        )
        model = row.scalar_one_or_none()
        return _to_record(model) if model is not None else None

    async def get_by_reservation(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> AccessRecord | None:
        row = await self._session.execute(
            select(AccessRecordModel)
            .where(
                AccessRecordModel.tenant_id == tenant_id,
                AccessRecordModel.reservation_id == reservation_id,
            )
            # Deterministic if a stay ever ends up with more than one: newest wins, rather
            # than letting the query plan decide. Same discipline as `GuestRepository`.
            .order_by(AccessRecordModel.created_at.desc(), AccessRecordModel.id)
            .limit(1)
        )
        model = row.scalar_one_or_none()
        return _to_record(model) if model is not None else None

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: AccessRecordFilters,
        *,
        page: int,
        per_page: int,
    ) -> AccessRecordPage:
        conditions = [AccessRecordModel.tenant_id == tenant_id]
        if filters.property_id is not None:
            conditions.append(AccessRecordModel.property_id == filters.property_id)
        if filters.reservation_id is not None:
            conditions.append(AccessRecordModel.reservation_id == filters.reservation_id)
        if filters.status is not None:
            conditions.append(AccessRecordModel.status == filters.status)

        total = await self._session.scalar(
            select(func.count()).select_from(AccessRecordModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(AccessRecordModel)
            .where(*conditions)
            .order_by(AccessRecordModel.created_at.desc(), AccessRecordModel.id)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return AccessRecordPage(
            items=tuple(_to_record(model) for model in rows.scalars()),
            total=total or 0,
        )

    async def add(self, tenant_id: uuid.UUID, record: AccessRecord) -> None:
        self._guard(tenant_id, record)
        self._session.add(
            AccessRecordModel(
                id=record.id,
                tenant_id=record.tenant_id,
                property_id=record.property_id,
                reservation_id=record.reservation_id,
                provider=record.provider,
                external_id=record.external_id,
                status=record.status,
                code_masked=record.code_masked,
                valid_from=record.valid_from,
                valid_to=record.valid_to,
                created_mode=record.created_mode,
                notes=record.notes,
            )
        )
        await self._session.flush()
        await self._project(tenant_id, record)

    async def save(self, tenant_id: uuid.UUID, record: AccessRecord) -> None:
        self._guard(tenant_id, record)
        result = await self._session.execute(
            update(AccessRecordModel)
            .where(
                AccessRecordModel.tenant_id == tenant_id,
                AccessRecordModel.id == record.id,
            )
            .values(
                provider=record.provider,
                external_id=record.external_id,
                status=record.status,
                code_masked=record.code_masked,
                valid_from=record.valid_from,
                valid_to=record.valid_to,
                created_mode=record.created_mode,
                notes=record.notes,
                updated_at=record.updated_at,
            )
        )
        if result.rowcount == 0:
            # Loud, like `mark_breached`: the caller has already moved the entity through
            # its state machine and written a timeline event by now, so a silent zero-row
            # UPDATE would leave the event claiming a transition the row never made.
            raise AccessRecordNotFoundError(record.id)
        await self._project(tenant_id, record)

    async def _project(self, tenant_id: uuid.UUID, record: AccessRecord) -> None:
        """`reservations.access_status`, in the same transaction (design D1).

        A record with no reservation projects nowhere — the column belongs to a stay, and
        `access_records.reservation_id` is nullable.
        """
        if record.reservation_id is None:
            return
        await self._session.execute(
            update(ReservationModel)
            .where(
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.id == record.reservation_id,
            )
            .values(access_status=_PROJECTION[record.status])
        )

    async def list_reservations_missing_records(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> Sequence[ReservationNeedingAccess]:
        """Stays that need a record made, and the two halves are NOT symmetric.

        The asymmetry is what makes the sweep converge, and getting it wrong in either
        direction produces a job that never settles. It was wrong in one direction until the
        feature-scale QA panel found it (see below).

        * A **live** stay needs a record that is still live. Having *any* record is not
          enough: a booking that was cancelled and then re-confirmed —
          `Reservation.UPDATABLE_FIELDS` allows `CANCELLED → CONFIRMED` and no state machine
          forbids it — owns a `REVOKED` record, which is history and cannot come back
          (`revoke()` is terminal by design D14). Excluding it on the strength of that record
          left an active booking with `access_status = NOT_REQUIRED` **for ever**. So the
          subquery here counts only NON-terminal records, and a re-confirmed stay gets a
          fresh `PENDING` one while the revoked row stays as the account of what happened.
        * A **cancelled** stay needs a record, full stop — one, in `REVOKED`. Skipping them
          entirely would mean every run re-found them and made a `PENDING` access for a
          booking that is off. But here *any* record excludes it: applying the live rule
          would make the job mint a new `REVOKED` row every five minutes.
        """
        live_record = select(AccessRecordModel.reservation_id).where(
            AccessRecordModel.tenant_id == tenant_id,
            AccessRecordModel.reservation_id.is_not(None),
            AccessRecordModel.status.not_in(_TERMINAL),
        )
        any_record = select(AccessRecordModel.reservation_id).where(
            AccessRecordModel.tenant_id == tenant_id,
            AccessRecordModel.reservation_id.is_not(None),
        )
        rows = await self._session.execute(
            select(
                ReservationModel.id,
                ReservationModel.property_id,
                ReservationModel.status,
            )
            .where(
                ReservationModel.tenant_id == tenant_id,
                # `PENDING` is excluded: a booking nobody has agreed to yet has no access to
                # arrange.
                ReservationModel.status != ReservationStatus.PENDING,
                or_(
                    and_(
                        ReservationModel.status != ReservationStatus.CANCELLED,
                        ReservationModel.id.not_in(live_record),
                    ),
                    and_(
                        ReservationModel.status == ReservationStatus.CANCELLED,
                        ReservationModel.id.not_in(any_record),
                    ),
                ),
            )
            # `ix_reservations_tenant_id_status` covers the tenant+status half of this.
            .order_by(ReservationModel.created_at, ReservationModel.id)
            .limit(limit)
        )
        return [
            ReservationNeedingAccess(
                reservation_id=row.id,
                property_id=row.property_id,
                cancelled=row.status is ReservationStatus.CANCELLED,
            )
            for row in rows
        ]

    async def list_expirable(
        self, tenant_id: uuid.UUID, *, now: datetime, limit: int
    ) -> Sequence[AccessRecord]:
        rows = await self._session.execute(
            select(AccessRecordModel)
            .where(
                AccessRecordModel.tenant_id == tenant_id,
                AccessRecordModel.valid_to.is_not(None),
                AccessRecordModel.valid_to < now,
                AccessRecordModel.status.not_in(_TERMINAL),
                # `PENDING` has nothing to expire — the entity refuses that transition, and
                # selecting it here would make the reconciler raise instead of skip.
                AccessRecordModel.status != AccessRecordStatus.PENDING,
            )
            .order_by(AccessRecordModel.valid_to, AccessRecordModel.id)
            .limit(limit)
        )
        return [_to_record(model) for model in rows.scalars()]

    async def list_revocable(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> Sequence[AccessRecord]:
        rows = await self._session.execute(
            select(AccessRecordModel)
            .join(ReservationModel, ReservationModel.id == AccessRecordModel.reservation_id)
            .where(
                AccessRecordModel.tenant_id == tenant_id,
                # The JOIN is on the id alone, so the neighbour's reservations would be
                # reachable through it if this second predicate were missing — the same trap
                # `cleaning` documented for `cleaning_checklist_completions`.
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.status == ReservationStatus.CANCELLED,
                AccessRecordModel.status.not_in(_TERMINAL),
            )
            .order_by(AccessRecordModel.created_at, AccessRecordModel.id)
            .limit(limit)
        )
        return [_to_record(model) for model in rows.scalars()]

    def _guard(self, tenant_id: uuid.UUID, record: AccessRecord) -> None:
        if record.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="access record",
                entity_tenant_id=record.tenant_id,
                acting_tenant_id=tenant_id,
            )


def _to_record(model: AccessRecordModel) -> AccessRecord:
    return AccessRecord(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        reservation_id=model.reservation_id,
        provider=model.provider,
        external_id=model.external_id,
        status=model.status,
        code_masked=model.code_masked,
        valid_from=model.valid_from,
        valid_to=model.valid_to,
        created_mode=model.created_mode,
        notes=model.notes,
    )
