import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Time, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.properties.domain.enums import (
    PropertyOperationalState,
    PropertyStatus,
    StateTransitionTriggeredBy,
)

property_operational_state_enum = Enum(
    PropertyOperationalState, name="property_operational_state", native_enum=True
)


class PropertyModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("tenant_id", "internal_code", name="uq_properties_tenant_id_internal_code"),
        Index("ix_properties_tenant_id_current_operational_state", "tenant_id", "current_operational_state"),
        Index("ix_properties_tenant_id_pms_external_id", "tenant_id", "pms_external_id"),
    )

    name: Mapped[str] = mapped_column(String(200))
    internal_code: Mapped[str] = mapped_column(String(50))
    pms_external_id: Mapped[str | None] = mapped_column(String(200), default=None)
    address_line1: Mapped[str | None] = mapped_column(String(200), default=None)
    address_line2: Mapped[str | None] = mapped_column(String(200), default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None)
    province: Mapped[str | None] = mapped_column(String(100), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(20), default=None)
    country: Mapped[str] = mapped_column(String(2), default="ES", server_default="ES")
    timezone: Mapped[str] = mapped_column(
        String(50), default="Europe/Madrid", server_default="Europe/Madrid"
    )
    max_guests: Mapped[int] = mapped_column(default=2, server_default="2")
    bedrooms: Mapped[int] = mapped_column(default=1, server_default="1")
    bathrooms: Mapped[int] = mapped_column(default=1, server_default="1")
    current_operational_state: Mapped[PropertyOperationalState] = mapped_column(
        property_operational_state_enum,
        default=PropertyOperationalState.VACANT_READY,
        server_default=PropertyOperationalState.VACANT_READY.value,
    )
    default_check_in_time: Mapped[time] = mapped_column(
        Time, default=time(15, 0), server_default="15:00:00"
    )
    default_check_out_time: Mapped[time] = mapped_column(
        Time, default=time(11, 0), server_default="11:00:00"
    )
    wifi_name: Mapped[str | None] = mapped_column(String(200), default=None)
    wifi_password_encrypted: Mapped[str | None] = mapped_column(default=None)
    access_notes: Mapped[str | None] = mapped_column(default=None)
    cleaning_notes: Mapped[str | None] = mapped_column(default=None)
    emergency_notes: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[PropertyStatus] = mapped_column(
        Enum(PropertyStatus, name="property_status", native_enum=True),
        default=PropertyStatus.ACTIVE,
        server_default=PropertyStatus.ACTIVE.value,
    )


class PropertyStateTransitionModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "property_state_transitions"
    __table_args__ = (
        Index(
            "ix_property_state_transitions_property_id_created_at",
            "property_id",
            text("created_at DESC"),
        ),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    to_state: Mapped[PropertyOperationalState] = mapped_column(property_operational_state_enum)
    triggered_by: Mapped[StateTransitionTriggeredBy] = mapped_column(
        Enum(StateTransitionTriggeredBy, name="state_transition_triggered_by", native_enum=True)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    from_state: Mapped[PropertyOperationalState | None] = mapped_column(
        property_operational_state_enum, default=None
    )
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reason: Mapped[str | None] = mapped_column(String(500), default=None)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=None)
