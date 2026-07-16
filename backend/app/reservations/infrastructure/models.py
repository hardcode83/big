import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, Numeric, String, Time, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.guests.domain.enums import LegalRegistrationStatus
from app.guests.infrastructure.models import legal_registration_status_enum
from app.reservations.domain.enums import (
    PaymentStatus,
    ReservationAccessStatus,
    ReservationChannel,
    ReservationStatus,
)


class ReservationModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_pms_id", name="uq_reservations_tenant_id_external_pms_id"),
        Index("ix_reservations_property_id_check_in_date", "property_id", "check_in_date"),
        Index("ix_reservations_property_id_check_out_date", "property_id", "check_out_date"),
        Index("ix_reservations_tenant_id_status", "tenant_id", "status"),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("guests.id", ondelete="RESTRICT"), default=None
    )
    external_pms_id: Mapped[str | None] = mapped_column(String(200), default=None)
    external_channel_id: Mapped[str | None] = mapped_column(String(200), default=None)
    channel: Mapped[ReservationChannel] = mapped_column(
        Enum(ReservationChannel, name="reservation_channel", native_enum=True)
    )
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="reservation_status", native_enum=True),
        default=ReservationStatus.PENDING,
        server_default=ReservationStatus.PENDING.value,
    )
    check_in_date: Mapped[date] = mapped_column(Date)
    check_out_date: Mapped[date] = mapped_column(Date)
    check_in_time: Mapped[time | None] = mapped_column(Time, default=None)
    check_out_time: Mapped[time | None] = mapped_column(Time, default=None)
    nights: Mapped[int] = mapped_column(Integer)
    adults: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    children: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_guests: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    ota_commission: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status", native_enum=True),
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
    )
    access_status: Mapped[ReservationAccessStatus] = mapped_column(
        Enum(ReservationAccessStatus, name="access_status", native_enum=True),
        default=ReservationAccessStatus.PENDING,
        server_default=ReservationAccessStatus.PENDING.value,
    )
    legal_registration_status: Mapped[LegalRegistrationStatus] = mapped_column(
        legal_registration_status_enum,
        default=LegalRegistrationStatus.NOT_REQUIRED,
        server_default=LegalRegistrationStatus.NOT_REQUIRED.value,
    )
    cleaning_required: Mapped[bool] = mapped_column(default=True, server_default="true")
    special_requests: Mapped[str | None] = mapped_column(default=None)
    internal_notes: Mapped[str | None] = mapped_column(default=None)
