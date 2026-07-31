"""The port of the reservations aggregate (design D5, D9, D12).

Every method takes `tenant_id` explicitly and speaks in domain entities, never ORM
models. Reads outside the tenant return `None`/empty, which is what lets the use cases
answer `404` without ever asking "does it exist somewhere else?" (R5.1, design D6).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationStatus


@dataclass(frozen=True)
class ReservationFilters:
    """The filters of `GET /reservations` (R1.1), combined with AND.

    `date_from`/`date_to` are interpreted as **stay overlap**, not as "check-in inside
    the range" (design D12): the operational question is "which reservations fall in
    these dates", and a guest already in the flat on `date_from` is one of them even
    though they arrived earlier.
    """

    property_id: uuid.UUID | None = None
    status: ReservationStatus | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass(frozen=True)
class Page:
    """One page of results plus the total the client needs for `total_pages` (PRD §23)."""

    items: tuple[Reservation, ...]
    total: int


class ReservationRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID, reservation_id: uuid.UUID) -> Reservation | None:
        ...

    async def find_by_external_pms_id(
        self, tenant_id: uuid.UUID, external_pms_id: str
    ) -> Reservation | None:
        """The idempotency lookup of the ingest paths (R3.2, R4.5, design D9)."""
        ...

    async def list(
        self, tenant_id: uuid.UUID, filters: ReservationFilters, *, page: int, per_page: int
    ) -> Page:
        """Filtered, ordered and paginated (R1.1). The order must be stable (design D12)."""
        ...

    async def add(self, tenant_id: uuid.UUID, reservation: Reservation) -> None:
        """Persist a new reservation; refuses an entity of another tenant.

        Raises `DuplicateExternalReservationError` when the tenant already has a
        reservation with that `external_pms_id` — the unique constraint decides, not a
        prior read (design D9).
        """
        ...

    async def save(self, tenant_id: uuid.UUID, reservation: Reservation) -> None:
        """Persist changes to an existing reservation.

        Identity columns (`tenant_id`, `property_id`, `external_pms_id`) are never
        written: a repository able to move a row to another tenant would defeat the
        isolation rule, and one able to re-point the idempotency key would defeat D9.
        """
        ...
