import uuid
from datetime import datetime, timezone

from app.properties.domain.entities import Property
from app.properties.domain.enums import StateTransitionTriggeredBy
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.domain.value_objects import (
    PropertyStateChangeRequest,
    PropertyTransitionContext,
    TransitionActor,
    TransitionEvidenceIds,
)


def test_accepted_transition_returns_correlated_evidence() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    tenant_id, property_id = uuid.uuid4(), uuid.uuid4()
    prop = Property(property_id, tenant_id, "Home", "H1", now, now)
    transition_id, event_id = uuid.uuid4(), uuid.uuid4()
    request = PropertyStateChangeRequest(
        property=prop, trigger=PropertyStateTrigger.OWNER_BLOCKED,
        context=PropertyTransitionContext(),
        actor=TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4()),
        reference_instant=now, evidence_ids=TransitionEvidenceIds(transition_id, event_id),
        reason="Owner request", correlation_id="corr-1",
    )
    result = PropertyStateMachine.evaluate(request)
    assert result.transition.id == transition_id
    assert result.timeline_event.id == event_id
    assert result.timeline_event.event_type.value == "PROPERTY_STATE_CHANGED"
    assert result.transition.metadata["correlation_id"] == "corr-1"
    assert result.timeline_event.metadata["correlation_id"] == "corr-1"
