import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
)


class IncidentModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_property_id_status", "property_id", "status"),
        Index("ix_incidents_tenant_id_severity_status", "tenant_id", "severity", "status"),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("properties.id", ondelete="RESTRICT"))
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), default=None
    )
    reported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reported_by_guest_token: Mapped[str | None] = mapped_column(String(200), default=None)
    source: Mapped[IncidentSource] = mapped_column(Enum(IncidentSource, name="incident_source", native_enum=True))
    category: Mapped[IncidentCategory] = mapped_column(
        Enum(IncidentCategory, name="incident_category", native_enum=True),
        default=IncidentCategory.OTHER,
        server_default=IncidentCategory.OTHER.value,
    )
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity", native_enum=True),
        default=IncidentSeverity.MEDIUM,
        server_default=IncidentSeverity.MEDIUM.value,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status", native_enum=True),
        default=IncidentStatus.OPEN,
        server_default=IncidentStatus.OPEN.value,
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column()
    ai_summary: Mapped[str | None] = mapped_column(default=None)
    ai_classification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    assigned_technician_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    owner_approval_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    approved_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    final_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
