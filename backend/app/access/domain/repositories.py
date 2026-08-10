"""Ports owned by the access domain (`access-notifications` design D1, D2).

Shaped by its two consumers: the operator endpoints of R3 and the reconciler of design D2.
`tenant_id` is a parameter of every method, including `add`, following
`app/auth/domain/ports.py` — one source of truth for the acting tenant per call, so a
repository instance cannot disagree with its caller about which tenant it serves.

**`save` also writes the reservation's `access_status` projection** (design D1). That is
deliberate coupling, stated here rather than discovered: `access_records.status` is the
truth, `reservations.access_status` is a denormalised copy for the dashboard, and the only
way the copy cannot drift is for the same call that moves one to move the other, in the
same transaction. It is also why `Reservation.UPDATABLE_FIELDS` excludes the column — no
other writer exists.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessRecordStatus


@dataclass(frozen=True)
class AccessRecordFilters:
    """What `GET /access-records` may narrow by (R3.1).

    No `tenant_id` here on purpose: the acting tenant is a separate argument, taken from the
    token, and a filter object that carried it would be one request body away from choosing
    it.
    """

    property_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    status: AccessRecordStatus | None = None


@dataclass(frozen=True)
class AccessRecordPage:
    """One page plus the total the client needs for `total_pages` (PRD §23)."""

    items: tuple[AccessRecord, ...]
    total: int


@dataclass(frozen=True)
class ReservationNeedingAccess:
    """The minimum the reconciler needs about a reservation (design D2).

    A projection rather than the `Reservation` entity, for the same reason
    `GuestRepository` returns `GuestSummary`: the job needs four fields, and handing it the
    aggregate would let a later edit reach `special_requests` or `internal_notes` from a
    context that has no business with them.
    """

    reservation_id: uuid.UUID
    property_id: uuid.UUID
    cancelled: bool


class AccessRecordRepository(Protocol):
    async def get(
        self, tenant_id: uuid.UUID, record_id: uuid.UUID
    ) -> AccessRecord | None:
        ...

    async def get_by_reservation(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> AccessRecord | None:
        """The access of one stay. `None` is the answer before the reconciler has run."""
        ...

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: AccessRecordFilters,
        *,
        page: int,
        per_page: int,
    ) -> AccessRecordPage:
        ...

    async def add(self, tenant_id: uuid.UUID, record: AccessRecord) -> None:
        """Persist a new record; refuses an entity belonging to another tenant."""
        ...

    async def save(self, tenant_id: uuid.UUID, record: AccessRecord) -> None:
        """Persist a moved record **and project `reservations.access_status`** (design D1).

        The projection happens here and not in the use case so that no caller can persist a
        transition without it. `AccessRecordStatus.REVOKED` has no counterpart in
        `ReservationAccessStatus` — PRD §7.6 closes that enum and its names are canonical —
        so it projects to `NOT_REQUIRED`, which is what actually applies to the only thing
        that produces `REVOKED`: a cancelled stay. `ASSUMPTION`, recorded in the spec.
        """
        ...

    async def list_reservations_missing_records(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> Sequence[ReservationNeedingAccess]:
        """Confirmed reservations with no access record yet (design D2, R1.1).

        The reconciler's work queue. `cancelled` travels with each row because the same
        sweep both creates and revokes: a stay cancelled before the job ever saw it needs a
        record in `REVOKED`, not no record at all — otherwise the next run would create a
        `PENDING` one for a booking that is off.
        """
        ...

    async def list_expirable(
        self, tenant_id: uuid.UUID, *, now: datetime, limit: int
    ) -> Sequence[AccessRecord]:
        """Live records whose `valid_to` has passed (design D14, OQ4).

        Returns nothing today: no code writes `valid_to`, because that is a real access
        provider's job and the MVP has none. The query exists so the path is built and
        tested rather than discovered later.
        """
        ...

    async def list_revocable(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> Sequence[AccessRecord]:
        """Live records whose reservation is cancelled (R1.4)."""
        ...
