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
