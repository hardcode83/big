import uuid
from datetime import datetime, timezone

from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity


def test_timeline_event_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    event = TimelineEvent(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        actor_type=TimelineActorType.SYSTEM,
        event_type=TimelineEventType.PROPERTY_STATE_CHANGED,
        title="Property state changed",
        created_at=now,
    )

    assert event.severity == TimelineSeverity.INFO
    assert event.metadata == {}
    assert event.reservation_id is None
    assert event.actor_user_id is None
