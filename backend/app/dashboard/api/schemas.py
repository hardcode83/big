"""Response DTOs of the dashboard endpoints (PRD §9.1, §9.2, §23).

Every schema maps a frozen projection from `app/dashboard/domain/read_models.py` field by
field, with an explicit `from_domain`. Never `from_attributes`, for the reason
`PropertyResponse` and `CleaningTaskOut` both record: a projection gains fields over time
and a dump publishes each new one automatically. Here that would undo the whole point of
section 5 — the projections are narrow *so that* a serialiser cannot reach what is not on
them, and a dump would make the narrowing pointless the day a field is added.

Money crosses the wire as a **string**, not a float. `Decimal` is what the domain holds
(cents survive), and JSON has no decimal type — serialising through `float` is how `120.50`
becomes `120.49999999999999`. `dto.ts` types these `number | null`; a numeric string parses
cleanly on the other side and does not lose a cent on the way.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.dashboard.domain.read_models import (
    AccessBlock,
    ApprovalBlock,
    CleaningPhotoBlock,
    FinancialBlock,
    GuestBlock,
    IncidentBlock,
    NextActionBlock,
    PropertyDashboardCard,
    PropertyDetail,
    ReservationBlock,
)
from app.maintenance.domain.enums import IncidentSeverity
from app.properties.domain.enums import PropertyOperationalState

# The same bounds `GET /api/v1/properties` applies, and imported rather than restated so the
# two cannot drift (R1.5 requires "los mismos límites y validación").
from app.properties.api.schemas import MAX_PAGE, MAX_PER_PAGE

__all__ = [
    "MAX_PAGE",
    "MAX_PER_PAGE",
    "PropertyDashboardCardResponse",
    "PropertyDashboardPageResponse",
    "PropertyDetailResponse",
]


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class ReservationSummaryResponse(BaseModel):
    id: uuid.UUID
    reference: str | None
    guest_name: str | None
    check_in: date
    check_out: date

    @classmethod
    def from_domain(cls, block: ReservationBlock) -> "ReservationSummaryResponse":
        return cls(
            id=block.id,
            reference=block.reference,
            guest_name=block.guest_name,
            check_in=block.check_in,
            check_out=block.check_out,
        )


class NextActionResponse(BaseModel):
    label: str
    responsible: str | None

    @classmethod
    def from_domain(cls, block: NextActionBlock) -> "NextActionResponse":
        return cls(label=block.label, responsible=block.responsible)


class GuestResponse(BaseModel):
    """A name. Rule 4 of `steering/security.md` — nothing about the document, ever."""

    name: str | None

    @classmethod
    def from_domain(cls, block: GuestBlock) -> "GuestResponse":
        return cls(name=block.name)


class AccessResponse(BaseModel):
    """A status label. No code, in any form (R2.5)."""

    label: str | None

    @classmethod
    def from_domain(cls, block: AccessBlock) -> "AccessResponse":
        return cls(label=block.label)


class IncidentSummaryResponse(BaseModel):
    id: uuid.UUID
    title: str
    severity: IncidentSeverity
    opened_at: datetime

    @classmethod
    def from_domain(cls, block: IncidentBlock) -> "IncidentSummaryResponse":
        return cls(
            id=block.id,
            title=block.title,
            severity=block.severity,
            opened_at=block.opened_at,
        )


class FinancialSummaryResponse(BaseModel):
    currency: str
    reservation_total: str | None
    pending_expenses: str | None

    @classmethod
    def from_domain(cls, block: FinancialBlock) -> "FinancialSummaryResponse":
        return cls(
            currency=block.currency,
            reservation_total=_money(block.reservation_total),
            pending_expenses=_money(block.pending_expenses),
        )


class PendingApprovalResponse(BaseModel):
    id: uuid.UUID
    label: str
    amount: str | None
    currency: str | None

    @classmethod
    def from_domain(cls, block: ApprovalBlock) -> "PendingApprovalResponse":
        return cls(
            id=block.id,
            label=block.label,
            amount=_money(block.amount),
            currency=block.currency,
        )


class CleaningPhotoResponse(BaseModel):
    """Always an empty list today (R2.4, `EXTERNAL_DEPENDENCY`) — the signed URL needs
    `StorageAdapter.get_signed_url`, which `cleaning-photos-storage` delivers."""

    id: uuid.UUID
    url: str
    taken_at: datetime

    @classmethod
    def from_domain(cls, block: CleaningPhotoBlock) -> "CleaningPhotoResponse":
        return cls(id=block.id, url=block.url, taken_at=block.taken_at)


class PropertyDashboardCardResponse(BaseModel):
    """One card (`dto.ts:85-96`, R1.2).

    `current_or_next_reservation` is `None` and **present**, never omitted: R1.4 says
    "SHALL devolver `currentOrNextReservation: null` en vez de omitir la clave", and pydantic
    serialises a `None` field unless told otherwise — which nothing here does.
    """

    property_id: uuid.UUID
    property_code: str
    operational_state: PropertyOperationalState
    current_or_next_reservation: ReservationSummaryResponse | None
    cleaning_status: str | None
    open_incidents_count: int
    next_action: NextActionResponse | None
    last_event_label: str | None
    last_event_at: datetime | None

    @classmethod
    def from_domain(cls, card: PropertyDashboardCard) -> "PropertyDashboardCardResponse":
        return cls(
            property_id=card.property_id,
            property_code=card.property_code,
            operational_state=card.operational_state,
            current_or_next_reservation=(
                ReservationSummaryResponse.from_domain(card.current_or_next_reservation)
                if card.current_or_next_reservation is not None
                else None
            ),
            cleaning_status=card.cleaning_status,
            open_incidents_count=card.open_incidents_count,
            next_action=(
                NextActionResponse.from_domain(card.next_action)
                if card.next_action is not None
                else None
            ),
            last_event_label=card.last_event_label,
            last_event_at=card.last_event_at,
        )


class PropertyDashboardPageResponse(BaseModel):
    """The pagination envelope of PRD §23."""

    data: list[PropertyDashboardCardResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls,
        cards: tuple[PropertyDashboardCard, ...],
        *,
        total: int,
        page: int,
        per_page: int,
    ) -> "PropertyDashboardPageResponse":
        return cls(
            data=[PropertyDashboardCardResponse.from_domain(card) for card in cards],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )


class PropertyDetailResponse(BaseModel):
    """The aggregate of PRD §9.2 (`dto.ts:161-174`, R2.1)."""

    property_id: uuid.UUID
    property_code: str
    operational_state: PropertyOperationalState
    current_or_next_reservation: ReservationSummaryResponse | None
    guest: GuestResponse | None
    access: AccessResponse | None
    cleaning_status: str | None
    last_cleaning_photos: list[CleaningPhotoResponse]
    open_incidents: list[IncidentSummaryResponse]
    financial: FinancialSummaryResponse | None
    notes: str | None
    pending_approvals: list[PendingApprovalResponse]

    @classmethod
    def from_domain(cls, detail: PropertyDetail) -> "PropertyDetailResponse":
        return cls(
            property_id=detail.property_id,
            property_code=detail.property_code,
            operational_state=detail.operational_state,
            current_or_next_reservation=(
                ReservationSummaryResponse.from_domain(detail.current_or_next_reservation)
                if detail.current_or_next_reservation is not None
                else None
            ),
            guest=(
                GuestResponse.from_domain(detail.guest) if detail.guest is not None else None
            ),
            access=(
                AccessResponse.from_domain(detail.access)
                if detail.access is not None
                else None
            ),
            cleaning_status=detail.cleaning_status,
            last_cleaning_photos=[
                CleaningPhotoResponse.from_domain(photo)
                for photo in detail.last_cleaning_photos
            ],
            open_incidents=[
                IncidentSummaryResponse.from_domain(incident)
                for incident in detail.open_incidents
            ],
            financial=(
                FinancialSummaryResponse.from_domain(detail.financial)
                if detail.financial is not None
                else None
            ),
            notes=detail.notes,
            pending_approvals=[
                PendingApprovalResponse.from_domain(approval)
                for approval in detail.pending_approvals
            ],
        )
