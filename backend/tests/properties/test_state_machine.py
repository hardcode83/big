import copy
import uuid
from datetime import date, datetime, time, timezone

import pytest

from app.cleaning.domain.entities import CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import IncidentCategory, IncidentSeverity, IncidentSource, IncidentStatus
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.properties.domain.exceptions import (
    IncompatibleTransitionContextError,
    InvalidStateTransitionError,
    InvalidTransitionInputError,
    NoOperationalStateChangeError,
    PropertyDomainError,
    TransitionScopeMismatchError,
)
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.domain.value_objects import (
    PropertyStateChangeRequest,
    PropertyTransitionContext,
    TransitionActor,
    TransitionEvidenceIds,
)
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.timeline.domain.exceptions import TimelineEventValidationError


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_property(state=PropertyOperationalState.VACANT_READY, *, tenant_id=None, property_id=None, tz="UTC"):
    return Property(
        property_id or uuid.uuid4(), tenant_id or uuid.uuid4(), "Home", "H1", NOW, NOW,
        timezone=tz, current_operational_state=state,
    )


def make_reservation(prop, *, status=ReservationStatus.CONFIRMED, check_in=date(2026, 1, 1), check_out=date(2026, 1, 3), check_in_time=None, check_out_time=None, tenant_id=None, property_id=None):
    return Reservation(
        uuid.uuid4(), tenant_id or prop.tenant_id, property_id or prop.id, ReservationChannel.MANUAL,
        check_in, check_out, (check_out - check_in).days, NOW, NOW, status=status,
        check_in_time=check_in_time, check_out_time=check_out_time,
    )


def make_cleaning(prop, status=CleaningTaskStatus.ASSIGNED):
    return CleaningTask(uuid.uuid4(), prop.tenant_id, prop.id, uuid.uuid4(), NOW, NOW, status=status)


def make_incident(prop, severity=IncidentSeverity.HIGH, status=IncidentStatus.OPEN, *, tenant_id=None, property_id=None):
    return Incident(
        uuid.uuid4(), tenant_id or prop.tenant_id, property_id or prop.id, IncidentSource.SYSTEM,
        "Issue", "Description", NOW, NOW, category=IncidentCategory.OTHER,
        severity=severity, status=status,
    )


def make_request(prop, trigger, *, context=None, actor=None, requested_state=None, reason=None, source=None, reservation_id=None, instant=NOW, correlation_id=None):
    return PropertyStateChangeRequest(
        property=prop, trigger=trigger, context=context or PropertyTransitionContext(),
        actor=actor or TransitionActor(StateTransitionTriggeredBy.SYSTEM), reference_instant=instant,
        evidence_ids=TransitionEvidenceIds(uuid.uuid4(), uuid.uuid4()), requested_state=requested_state,
        reason=reason, source_entity_id=source, reservation_id=reservation_id, correlation_id=correlation_id,
    )


def test_property_state_trigger_catalog_is_closed() -> None:
    assert [member.value for member in PropertyStateTrigger] == [
        "CHECKIN_WINDOW_OPENED", "CHECKIN_TIME_REACHED", "CHECKOUT_TIME_REACHED",
        "RESERVATION_CANCELLED_BEFORE_CHECKIN", "CLEANER_ASSIGNED", "CLEANER_REJECTED",
        "CLEANING_ASSIGNMENT_EXPIRED", "CLEANING_STARTED", "CLEANING_COMPLETED",
        "INCIDENT_HIGH", "INCIDENT_CRITICAL", "INCIDENT_RESOLVED", "OWNER_BLOCKED",
        "PROPERTY_MARKED_OUT_OF_SERVICE", "PROPERTY_REACTIVATED", "OWNER_MANAGER_UNBLOCKED",
    ]
    with pytest.raises(ValueError):
        PropertyStateTrigger("DOOR_OPENED")


