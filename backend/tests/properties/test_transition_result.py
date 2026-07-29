import copy
import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.properties.domain.exceptions import InvalidTransitionInputError, TransitionEvidenceError
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.domain.value_objects import (
    PropertyStateChangeRequest, PropertyStateChangeResult, PropertyTransitionContext,
    TransitionActor, TransitionEvidenceIds,
)
from app.timeline.domain.exceptions import TimelineEventValidationError


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def request(*, state=PropertyOperationalState.VACANT_READY, actor=None, correlation="corr-1", instant=NOW, ids=None, requested=None, reason="Owner request"):
    p = Property(uuid.uuid4(), uuid.uuid4(), "Home", "H1", NOW, NOW, current_operational_state=state)
    return PropertyStateChangeRequest(
        property=p, trigger=PropertyStateTrigger.OWNER_BLOCKED if state is not PropertyOperationalState.BLOCKED_BY_OWNER else PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED,
        context=PropertyTransitionContext(), actor=actor or TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4()),
        reference_instant=instant, evidence_ids=ids or TransitionEvidenceIds(uuid.uuid4(), uuid.uuid4()),
        requested_state=requested, reason=reason, correlation_id=correlation,
    )


def test_value_objects_are_frozen_and_evidence_ids_are_distinct():
    req = request()
    with pytest.raises(FrozenInstanceError):
        req.reason = "changed"
    with pytest.raises(InvalidTransitionInputError):
        TransitionEvidenceIds("not-a-uuid", uuid.UUID(int=0))
    same = uuid.uuid4()
    with pytest.raises(InvalidTransitionInputError):
        TransitionEvidenceIds(same, same)


@pytest.mark.parametrize("instant", [datetime(2026, 1, 1, 12), datetime(2026, 1, 1, 12, tzinfo=timezone.utc)])
def test_reference_instant_validation(instant):
    if instant.tzinfo is None:
        with pytest.raises(InvalidTransitionInputError):
            request(instant=instant)
    else:
        assert request(instant=instant).reference_instant == instant


@pytest.mark.parametrize("correlation", ["", "   "])
def test_correlation_id_must_be_non_empty(correlation):
    with pytest.raises(InvalidTransitionInputError):
        request(correlation=correlation)


def test_actor_user_id_consistency_is_enforced():
    from app.properties.domain.value_objects import TransitionActor
    with pytest.raises(InvalidTransitionInputError):
        TransitionActor(StateTransitionTriggeredBy.USER)
    with pytest.raises(InvalidTransitionInputError):
        TransitionActor(StateTransitionTriggeredBy.SYSTEM, uuid.uuid4())


def test_accepted_transition_returns_correlated_evidence():
    transition_id, event_id = uuid.uuid4(), uuid.uuid4()
    req = request(ids=TransitionEvidenceIds(transition_id, event_id), correlation="corr-1")
    result = PropertyStateMachine.evaluate(req)
    assert isinstance(result, PropertyStateChangeResult)
    assert result.transition.id == transition_id
    assert result.timeline_event.id == event_id
    assert result.transition.tenant_id == result.timeline_event.tenant_id == req.property.tenant_id
    assert result.transition.property_id == result.timeline_event.property_id == req.property.id
    assert result.transition.from_state is PropertyOperationalState.VACANT_READY
    assert result.transition.to_state.value == result.timeline_event.metadata["to_state"]
    assert result.transition.triggered_by is StateTransitionTriggeredBy.USER
    assert result.timeline_event.actor_user_id == result.transition.triggered_by_user_id
    assert result.transition.reason == result.timeline_event.description == "Owner request"
    assert result.transition.created_at == result.timeline_event.created_at == NOW
    assert result.transition.metadata["correlation_id"] == result.timeline_event.metadata["correlation_id"] == "corr-1"


def test_identical_complete_requests_produce_identical_logical_results():
    p_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    actor_id, transition_id, event_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    prop = Property(p_id, tenant_id, "Home", "H1", NOW, NOW)
    def build():
        return PropertyStateChangeRequest(
            property=prop, trigger=PropertyStateTrigger.OWNER_BLOCKED, context=PropertyTransitionContext(),
            actor=TransitionActor(StateTransitionTriggeredBy.USER, actor_id), reference_instant=NOW,
            evidence_ids=TransitionEvidenceIds(transition_id, event_id), reason="same", correlation_id="same",
        )
    first, second = PropertyStateMachine.evaluate(build()), PropertyStateMachine.evaluate(build())
    assert first == second


def test_changed_input_changes_result_and_does_not_mutate_input():
    req = request()
    snapshot = copy.deepcopy(req)
    result = PropertyStateMachine.evaluate(req)
    assert req == snapshot
    assert result.transition.to_state is PropertyOperationalState.BLOCKED_BY_OWNER
    assert req.property.current_operational_state is PropertyOperationalState.VACANT_READY


def test_invalid_evidence_construction_returns_no_partial_result(monkeypatch):
    from app.timeline.domain.services import TimelineEventFactory
    monkeypatch.setattr(TimelineEventFactory, "property_state_changed", lambda **_: (_ for _ in ()).throw(TimelineEventValidationError("invalid timeline")))
    with pytest.raises(TransitionEvidenceError):
        PropertyStateMachine.evaluate(request())
