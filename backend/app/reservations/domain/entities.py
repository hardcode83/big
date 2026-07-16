import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from app.guests.domain.enums import LegalRegistrationStatus
from app.reservations.domain.enums import (
    PaymentStatus,
    ReservationAccessStatus,
    ReservationChannel,
    ReservationStatus,
)


@dataclass
class Reservation:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    channel: ReservationChannel
    check_in_date: date
    check_out_date: date
    nights: int
    created_at: datetime
    updated_at: datetime
    guest_id: uuid.UUID | None = None
    external_pms_id: str | None = None
    external_channel_id: str | None = None
    status: ReservationStatus = ReservationStatus.PENDING
    check_in_time: time | None = None
    check_out_time: time | None = None
    adults: int = 1
    children: int = 0
    total_guests: int = 1
    gross_amount: Decimal | None = None
    ota_commission: Decimal | None = None
    net_amount: Decimal | None = None
    currency: str = "EUR"
    payment_status: PaymentStatus = PaymentStatus.PENDING
    access_status: ReservationAccessStatus = ReservationAccessStatus.PENDING
    legal_registration_status: LegalRegistrationStatus = LegalRegistrationStatus.NOT_REQUIRED
    cleaning_required: bool = True
    special_requests: str | None = None
    internal_notes: str | None = None

    def __post_init__(self) -> None:
        if self.check_out_date <= self.check_in_date:
            raise ValueError("check_out_date must be after check_in_date")
