import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.tenants.domain.enums import StorageType, TenantStatus


class TenantModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    # `platform-admin-api` (R-2, D2 enmendada): `tenants.name` is the only natural handle
    # on the row the API exposes before its id is known, and the document search of D6 is
    # keyed on the same column. The constraint is declared HERE, with the same name the
    # migration `936fef5a01b1_tenants_name_unique.py` uses, and not as `unique=True`:
    # `unique=True` lets the backend pick the name (Postgres derives `tenants_name_key`),
    # which made the two schema paths disagree — the test database is built from this
    # metadata via `create_all`, the deployed one by the migration — and forced the
    # repository's `IntegrityError` translation to match a set of two spellings. One
    # explicit name means both paths produce the same constraint and the translation has
    # a single thing to look for.
    __table_args__ = (UniqueConstraint("name", name="uq_tenants_name"),)

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
    # `revenue-reviews` R5.5: bound on the per-property recurring-issues summary. The
    # `CHECK (review_recurring_issues_top_n BETWEEN 1 AND 50)` lives in
    # `r3v1ew5a02_revenue_reviews_tenant_config.py`; this model declares only the
    # column and its server default.
    review_recurring_issues_top_n: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5"
    )
