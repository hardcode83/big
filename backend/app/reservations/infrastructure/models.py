import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Time, UniqueConstraint, Uuid
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
        # Redundant as a *constraint* — `id` is already the primary key, so `(tenant_id, id)`
        # is trivially unique — and load-bearing as an FK **target**: PostgreSQL only lets a
        # composite foreign key point at a declared unique key. `guest_access_tokens`
        # (`guest-portal-api` D2) references `(tenant_id, reservation_id)` through it, which
        # is what makes "the token's tenant and its reservation's tenant agree" impossible to
        # violate rather than something each writer must remember.
        #
        # That mattered enough to add an index here because the guest portal authorises on a
        # session that is deliberately **not** yet marked with a tenant — the token row is what
        # resolves it — so the global filter of `app/core/db.py` is off at exactly the moment
        # a mismatched pair would be read. Both the security and the tenancy panel of that
        # change's section 1 demonstrated the bad row being accepted before this existed.
        UniqueConstraint("tenant_id", "id", name="uq_reservations_tenant_id_id"),
        # `guest_id` reaches `guests` through a **composite** key on `(tenant_id, guest_id)`
        # so a stay cannot be linked to a guest of another tenant (`guest-portal-api` R4.2,
        # R2.5). `guest_id` is nullable and the default MATCH SIMPLE semantics mean the
        # constraint simply does not apply when it is NULL — which is the wanted behaviour,
        # since a booking with no guest is legal (OQ3's premise).
        #
        # Added because that change gave the column its first writer driven from an anonymous
        # surface (`LegalRegistrationStayStore.set_guest`), and its section 3 panel had three
        # reviewers independently reproduce a cross-tenant link. `ON DELETE RESTRICT` matches
        # the single-column FK it replaces.
        #
        # **`property_id` deliberately keeps its plain FK**, and that asymmetry is a scope
        # decision rather than an oversight: this change writes `guest_id` and does not write
        # `property_id`, whose writers are the reservations CRUD and the PMS sync. The portal's
        # own exposure to it is closed explicitly in
        # `app/guests/infrastructure/portal_repositories.py`, which filters
        # `properties.tenant_id` in the join rather than trusting the FK.
        ForeignKeyConstraint(
            ["tenant_id", "guest_id"],
            ["guests.tenant_id", "guests.id"],
            ondelete="RESTRICT",
            name="fk_reservations_guest_within_tenant",
        ),
        Index("ix_reservations_property_id_check_in_date", "property_id", "check_in_date"),
        Index("ix_reservations_property_id_check_out_date", "property_id", "check_out_date"),
        Index("ix_reservations_tenant_id_status", "tenant_id", "status"),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    guest_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, default=None)
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
