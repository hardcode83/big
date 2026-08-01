import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
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


class OwnerApprovalModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """No TimestampMixin: §7.19 declares requested_at/responded_at and nothing else.

    Strict PRD fidelity, decided in the design gate (OQ1). The trade-off is recorded:
    `status` mutates (PENDING → APPROVED/REJECTED/EXPIRED), so this is the only
    editable table in the schema without `updated_at`, and an expiry driven by a job
    leaves `responded_at` NULL with no trace of when it happened. `maintenance` adds
    the column if its approval flow needs it — the table is empty until then.
    """

    __tablename__ = "owner_approvals"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    related_type: Mapped[OwnerApprovalRelatedType] = mapped_column(
        Enum(OwnerApprovalRelatedType, name="owner_approval_related_type", native_enum=True)
    )
    # Polymorphic pair (§7.19): related_id points at a different table depending on
    # related_type, so it deliberately carries no ForeignKey. Not an oversight.
    related_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reason: Mapped[str] = mapped_column()
    status: Mapped[OwnerApprovalStatus] = mapped_column(
        Enum(OwnerApprovalStatus, name="owner_approval_status", native_enum=True),
        default=OwnerApprovalStatus.PENDING,
        server_default=OwnerApprovalStatus.PENDING.value,
    )
    # `requested_at` IS this row's creation timestamp — §7.19 declares no created_at
    # precisely because this column plays that role — so it gets the same
    # server_default every creation timestamp in the schema gets. The PRD declares
    # `created_at TIMESTAMPTZ NOT NULL` with no DEFAULT in all 23 tables of §7 and
    # `TimestampMixin` defaults them all; singling this one out would be the
    # inconsistency, not the fidelity (design D5, panel section 2).
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    responded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    response_notes: Mapped[str | None] = mapped_column(default=None)
