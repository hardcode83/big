import copy
import uuid
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.properties.domain.exceptions import (
    InvalidTransitionInputError,
    PropertyDomainError,
    TransitionEvidenceError,
)
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.domain.value_objects import (
    PropertyStateChangeRequest, PropertyStateChangeResult, PropertyTransitionContext,
    TransitionActor, TransitionEvidenceIds,
)
from app.timeline.domain.exceptions import TimelineEventValidationError
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus


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
    with pytest.raises(InvalidTransitionInputError):
        TransitionActor(StateTransitionTriggeredBy.USER, "not-a-uuid")


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference_instant", "2026-01-01T12:00:00Z"),
        ("reason", 123),
        ("source_entity_id", "not-a-uuid"),
        ("reservation_id", "not-a-uuid"),
        ("correlation_id", 123),
    ],
)
def test_request_rejects_invalid_runtime_types_with_domain_error(field, value):
    kwargs = {
        "property": Property(uuid.uuid4(), uuid.uuid4(), "Home", "H1", NOW, NOW),
        "trigger": PropertyStateTrigger.OWNER_BLOCKED,
        "context": PropertyTransitionContext(),
        "actor": TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4()),
        "reference_instant": NOW,
        "evidence_ids": TransitionEvidenceIds(uuid.uuid4(), uuid.uuid4()),
        "reason": "valid",
    }
    kwargs[field] = value
    with pytest.raises(InvalidTransitionInputError):
        PropertyStateChangeRequest(**kwargs)


@pytest.mark.parametrize("field", ["id", "tenant_id"])
def test_request_rejects_invalid_property_scope_ids(field):
    prop = Property(uuid.uuid4(), uuid.uuid4(), "Home", "H1", NOW, NOW)
    setattr(prop, field, "not-a-uuid")
    with pytest.raises(InvalidTransitionInputError):
        PropertyStateChangeRequest(
            property=prop,
            trigger=PropertyStateTrigger.OWNER_BLOCKED,
            context=PropertyTransitionContext(),
            actor=TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4()),
            reference_instant=NOW,
            evidence_ids=TransitionEvidenceIds(uuid.uuid4(), uuid.uuid4()),
            reason="valid",
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reservations": []},
        {"cleaning_tasks": (object(),)},
        {"incidents": ("invalid",)},
    ],
)
def test_context_rejects_invalid_collection_shapes(kwargs):
    with pytest.raises(InvalidTransitionInputError):
        PropertyTransitionContext(**kwargs)


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


def deterministic_request(
    *,
    state=PropertyOperationalState.BLOCKED_BY_OWNER,
    context=None,
    actor_id=None,
    instant=NOW,
    requested=PropertyOperationalState.VACANT_READY,
):
    property_id, tenant_id = uuid.UUID(int=1), uuid.UUID(int=2)
    prop = Property(property_id, tenant_id, "Home", "H1", NOW, NOW, current_operational_state=state)
    return PropertyStateChangeRequest(
        property=prop,
        trigger=PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED,
        context=context or PropertyTransitionContext(),
        actor=TransitionActor(StateTransitionTriggeredBy.USER, actor_id or uuid.UUID(int=3)),
        reference_instant=instant,
        evidence_ids=TransitionEvidenceIds(uuid.UUID(int=4), uuid.UUID(int=5)),
        requested_state=requested,
        reason="same",
        correlation_id="same",
    )


def test_changing_state_changes_or_rejects_the_logical_result():
    baseline = PropertyStateMachine.evaluate(deterministic_request())
    changed = deterministic_request(state=PropertyOperationalState.VACANT_READY)
    with pytest.raises(PropertyDomainError):
        PropertyStateMachine.evaluate(changed)
    assert baseline.transition.from_state is PropertyOperationalState.BLOCKED_BY_OWNER


def test_changing_context_changes_the_logical_result_without_mutation():
    baseline_request = deterministic_request()
    baseline_snapshot = copy.deepcopy(baseline_request)
    baseline = PropertyStateMachine.evaluate(baseline_request)
    prop = baseline_request.property
    reservation = Reservation(
        uuid.UUID(int=6),
        prop.tenant_id,
        prop.id,
        ReservationChannel.MANUAL,
        date(2026, 1, 1),
        date(2026, 1, 2),
        1,
        NOW,
        NOW,
        status=ReservationStatus.CONFIRMED,
    )
    changed_request = deterministic_request(
        context=PropertyTransitionContext(reservations=(reservation,)),
        requested=PropertyOperationalState.AWAITING_CHECKIN,
    )
    changed_snapshot = copy.deepcopy(changed_request)
    changed = PropertyStateMachine.evaluate(changed_request)
    assert baseline.transition.to_state is PropertyOperationalState.VACANT_READY
    assert changed.transition.to_state is PropertyOperationalState.AWAITING_CHECKIN
    assert baseline_request == baseline_snapshot
    assert changed_request == changed_snapshot


def test_changing_actor_changes_the_correlated_result():
    baseline = PropertyStateMachine.evaluate(deterministic_request(actor_id=uuid.UUID(int=3)))
    changed = PropertyStateMachine.evaluate(deterministic_request(actor_id=uuid.UUID(int=7)))
    assert baseline != changed
    assert baseline.transition.triggered_by_user_id != changed.transition.triggered_by_user_id
    assert baseline.timeline_event.actor_user_id != changed.timeline_event.actor_user_id


def test_changing_instant_changes_the_correlated_result():
    baseline = PropertyStateMachine.evaluate(deterministic_request(instant=NOW))
    changed_instant = datetime(2026, 1, 1, 13, tzinfo=timezone.utc)
    changed = PropertyStateMachine.evaluate(deterministic_request(instant=changed_instant))
    assert baseline != changed
    assert baseline.transition.created_at != changed.transition.created_at
    assert baseline.timeline_event.created_at != changed.timeline_event.created_at


def test_invalid_evidence_construction_returns_no_partial_result(monkeypatch):
    from app.timeline.domain.services import TimelineEventFactory
    monkeypatch.setattr(TimelineEventFactory, "property_state_changed", lambda **_: (_ for _ in ()).throw(TimelineEventValidationError("invalid timeline")))
    with pytest.raises(TransitionEvidenceError):
        PropertyStateMachine.evaluate(request())
