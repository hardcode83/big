import uuid
from datetime import datetime, timezone

import pytest

from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
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


@pytest.mark.parametrize("actor_type", [TimelineActorType.SYSTEM, TimelineActorType.SCHEDULER, TimelineActorType.WEBHOOK])
def test_generic_factory_accepts_non_user_actor_without_user_id(actor_type):
    event = TimelineEventFactory.create(TimelineEventData(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(), actor_type=actor_type,
        event_type=TimelineEventType.INCIDENT_CREATED, title="Incident", created_at=datetime.now(timezone.utc),
    ))
    assert event.actor_type is actor_type


def test_generic_factory_rejects_invalid_common_fields():
    base = dict(id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(), actor_type=TimelineActorType.SYSTEM, event_type=TimelineEventType.INCIDENT_CREATED, title="Incident", created_at=datetime.now(timezone.utc))
    with pytest.raises(TimelineEventValidationError):
        TimelineEventFactory.create(TimelineEventData(**{**base, "title": "   "}))
    with pytest.raises(TimelineEventValidationError):
        TimelineEventFactory.create(TimelineEventData(**{**base, "actor_type": TimelineActorType.USER}))


def test_property_state_changed_reuses_existing_event_contract():
    transition = PropertyStateTransition(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(),
        from_state=PropertyOperationalState.VACANT_READY, to_state=PropertyOperationalState.BLOCKED_BY_OWNER,
        triggered_by=StateTransitionTriggeredBy.USER, triggered_by_user_id=uuid.uuid4(),
        reason="manual", created_at=datetime.now(timezone.utc), metadata={},
    )
    event_id = uuid.uuid4()
    event = TimelineEventFactory.property_state_changed(
        transition=transition, trigger="OWNER_BLOCKED", timeline_event_id=event_id, correlation_id="c1",
    )
    assert event.id == event_id
    assert event.event_type is TimelineEventType.PROPERTY_STATE_CHANGED
    assert event.severity is TimelineSeverity.INFO
    assert event.metadata == {"from_state": "VACANT_READY", "to_state": "BLOCKED_BY_OWNER", "trigger": "OWNER_BLOCKED", "correlation_id": "c1"}
