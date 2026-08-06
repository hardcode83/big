import uuid
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from app.integrations.domain.enums import PMSProvider
from app.properties.domain.enums import (
    PropertyOperationalState,
    PropertyStatus,
    StateTransitionTriggeredBy,
)


@dataclass
class Property:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    internal_code: str
    created_at: datetime
    updated_at: datetime
    pms_external_id: str | None = None
    pms_provider: PMSProvider | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str = "ES"
    timezone: str = "Europe/Madrid"
    max_guests: int = 2
    bedrooms: int = 1
    bathrooms: int = 1
    current_operational_state: PropertyOperationalState = PropertyOperationalState.VACANT_READY
    default_check_in_time: time = time(15, 0)
    default_check_out_time: time = time(11, 0)
    wifi_name: str | None = None
    wifi_password_encrypted: str | None = None
    access_notes: str | None = None
    cleaning_notes: str | None = None
    emergency_notes: str | None = None
    status: PropertyStatus = PropertyStatus.ACTIVE


@dataclass
class PropertyStateTransition:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    to_state: PropertyOperationalState
    triggered_by: StateTransitionTriggeredBy
    created_at: datetime
    from_state: PropertyOperationalState | None = None
    triggered_by_user_id: uuid.UUID | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
