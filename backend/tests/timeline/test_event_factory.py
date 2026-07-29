import uuid
from datetime import datetime, timezone

import pytest

from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.properties.domain.transition_enums import PropertyStateTrigger
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


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "not-a-uuid"),
        ("tenant_id", "not-a-uuid"),
        ("property_id", None),
        ("actor_type", "SYSTEM"),
        ("event_type", "INCIDENT_CREATED"),
        ("severity", "INFO"),
        ("title", None),
        ("created_at", "2026-01-01T12:00:00Z"),
        ("reservation_id", "not-a-uuid"),
        ("actor_user_id", "not-a-uuid"),
        ("description", 123),
        ("metadata", None),
    ],
)
def test_generic_factory_rejects_structurally_invalid_data(field, value):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        actor_type=TimelineActorType.SYSTEM,
        event_type=TimelineEventType.INCIDENT_CREATED,
        title="Incident",
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(TimelineEventValidationError):
        TimelineEventFactory.create(TimelineEventData(**{**base, field: value}))


def test_generic_factory_rejects_wrong_payload_and_actor_id_combinations():
    with pytest.raises(TimelineEventValidationError):
        TimelineEventFactory.create(object())
    base = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        actor_type=TimelineActorType.SYSTEM,
        event_type=TimelineEventType.INCIDENT_CREATED,
        title="Incident",
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(TimelineEventValidationError):
        TimelineEventFactory.create(
            TimelineEventData(**base, actor_user_id=uuid.uuid4())
        )


def make_transition(triggered_by=StateTransitionTriggeredBy.USER):
    user_id = uuid.uuid4() if triggered_by is StateTransitionTriggeredBy.USER else None
    return PropertyStateTransition(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(),
        from_state=PropertyOperationalState.VACANT_READY, to_state=PropertyOperationalState.BLOCKED_BY_OWNER,
        triggered_by=triggered_by, triggered_by_user_id=user_id,
        reason="manual", created_at=datetime.now(timezone.utc), metadata={},
    )


def test_property_state_changed_reuses_existing_event_contract():
    transition = make_transition()
    event_id = uuid.uuid4()
    event = TimelineEventFactory.property_state_changed(
        transition=transition, trigger=PropertyStateTrigger.OWNER_BLOCKED, timeline_event_id=event_id, correlation_id="c1",
    )
    assert event.id == event_id
    assert event.event_type is TimelineEventType.PROPERTY_STATE_CHANGED
    assert event.severity is TimelineSeverity.INFO
    assert event.metadata == {"from_state": "VACANT_READY", "to_state": "BLOCKED_BY_OWNER", "trigger": "OWNER_BLOCKED", "correlation_id": "c1"}


@pytest.mark.parametrize(
    "triggered_by,expected",
    [
        (StateTransitionTriggeredBy.SYSTEM, TimelineActorType.SYSTEM),
        (StateTransitionTriggeredBy.USER, TimelineActorType.USER),
        (StateTransitionTriggeredBy.SCHEDULER, TimelineActorType.SCHEDULER),
        (StateTransitionTriggeredBy.WEBHOOK, TimelineActorType.WEBHOOK),
    ],
)
def test_property_state_changed_maps_every_domain_actor(triggered_by, expected):
    event = TimelineEventFactory.property_state_changed(
        transition=make_transition(triggered_by),
        trigger=PropertyStateTrigger.OWNER_BLOCKED,
        timeline_event_id=uuid.uuid4(),
    )
    assert event.actor_type is expected


@pytest.mark.parametrize(
    "mutation",
    [
        lambda transition: setattr(transition, "triggered_by", "INVALID"),
        lambda transition: setattr(transition, "to_state", "INVALID"),
        lambda transition: setattr(transition, "from_state", "INVALID"),
        lambda transition: setattr(transition, "tenant_id", "INVALID"),
        lambda transition: setattr(transition, "metadata", None),
    ],
)
def test_property_state_changed_wraps_invalid_transition_data(mutation):
    transition = make_transition()
    mutation(transition)
    with pytest.raises(TimelineEventValidationError):
        TimelineEventFactory.property_state_changed(
            transition=transition,
            trigger=PropertyStateTrigger.OWNER_BLOCKED,
            timeline_event_id=uuid.uuid4(),
        )


def test_property_state_changed_rejects_invalid_trigger_without_key_or_value_errors():
    with pytest.raises(TimelineEventValidationError):
        TimelineEventFactory.property_state_changed(
            transition=make_transition(),
            trigger="OWNER_BLOCKED",
            timeline_event_id=uuid.uuid4(),
        )