def valid_case(state, trigger):
    prop = make_property(state)
    context = PropertyTransitionContext()
    source = None
    reservation_id = None
    instant = NOW
    actor = TransitionActor(StateTransitionTriggeredBy.SYSTEM)
    reason = None
    requested = None
    if trigger in {PropertyStateTrigger.CHECKIN_WINDOW_OPENED, PropertyStateTrigger.CHECKIN_TIME_REACHED, PropertyStateTrigger.CHECKOUT_TIME_REACHED, PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN}:
        status = ReservationStatus.CANCELLED if trigger is PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN else ReservationStatus.CONFIRMED
        reservation = make_reservation(prop, status=status)
        source, reservation_id = reservation.id, reservation.id
        context = PropertyTransitionContext(reservations=(reservation,))
        instant = datetime(2026, 1, 1, 16, tzinfo=timezone.utc)
        if trigger is PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN:
            instant = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        if trigger is PropertyStateTrigger.CHECKOUT_TIME_REACHED:
            instant = datetime(2026, 1, 3, 12, tzinfo=timezone.utc)
        if trigger is PropertyStateTrigger.CHECKIN_TIME_REACHED and state is PropertyOperationalState.AWAITING_CHECKIN:
            instant = datetime(2026, 1, 1, 16, tzinfo=timezone.utc)
    elif trigger in {PropertyStateTrigger.CLEANER_ASSIGNED, PropertyStateTrigger.CLEANER_REJECTED, PropertyStateTrigger.CLEANING_ASSIGNMENT_EXPIRED, PropertyStateTrigger.CLEANING_STARTED, PropertyStateTrigger.CLEANING_COMPLETED}:
        status = {
            PropertyStateTrigger.CLEANER_ASSIGNED: CleaningTaskStatus.ASSIGNED,
            PropertyStateTrigger.CLEANER_REJECTED: CleaningTaskStatus.REJECTED,
            PropertyStateTrigger.CLEANING_ASSIGNMENT_EXPIRED: CleaningTaskStatus.ASSIGNED,
            PropertyStateTrigger.CLEANING_STARTED: CleaningTaskStatus.IN_PROGRESS,
            PropertyStateTrigger.CLEANING_COMPLETED: CleaningTaskStatus.COMPLETED,
        }[trigger]
        task = make_cleaning(prop, status)
        source = task.id
        context = PropertyTransitionContext(cleaning_tasks=(task,))
    elif trigger in {PropertyStateTrigger.INCIDENT_HIGH, PropertyStateTrigger.INCIDENT_CRITICAL, PropertyStateTrigger.INCIDENT_RESOLVED}:
        severity = IncidentSeverity.CRITICAL if trigger is PropertyStateTrigger.INCIDENT_CRITICAL else IncidentSeverity.HIGH
        status = IncidentStatus.RESOLVED if trigger is PropertyStateTrigger.INCIDENT_RESOLVED else IncidentStatus.OPEN
        incident = make_incident(prop, severity, status)
        source = incident.id
        context = PropertyTransitionContext(incidents=(incident,))
    elif trigger in {PropertyStateTrigger.OWNER_BLOCKED, PropertyStateTrigger.PROPERTY_MARKED_OUT_OF_SERVICE, PropertyStateTrigger.PROPERTY_REACTIVATED, PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED}:
        actor = TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4())
        reason = "approved manual action"
        if trigger is PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED:
            requested = PropertyOperationalState.VACANT_READY
    return make_request(prop, trigger, context=context, actor=actor, requested_state=requested, reason=reason, source=source, reservation_id=reservation_id, instant=instant)


@pytest.mark.parametrize("state,trigger", list(PropertyStateMachine._POLICY))
def test_every_declared_policy_arrow_is_evaluable(state, trigger) -> None:
    request = valid_case(state, trigger)
    result = PropertyStateMachine.evaluate(request)
    assert result.transition.from_state is state
    assert result.transition.to_state in PropertyStateMachine._POLICY[(state, trigger)]
    assert result.timeline_event.event_type.value == "PROPERTY_STATE_CHANGED"


@pytest.mark.parametrize("state", list(PropertyOperationalState))
@pytest.mark.parametrize("trigger", list(PropertyStateTrigger))
def test_every_undeclared_state_trigger_pair_is_rejected(state, trigger) -> None:
    if (state, trigger) in PropertyStateMachine._POLICY:
        pytest.skip("declared policy pair")
    with pytest.raises(PropertyDomainError):
        PropertyStateMachine.evaluate(valid_case(state, trigger))


def test_fixed_policy_configuration_requires_one_destination() -> None:
    key = (PropertyOperationalState.VACANT_READY, PropertyStateTrigger.OWNER_BLOCKED)
    original = PropertyStateMachine._POLICY[key]
    PropertyStateMachine._POLICY[key] = {PropertyOperationalState.BLOCKED_BY_OWNER, PropertyOperationalState.OUT_OF_SERVICE}
    try:
        with pytest.raises(InvalidStateTransitionError, match="exactly one"):
            PropertyStateMachine.evaluate(valid_case(*key))
    finally:
        PropertyStateMachine._POLICY[key] = original


