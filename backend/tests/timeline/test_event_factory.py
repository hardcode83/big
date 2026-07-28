import uuid
from datetime import datetime, timezone

import pytest

from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData
from app.timeline.domain.exceptions import TimelineEventValidationError


def test_generic_factory_copies_metadata_and_rejects_naive_time() -> None:
    metadata = {"key": "value"}
    data = TimelineEventData(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(),
        actor_type=TimelineActorType.SYSTEM, event_type=TimelineEventType.INCIDENT_CREATED,
        title="Incident created", created_at=datetime.now(timezone.utc), metadata=metadata,
    )
    event = TimelineEventFactory.create(data)
    metadata["key"] = "changed"
    assert event.metadata == {"key": "value"}
    with pytest.raises(TimelineEventValidationError):
        TimelineEventFactory.create(data.__class__(**{**data.__dict__, "created_at": datetime.now()}))


def test_generic_factory_supports_existing_non_property_event() -> None:
    event = TimelineEventFactory.create(TimelineEventData(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(),
        actor_type=TimelineActorType.SYSTEM, event_type=TimelineEventType.CLEANING_STARTED,
        title="Cleaning started", created_at=datetime.now(timezone.utc), severity=TimelineSeverity.INFO,
    ))
    assert event.event_type is TimelineEventType.CLEANING_STARTED
