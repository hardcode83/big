import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.tenants.domain.enums import StorageType, TenantStatus


class TenantModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))
    billing_email: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(2), default="ES", server_default="ES")
    timezone: Mapped[str] = mapped_column(
        String(50), default="Europe/Madrid", server_default="Europe/Madrid"
    )
    default_language: Mapped[str] = mapped_column(String(5), default="es", server_default="es")
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status", native_enum=True),
        default=TenantStatus.ACTIVE,
        server_default=TenantStatus.ACTIVE.value,
    )


class TenantConfigModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenant_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), unique=True)
    owner_approval_threshold_eur: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("100.00"), server_default="100.00"
    )
    ai_confidence_threshold: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0.75"), server_default="0.75"
    )
    sla_critical_minutes: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    sla_high_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    sla_medium_minutes: Mapped[int] = mapped_column(Integer, default=240, server_default="240")
    sla_low_minutes: Mapped[int] = mapped_column(Integer, default=480, server_default="480")
    checkin_window_hours_before: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    checkout_ready_hours_after: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    auto_create_cleaning_task: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    cleaning_photo_required: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    storage_type: Mapped[StorageType] = mapped_column(
        Enum(StorageType, name="storage_type", native_enum=True),
        default=StorageType.LOCAL,
        server_default=StorageType.LOCAL.value,
    )
    notification_email_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    notification_whatsapp_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