def test_noop_and_requested_state_mismatch_are_rejected() -> None:
    actor = TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4())
    noop = make_request(make_property(PropertyOperationalState.BLOCKED_BY_OWNER), PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED, actor=actor, requested_state=PropertyOperationalState.BLOCKED_BY_OWNER, reason="manual")
    with pytest.raises(NoOperationalStateChangeError):
        PropertyStateMachine.evaluate(noop)
    mismatch = make_request(make_property(), PropertyStateTrigger.OWNER_BLOCKED, actor=actor, requested_state=PropertyOperationalState.VACANT_READY, reason="manual")
    with pytest.raises(InvalidStateTransitionError):
        PropertyStateMachine.evaluate(mismatch)


@pytest.mark.parametrize("trigger", [PropertyStateTrigger.OWNER_BLOCKED, PropertyStateTrigger.PROPERTY_MARKED_OUT_OF_SERVICE, PropertyStateTrigger.PROPERTY_REACTIVATED])
def test_manual_actions_require_user_and_reason(trigger) -> None:
    state = PropertyOperationalState.OUT_OF_SERVICE if trigger is PropertyStateTrigger.PROPERTY_REACTIVATED else PropertyOperationalState.VACANT_READY
    with pytest.raises(InvalidTransitionInputError):
        PropertyStateMachine.evaluate(make_request(make_property(state), trigger, reason=""))
    with pytest.raises(InvalidTransitionInputError):
        PropertyStateMachine.evaluate(make_request(make_property(state), trigger, actor=TransitionActor(StateTransitionTriggeredBy.USER), reason="x"))


def test_unblock_requires_actor_reason_and_explicit_destination() -> None:
    prop = make_property(PropertyOperationalState.BLOCKED_BY_OWNER)
    with pytest.raises(InvalidTransitionInputError):
        PropertyStateMachine.evaluate(make_request(prop, PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED, reason="x"))
    with pytest.raises(InvalidTransitionInputError):
        PropertyStateMachine.evaluate(make_request(prop, PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED, actor=TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4()), reason=""))


def test_context_scope_is_validated_for_tenant_and_property() -> None:
    prop = make_property()
    wrong_tenant = make_reservation(prop, tenant_id=uuid.uuid4())
    with pytest.raises(TransitionScopeMismatchError):
        PropertyStateMachine.evaluate(make_request(prop, PropertyStateTrigger.CHECKIN_WINDOW_OPENED, context=PropertyTransitionContext(reservations=(wrong_tenant,)), source=wrong_tenant.id, reservation_id=wrong_tenant.id))
    wrong_property = make_reservation(prop, property_id=uuid.uuid4())
    with pytest.raises(TransitionScopeMismatchError):
        PropertyStateMachine.evaluate(make_request(prop, PropertyStateTrigger.CHECKIN_WINDOW_OPENED, context=PropertyTransitionContext(reservations=(wrong_property,)), source=wrong_property.id, reservation_id=wrong_property.id))


@pytest.mark.parametrize("trigger,status", [
    (PropertyStateTrigger.CHECKIN_WINDOW_OPENED, ReservationStatus.CANCELLED),
    (PropertyStateTrigger.CHECKIN_TIME_REACHED, ReservationStatus.PENDING),
    (PropertyStateTrigger.CHECKOUT_TIME_REACHED, ReservationStatus.CANCELLED),
    (PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN, ReservationStatus.CONFIRMED),
])
def test_reservation_trigger_preconditions_reject_incompatible_statuses(trigger, status):
    state = {
        PropertyStateTrigger.CHECKIN_WINDOW_OPENED: PropertyOperationalState.VACANT_READY,
        PropertyStateTrigger.CHECKIN_TIME_REACHED: PropertyOperationalState.AWAITING_CHECKIN,
        PropertyStateTrigger.CHECKOUT_TIME_REACHED: PropertyOperationalState.OCCUPIED_ESTIMATED,
        PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN: PropertyOperationalState.AWAITING_CHECKIN,
    }[trigger]
    p = make_property(state)
    r = make_reservation(p, status=status)
    with pytest.raises(IncompatibleTransitionContextError):
        PropertyStateMachine.evaluate(make_request(p, trigger, context=PropertyTransitionContext(reservations=(r,)), source=r.id, reservation_id=r.id, instant=datetime(2026, 1, 1, 16, tzinfo=timezone.utc)))


