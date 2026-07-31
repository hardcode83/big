import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)


@dataclass
class Incident:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    source: IncidentSource
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    reservation_id: uuid.UUID | None = None
    reported_by_user_id: uuid.UUID | None = None
    reported_by_guest_token: str | None = None
    category: IncidentCategory = IncidentCategory.OTHER
    severity: IncidentSeverity = IncidentSeverity.MEDIUM
    status: IncidentStatus = IncidentStatus.OPEN
    ai_summary: str | None = None
    ai_classification: dict[str, Any] | None = None
    assigned_technician_id: uuid.UUID | None = None
    owner_approval_required: bool = False
    estimated_cost: Decimal | None = None
    approved_cost: Decimal | None = None
    final_cost: Decimal | None = None
    resolved_at: datetime | None = None


@dataclass
class OwnerApproval:
    """No created_at/updated_at: §7.19 declares requested_at/responded_at only.

    Strict fidelity to the PRD, decided in the design gate (OQ1). It makes this the
    only editable table in the schema without `updated_at` — an automatic expiry
    leaves no timestamp — so `maintenance` adds one if its approval flow needs it.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    related_type: OwnerApprovalRelatedType
    related_id: uuid.UUID
    amount: Decimal
    reason: str
    requested_at: datetime
    status: OwnerApprovalStatus = OwnerApprovalStatus.PENDING
    responded_at: datetime | None = None
    responded_by: uuid.UUID | None = None
    response_notes: str | None = None
