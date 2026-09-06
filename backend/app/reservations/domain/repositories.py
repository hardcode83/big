"""The port of the reservations aggregate (design D5, D9, D12).

Every method takes `tenant_id` explicitly and speaks in domain entities, never ORM
models. Reads outside the tenant return `None`/empty, which is what lets the use cases
answer `404` without ever asking "does it exist somewhere else?" (R5.1, design D6).
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationStatus
from app.reservations.domain.exceptions import ReservationValidationError

# `whatsapp-cloud-adapter` design D5: how far past check-out (or before check-in) a stay is
# still considered "active" for phone-to-reservation matching (R4.2, R4.4) — covers
# early-arrival/late-checkout questions without treating every past guest as indefinitely
# active. A named constant, not a literal `2` inline, so a later change can retune it
# without hunting for the number (confirmed with the user in design D5).
RESERVATION_MATCH_GRACE_DAYS = 2


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

    def __post_init__(self) -> None:
        """An inverted range is a contradiction, not an empty result.

        The rule lives here rather than in the router (where it started, and where the
        architecture review caught it): `steering/backend.md` says "la lógica nunca vive en el
        router", and this way any future caller of `ListReservationsUseCase` — a dashboard
        aggregate, a scheduled report — gets the same answer instead of silently receiving
        zero rows.
        """
        if self.date_from is not None and self.date_to is not None:
            if self.date_to < self.date_from:
                raise ReservationValidationError("date_to cannot be earlier than date_from")


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

    async def list_for_properties(
        self,
        tenant_id: uuid.UUID,
        property_ids: Collection[uuid.UUID],
        date_from: date,
        date_to: date,
        # `Sequence`, not `list`: this Protocol defines a method called `list`, which
        # shadows the builtin inside the class body and makes `list[Reservation]` a
        # `TypeError` at import time.
    ) -> Sequence[Reservation]:
        """Every reservation of those properties whose stay overlaps the range.

        Added by `celery-jobs` (its R3): its scheduled jobs need the reservations of a
        batch of candidate properties in one query rather than paginating per property.
        Unpaginated on purpose — the caller bounds the result with a window of a few days
        (design D3), not with a page size.

        Same overlap criterion as `ReservationFilters` (design D12), and **no status
        filter**: which statuses are eligible is `PropertyStateMachine`'s decision, and
        pre-filtering here would put a second copy of that policy in SQL.

        An empty `property_ids` returns an empty list without querying.
        """
        ...

    async def find_active_for_guest(
        self, tenant_id: uuid.UUID, guest_id: uuid.UUID, *, on_date: date
    ) -> Sequence[Reservation]:
        """Which stay a guest's WhatsApp message is about (`whatsapp-cloud-adapter` R4.2, R4.4).

        A reservation matches when its stay window, widened by `RESERVATION_MATCH_GRACE_DAYS`
        on each side, contains `on_date`: `check_in_date - RESERVATION_MATCH_GRACE_DAYS <=
        on_date <= check_out_date + RESERVATION_MATCH_GRACE_DAYS` (design D5). No status
        filter — which statuses count as a live stay is a decision for the caller (R4.4's
        escalation), the same way `list_for_properties` leaves status filtering to
        `PropertyStateMachine` rather than duplicating that policy here.

        More than one match is not an error here — it is exactly the signal R4.4 asks the
        caller to escalate on, so this returns every match rather than picking one.
        """
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

    async def count_check_ins_in_range(
        self, tenant_id: uuid.UUID, date_from: date, date_to: date
    ) -> int:
        """How many reservations check in within `[date_from, date_to]`, both inclusive
        (`dashboard-operational-kpis` R2).

        **A different question from `list_for_properties`'s stay overlap**: this counts
        `check_in_date` falling in the window, not "any stay touching it" — R2.1 asks for
        check-ins, not occupancy. `CANCELLED`/`NO_SHOW` are excluded and baked into the
        method rather than a parameter, the same reasoning `list_live_for_properties`
        gives for `LIVE_STATUSES`.

        Tenant-wide, not batched by property: unlike `list_for_properties`, this answers
        "how many, in total" and has no reason to enumerate properties first.

        Returns `0`, never `None`, when nothing checks in within the window.
        """
        ...