@pytest.mark.parametrize("trigger,status", [
    (PropertyStateTrigger.CLEANER_ASSIGNED, CleaningTaskStatus.CREATED),
    (PropertyStateTrigger.CLEANER_REJECTED, CleaningTaskStatus.ASSIGNED),
    (PropertyStateTrigger.CLEANING_ASSIGNMENT_EXPIRED, CleaningTaskStatus.REJECTED),
    (PropertyStateTrigger.CLEANING_STARTED, CleaningTaskStatus.ASSIGNED),
    (PropertyStateTrigger.CLEANING_COMPLETED, CleaningTaskStatus.IN_PROGRESS),
])
def test_cleaning_trigger_preconditions_reject_incompatible_statuses(trigger, status):
    state = {
        PropertyStateTrigger.CLEANER_ASSIGNED: PropertyOperationalState.AWAITING_CLEANING,
        PropertyStateTrigger.CLEANER_REJECTED: PropertyOperationalState.CLEANING_SCHEDULED,
        PropertyStateTrigger.CLEANING_ASSIGNMENT_EXPIRED: PropertyOperationalState.CLEANING_SCHEDULED,
        PropertyStateTrigger.CLEANING_STARTED: PropertyOperationalState.CLEANING_SCHEDULED,
        PropertyStateTrigger.CLEANING_COMPLETED: PropertyOperationalState.CLEANING_IN_PROGRESS,
    }[trigger]
    p = make_property(state)
    task = make_cleaning(p, status)
    with pytest.raises(IncompatibleTransitionContextError):
        PropertyStateMachine.evaluate(make_request(p, trigger, context=PropertyTransitionContext(cleaning_tasks=(task,)), source=task.id))


@pytest.mark.parametrize("trigger,severity,status", [
    (PropertyStateTrigger.INCIDENT_HIGH, IncidentSeverity.CRITICAL, IncidentStatus.OPEN),
    (PropertyStateTrigger.INCIDENT_CRITICAL, IncidentSeverity.HIGH, IncidentStatus.OPEN),
    (PropertyStateTrigger.INCIDENT_HIGH, IncidentSeverity.HIGH, IncidentStatus.RESOLVED),
    (PropertyStateTrigger.INCIDENT_RESOLVED, IncidentSeverity.HIGH, IncidentStatus.OPEN),
])
def test_incident_trigger_preconditions_reject_incompatible_evidence(trigger, severity, status):
    state = {
        PropertyStateTrigger.INCIDENT_HIGH: PropertyOperationalState.VACANT_READY,
        PropertyStateTrigger.INCIDENT_CRITICAL: PropertyOperationalState.AWAITING_CHECKIN,
        PropertyStateTrigger.INCIDENT_RESOLVED: PropertyOperationalState.MAINTENANCE_REQUIRED,
    }[trigger]
    p = make_property(state)
    item = make_incident(p, severity, status)
    with pytest.raises(IncompatibleTransitionContextError):
        PropertyStateMachine.evaluate(make_request(p, trigger, context=PropertyTransitionContext(incidents=(item,)), source=item.id))


def test_missing_source_entity_is_rejected_for_triggered_workflows():
    p = make_property(PropertyOperationalState.VACANT_READY)
    with pytest.raises(IncompatibleTransitionContextError):
        PropertyStateMachine.evaluate(make_request(p, PropertyStateTrigger.INCIDENT_HIGH))


def test_input_entities_and_metadata_are_not_mutated() -> None:
    prop = make_property()
    request = make_request(prop, PropertyStateTrigger.OWNER_BLOCKED, actor=TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4()), reason="manual", correlation_id="c1")
    before = copy.deepcopy(request)
    PropertyStateMachine.evaluate(request)
    assert request == before
    assert prop.current_operational_state is PropertyOperationalState.VACANT_READY


def test_evidence_failure_is_atomic(monkeypatch) -> None:
    from app.timeline.domain.services import TimelineEventFactory
    prop = make_property()
    request = make_request(prop, PropertyStateTrigger.OWNER_BLOCKED, actor=TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4()), reason="manual")
    monkeypatch.setattr(TimelineEventFactory, "property_state_changed", lambda **_: (_ for _ in ()).throw(TimelineEventValidationError("invalid")))
    with pytest.raises(Exception) as exc_info:
        PropertyStateMachine.evaluate(request)
    assert exc_info.value.__class__.__name__ == "TransitionEvidenceError"
