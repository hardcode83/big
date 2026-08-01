"""Request/response DTOs for the reservation endpoints (PRD §23, R1).

Two rules this module exists to enforce:

* **No request schema has a `tenant_id`** — the effective tenant comes only from the
  verified token (R5.2), so one sent in a body is rejected by `extra="forbid"` and never
  reaches a use case.
* **Response fields are enumerated, never dumped from the entity.** `Reservation` grows
  fields owned by other modules, and a `from_attributes` dump would publish each new one
  automatically. The guest is serialised from `GuestSummary`, which structurally has no
  document data (design D17).
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.guests.domain.value_objects import GuestSummary
from app.reservations.application.use_cases import ReservationDetail
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import (
    PaymentStatus,
    ReservationAccessStatus,
    ReservationChannel,
    ReservationStatus,
)
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus

MAX_PER_PAGE = 100
# `page` needs a ceiling too, not just `per_page`: the value becomes a SQL OFFSET, and a
# 20-digit page number overflows int8 and comes back as an unhandled driver error instead of a
# 422 in the PRD §23 envelope (found by the security review of section 4). At 100 rows per page
# this still allows ten million rows, far past anything this system will hold.
MAX_PAGE = 100_000
MAX_TEXT = 5000


class CreateReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: uuid.UUID
    channel: ReservationChannel = ReservationChannel.DIRECT
    check_in_date: date
    check_out_date: date
    adults: Annotated[int, Field(ge=1, le=50)] = 1
    children: Annotated[int, Field(ge=0, le=50)] = 0
    guest_id: uuid.UUID | None = None
    check_in_time: time | None = None
    check_out_time: time | None = None
    gross_amount: Annotated[Decimal | None, Field(ge=0, max_digits=10, decimal_places=2)] = None
    ota_commission: Annotated[Decimal | None, Field(ge=0, max_digits=10, decimal_places=2)] = None
    net_amount: Annotated[Decimal | None, Field(ge=0, max_digits=10, decimal_places=2)] = None
    currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")] = "EUR"
    payment_status: PaymentStatus = PaymentStatus.PENDING
    cleaning_required: bool = True
    special_requests: Annotated[str | None, Field(max_length=MAX_TEXT)] = None
    internal_notes: Annotated[str | None, Field(max_length=MAX_TEXT)] = None
    external_channel_id: Annotated[str | None, Field(max_length=200)] = None


class UpdateReservationRequest(BaseModel):
    """Every field optional; only those present are applied (R1.5).

    `model_fields_set` is what distinguishes "not sent" from "sent as null", so a caller
    can clear `internal_notes` by sending `null` without every other unsent field being
    treated as a clear.
    """

    model_config = ConfigDict(extra="forbid")

    guest_id: uuid.UUID | None = None
    status: ReservationStatus | None = None
    check_in_date: date | None = None
    check_out_date: date | None = None
    check_in_time: time | None = None
    check_out_time: time | None = None
    adults: Annotated[int | None, Field(ge=1, le=50)] = None
    children: Annotated[int | None, Field(ge=0, le=50)] = None
    gross_amount: Annotated[Decimal | None, Field(ge=0, max_digits=10, decimal_places=2)] = None
    ota_commission: Annotated[Decimal | None, Field(ge=0, max_digits=10, decimal_places=2)] = None
    net_amount: Annotated[Decimal | None, Field(ge=0, max_digits=10, decimal_places=2)] = None
    currency: Annotated[str | None, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")] = None
    payment_status: PaymentStatus | None = None
    cleaning_required: bool | None = None
    special_requests: Annotated[str | None, Field(max_length=MAX_TEXT)] = None
    internal_notes: Annotated[str | None, Field(max_length=MAX_TEXT)] = None

    def changes(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.model_fields_set}


class GuestSummaryResponse(BaseModel):
    """The guest as a reservation may show it — no document data at all (R1.8, D17)."""

    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    preferred_language: str
    document_status: GuestDocumentStatus
    legal_registration_status: LegalRegistrationStatus

    @classmethod
    def from_domain(cls, guest: GuestSummary) -> "GuestSummaryResponse":
        return cls(
            id=guest.id,
            full_name=guest.full_name,
            email=guest.email,
            phone=guest.phone,
            preferred_language=guest.preferred_language,
            document_status=guest.document_status,
            legal_registration_status=guest.legal_registration_status,
        )


class ReservationResponse(BaseModel):
    id: uuid.UUID
    property_id: uuid.UUID
    guest_id: uuid.UUID | None
    external_pms_id: str | None
    external_channel_id: str | None
    channel: ReservationChannel
    status: ReservationStatus
    check_in_date: date
    check_out_date: date
    check_in_time: time | None
    check_out_time: time | None
    nights: int
    adults: int
    children: int
    total_guests: int
    gross_amount: Decimal | None
    ota_commission: Decimal | None
    net_amount: Decimal | None
    currency: str
    payment_status: PaymentStatus
    access_status: ReservationAccessStatus
    legal_registration_status: LegalRegistrationStatus
    cleaning_required: bool
    special_requests: str | None
    internal_notes: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, reservation: Reservation) -> "ReservationResponse":
        return cls(
            id=reservation.id,
            property_id=reservation.property_id,
            guest_id=reservation.guest_id,
            external_pms_id=reservation.external_pms_id,
            external_channel_id=reservation.external_channel_id,
            channel=reservation.channel,
            status=reservation.status,
            check_in_date=reservation.check_in_date,
            check_out_date=reservation.check_out_date,
            check_in_time=reservation.check_in_time,
            check_out_time=reservation.check_out_time,
            nights=reservation.nights,
            adults=reservation.adults,
            children=reservation.children,
            total_guests=reservation.total_guests,
            gross_amount=reservation.gross_amount,
            ota_commission=reservation.ota_commission,
            net_amount=reservation.net_amount,
            currency=reservation.currency,
            payment_status=reservation.payment_status,
            access_status=reservation.access_status,
            legal_registration_status=reservation.legal_registration_status,
            cleaning_required=reservation.cleaning_required,
            special_requests=reservation.special_requests,
            internal_notes=reservation.internal_notes,
            created_at=reservation.created_at,
            updated_at=reservation.updated_at,
        )


class ReservationDetailResponse(ReservationResponse):
    guest: GuestSummaryResponse | None = None

    @classmethod
    def from_detail(cls, detail: ReservationDetail) -> "ReservationDetailResponse":
        base = ReservationResponse.from_domain(detail.reservation)
        return cls(
            **base.model_dump(),
            guest=(
                GuestSummaryResponse.from_domain(detail.guest)
                if detail.guest is not None
                else None
            ),
        )


class ReservationPageResponse(BaseModel):
    """The pagination envelope of PRD §23, verbatim."""

    data: list[ReservationResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, items: tuple[Reservation, ...], *, total: int, page: int, per_page: int
    ) -> "ReservationPageResponse":
        # Ceiling division rather than a float round: 21 rows at 20 per page is 2 pages,
        # and 0 rows is 0 pages, not 1.
        total_pages = -(-total // per_page) if per_page else 0
        return cls(
            data=[ReservationResponse.from_domain(item) for item in items],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )
