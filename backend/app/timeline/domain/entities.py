import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity


@dataclass
class TimelineEvent:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    actor_type: TimelineActorType
    event_type: TimelineEventType
    title: str
    created_at: datetime
    reservation_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    severity: TimelineSeverity = TimelineSeverity.INFO
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
