import copy
import uuid
from dataclasses import replace
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
from app.properties.domain.state_resolution import ContextualStateResolver
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


def context_for_destination(prop, destination):
    if destination is PropertyOperationalState.CRITICAL_INCIDENT:
        return PropertyTransitionContext(incidents=(make_incident(prop, IncidentSeverity.CRITICAL),)), NOW
    if destination is PropertyOperationalState.MAINTENANCE_REQUIRED:
        return PropertyTransitionContext(incidents=(make_incident(prop, IncidentSeverity.HIGH),)), NOW
    if destination is PropertyOperationalState.CLEANING_IN_PROGRESS:
        return PropertyTransitionContext(cleaning_tasks=(make_cleaning(prop, CleaningTaskStatus.IN_PROGRESS),)), NOW
    if destination is PropertyOperationalState.AWAITING_CLEANING:
        return PropertyTransitionContext(cleaning_tasks=(make_cleaning(prop, CleaningTaskStatus.CREATED),)), NOW
    if destination is PropertyOperationalState.CLEANING_SCHEDULED:
        return PropertyTransitionContext(cleaning_tasks=(make_cleaning(prop, CleaningTaskStatus.ASSIGNED),)), NOW
    if destination is PropertyOperationalState.OCCUPIED_ESTIMATED:
        return PropertyTransitionContext(reservations=(make_reservation(prop),)), datetime(2026, 1, 1, 16, tzinfo=timezone.utc)
    if destination is PropertyOperationalState.AWAITING_CHECKIN:
        return PropertyTransitionContext(reservations=(make_reservation(prop),)), NOW
    if destination is PropertyOperationalState.READY_FOR_NEXT_GUEST:
        return PropertyTransitionContext(
            reservations=(make_reservation(prop, check_in=date(2026, 1, 2), check_out=date(2026, 1, 3)),)
        ), NOW
    return PropertyTransitionContext(), NOW


def valid_case(state, trigger, destination=None):
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
        if trigger is PropertyStateTrigger.CLEANING_COMPLETED and destination is not None:
            destination_context, instant = context_for_destination(prop, destination)
            context = PropertyTransitionContext(
                reservations=destination_context.reservations,
                cleaning_tasks=(task,),
            )
    elif trigger in {PropertyStateTrigger.INCIDENT_HIGH, PropertyStateTrigger.INCIDENT_CRITICAL, PropertyStateTrigger.INCIDENT_RESOLVED}:
        severity = IncidentSeverity.CRITICAL if trigger is PropertyStateTrigger.INCIDENT_CRITICAL else IncidentSeverity.HIGH
        status = IncidentStatus.RESOLVED if trigger is PropertyStateTrigger.INCIDENT_RESOLVED else IncidentStatus.OPEN
        incident = make_incident(prop, severity, status)
        source = incident.id
        context = PropertyTransitionContext(incidents=(incident,))
        if trigger is PropertyStateTrigger.INCIDENT_RESOLVED and destination is not None:
            destination_context, instant = context_for_destination(prop, destination)
            context = PropertyTransitionContext(
                reservations=destination_context.reservations,
                cleaning_tasks=destination_context.cleaning_tasks,
                incidents=(incident, *destination_context.incidents),
            )
    elif trigger in {PropertyStateTrigger.OWNER_BLOCKED, PropertyStateTrigger.PROPERTY_MARKED_OUT_OF_SERVICE, PropertyStateTrigger.PROPERTY_REACTIVATED, PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED}:
        actor = TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4())
        reason = "approved manual action"
        if trigger is PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED:
            requested = destination or PropertyOperationalState.VACANT_READY
            if requested in (
                *ContextualStateResolver.CONTEXTUAL_STATES,
                PropertyOperationalState.CLEANING_SCHEDULED,
            ):
                context, instant = context_for_destination(prop, requested)
    return make_request(prop, trigger, context=context, actor=actor, requested_state=requested, reason=reason, source=source, reservation_id=reservation_id, instant=instant)


S = PropertyOperationalState
T = PropertyStateTrigger
EXPECTED_POLICY = {
    (S.VACANT_READY, T.CHECKIN_WINDOW_OPENED): {S.AWAITING_CHECKIN},
    (S.VACANT_READY, T.OWNER_BLOCKED): {S.BLOCKED_BY_OWNER},
    (S.VACANT_READY, T.PROPERTY_MARKED_OUT_OF_SERVICE): {S.OUT_OF_SERVICE},
    (S.VACANT_READY, T.INCIDENT_HIGH): {S.MAINTENANCE_REQUIRED},
    (S.AWAITING_CHECKIN, T.CHECKIN_TIME_REACHED): {S.OCCUPIED_ESTIMATED},
    (S.AWAITING_CHECKIN, T.INCIDENT_HIGH): {S.MAINTENANCE_REQUIRED},
    (S.AWAITING_CHECKIN, T.INCIDENT_CRITICAL): {S.CRITICAL_INCIDENT},
    (S.AWAITING_CHECKIN, T.OWNER_BLOCKED): {S.BLOCKED_BY_OWNER},
    (S.AWAITING_CHECKIN, T.RESERVATION_CANCELLED_BEFORE_CHECKIN): {S.VACANT_READY},
    (S.OCCUPIED_ESTIMATED, T.CHECKOUT_TIME_REACHED): {S.AWAITING_CLEANING},
    (S.OCCUPIED_ESTIMATED, T.INCIDENT_CRITICAL): {S.CRITICAL_INCIDENT},
    (S.OCCUPIED_ESTIMATED, T.INCIDENT_HIGH): {S.MAINTENANCE_REQUIRED},
    (S.AWAITING_CLEANING, T.CLEANER_ASSIGNED): {S.CLEANING_SCHEDULED},
    (S.AWAITING_CLEANING, T.INCIDENT_CRITICAL): {S.CRITICAL_INCIDENT},
    (S.AWAITING_CLEANING, T.INCIDENT_HIGH): {S.MAINTENANCE_REQUIRED},
    (S.AWAITING_CLEANING, T.OWNER_BLOCKED): {S.BLOCKED_BY_OWNER},
    (S.CLEANING_SCHEDULED, T.CLEANING_STARTED): {S.CLEANING_IN_PROGRESS},
    (S.CLEANING_SCHEDULED, T.CLEANER_REJECTED): {S.AWAITING_CLEANING},
    (S.CLEANING_SCHEDULED, T.CLEANING_ASSIGNMENT_EXPIRED): {S.AWAITING_CLEANING},
    (S.CLEANING_SCHEDULED, T.INCIDENT_CRITICAL): {S.CRITICAL_INCIDENT},
    (S.CLEANING_IN_PROGRESS, T.CLEANING_COMPLETED): {
        S.READY_FOR_NEXT_GUEST,
        S.AWAITING_CHECKIN,
        S.VACANT_READY,
    },
    (S.CLEANING_IN_PROGRESS, T.INCIDENT_HIGH): {S.MAINTENANCE_REQUIRED},
    (S.CLEANING_IN_PROGRESS, T.INCIDENT_CRITICAL): {S.CRITICAL_INCIDENT},
    (S.READY_FOR_NEXT_GUEST, T.CHECKIN_WINDOW_OPENED): {S.AWAITING_CHECKIN},
    (S.READY_FOR_NEXT_GUEST, T.INCIDENT_HIGH): {S.MAINTENANCE_REQUIRED},
    (S.READY_FOR_NEXT_GUEST, T.INCIDENT_CRITICAL): {S.CRITICAL_INCIDENT},
    (S.READY_FOR_NEXT_GUEST, T.OWNER_BLOCKED): {S.BLOCKED_BY_OWNER},
    (S.MAINTENANCE_REQUIRED, T.INCIDENT_RESOLVED): {
        S.CRITICAL_INCIDENT,
        S.CLEANING_IN_PROGRESS,
        S.AWAITING_CLEANING,
        S.OCCUPIED_ESTIMATED,
        S.AWAITING_CHECKIN,
        S.READY_FOR_NEXT_GUEST,
        S.VACANT_READY,
    },
    (S.MAINTENANCE_REQUIRED, T.INCIDENT_CRITICAL): {S.CRITICAL_INCIDENT},
    (S.MAINTENANCE_REQUIRED, T.OWNER_BLOCKED): {S.BLOCKED_BY_OWNER},
    (S.CRITICAL_INCIDENT, T.INCIDENT_HIGH): {S.MAINTENANCE_REQUIRED},
    (S.CRITICAL_INCIDENT, T.INCIDENT_RESOLVED): {
        S.MAINTENANCE_REQUIRED,
        S.CLEANING_IN_PROGRESS,
        S.AWAITING_CLEANING,
        S.OCCUPIED_ESTIMATED,
        S.AWAITING_CHECKIN,
        S.READY_FOR_NEXT_GUEST,
        S.VACANT_READY,
    },
    (S.CRITICAL_INCIDENT, T.OWNER_BLOCKED): {S.BLOCKED_BY_OWNER},
    (S.BLOCKED_BY_OWNER, T.OWNER_MANAGER_UNBLOCKED): {
        S.VACANT_READY,
        S.AWAITING_CHECKIN,
        S.OCCUPIED_ESTIMATED,
        S.AWAITING_CLEANING,
        S.CLEANING_SCHEDULED,
        S.CLEANING_IN_PROGRESS,
        S.READY_FOR_NEXT_GUEST,
        S.MAINTENANCE_REQUIRED,
        S.CRITICAL_INCIDENT,
        S.OUT_OF_SERVICE,
    },
    (S.OUT_OF_SERVICE, T.PROPERTY_REACTIVATED): {S.VACANT_READY},
}

# `sorted` and not bare iteration, because the values of `EXPECTED_POLICY` are **sets** of
# enum members. Enum members hash by identity, so a set of them iterates in an order that
# varies between processes — and these tuples become `@pytest.mark.parametrize` ids. Under
# `pytest -n` each worker would then collect the same tests in a different order and the run
# would abort with "Different tests were collected between gw0 and gw3" before executing
# anything. Sorting by `.value` (a string) makes the order a property of the data.
DECLARED_POLICY_RELATIONS = [
    (state, trigger, destination)
    for (state, trigger), destinations in EXPECTED_POLICY.items()
    for destination in sorted(destinations, key=lambda destination: destination.value)
]

REMOVED_CONTEXTUAL_SUPERSET_RELATIONS = [
    (source, PropertyStateTrigger.INCIDENT_RESOLVED, destination)
    for source in (
        PropertyOperationalState.MAINTENANCE_REQUIRED,
        PropertyOperationalState.CRITICAL_INCIDENT,
    )
    for destination in (
        source,
        PropertyOperationalState.CLEANING_SCHEDULED,
        PropertyOperationalState.BLOCKED_BY_OWNER,
        PropertyOperationalState.OUT_OF_SERVICE,
    )
]


def test_original_66_policy_candidates_are_explicitly_classified():
    assert PropertyStateMachine._POLICY == EXPECTED_POLICY
    assert len(DECLARED_POLICY_RELATIONS) == 58
    assert len(REMOVED_CONTEXTUAL_SUPERSET_RELATIONS) == 8
    assert len(DECLARED_POLICY_RELATIONS) + len(REMOVED_CONTEXTUAL_SUPERSET_RELATIONS) == 66


@pytest.mark.parametrize("state,trigger,destination", REMOVED_CONTEXTUAL_SUPERSET_RELATIONS)
def test_non_transitions_are_not_declared_as_valid_policy_relations(state, trigger, destination):
    assert destination not in PropertyStateMachine._POLICY[(state, trigger)]
    # Smallest by value, not `next(iter(...))`: picking from a set of enum members chooses
    # a different destination per process, so this test would exercise a different case in
    # each xdist worker — green here and red there, for no reason a reader could see.
    valid_destination = min(EXPECTED_POLICY[(state, trigger)], key=lambda s: s.value)
    request = valid_case(state, trigger, destination if destination is state else valid_destination)
    if destination is not state:
        request = replace(request, requested_state=destination)
    with pytest.raises(PropertyDomainError):
        PropertyStateMachine.evaluate(request)


@pytest.mark.parametrize("state,trigger,destination", DECLARED_POLICY_RELATIONS)
def test_every_declared_policy_relation_is_evaluable(state, trigger, destination) -> None:
    request = valid_case(state, trigger, destination)
    result = PropertyStateMachine.evaluate(request)
    assert result.transition.from_state is state
    assert result.transition.to_state is destination
    assert result.timeline_event.event_type.value == "PROPERTY_STATE_CHANGED"


@pytest.mark.parametrize("state", list(PropertyOperationalState))
@pytest.mark.parametrize("trigger", list(PropertyStateTrigger))
def test_every_undeclared_state_trigger_pair_is_rejected(state, trigger) -> None:
    if (state, trigger) in PropertyStateMachine._POLICY:
        pytest.skip("declared policy pair")
    with pytest.raises(PropertyDomainError):
        PropertyStateMachine.evaluate(valid_case(state, trigger))


# `CONTEXTUAL_STATES` is a `frozenset` in production code, so listing it yields a different
# order in every process and the parametrize ids below would not match between xdist workers.
# Sorted here rather than in `state_resolution.py`: the production set has no reason to be
# ordered, and the requirement is the test's.
CONTEXTUAL_STATES_IN_A_STABLE_ORDER = sorted(
    ContextualStateResolver.CONTEXTUAL_STATES, key=lambda state: state.value
)

INVALID_DESTINATIONS_FOR_DECLARED_PAIRS = [
    (state, trigger, destination)
    for (state, trigger), allowed in EXPECTED_POLICY.items()
    for destination in PropertyOperationalState
    if destination not in allowed
]


@pytest.mark.parametrize(
    "state,trigger,invalid_destination",
    INVALID_DESTINATIONS_FOR_DECLARED_PAIRS,
)
def test_every_invalid_destination_for_declared_pair_is_rejected(
    state,
    trigger,
    invalid_destination,
):
    # Smallest by value, not `next(iter(...))`: picking from a set of enum members chooses
    # a different destination per process, so this test would exercise a different case in
    # each xdist worker — green here and red there, for no reason a reader could see.
    valid_destination = min(EXPECTED_POLICY[(state, trigger)], key=lambda s: s.value)
    request = replace(
        valid_case(state, trigger, valid_destination),
        requested_state=invalid_destination,
    )
    with pytest.raises(PropertyDomainError):
        PropertyStateMachine.evaluate(request)


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


@pytest.mark.parametrize("destination", CONTEXTUAL_STATES_IN_A_STABLE_ORDER)
def test_unblock_rejects_every_contextual_destination_when_context_derives_another_state(destination):
    prop = make_property(PropertyOperationalState.BLOCKED_BY_OWNER)
    actor = TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4())
    context = (
        PropertyTransitionContext(incidents=(make_incident(prop, IncidentSeverity.HIGH),))
        if destination is PropertyOperationalState.VACANT_READY
        else PropertyTransitionContext()
    )
    with pytest.raises(IncompatibleTransitionContextError):
        PropertyStateMachine.evaluate(
            make_request(
                prop,
                PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED,
                context=context,
                actor=actor,
                requested_state=destination,
                reason="approved",
            )
        )


@pytest.mark.parametrize("destination", CONTEXTUAL_STATES_IN_A_STABLE_ORDER)
def test_unblock_accepts_every_contextual_destination_only_with_matching_context(destination):
    request = valid_case(
        PropertyOperationalState.BLOCKED_BY_OWNER,
        PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED,
        destination,
    )
    result = PropertyStateMachine.evaluate(request)
    assert result.transition.to_state is destination


def test_unblock_cleaning_scheduled_requires_one_assigned_or_accepted_task():
    prop = make_property(PropertyOperationalState.BLOCKED_BY_OWNER)
    actor = TransitionActor(StateTransitionTriggeredBy.USER, uuid.uuid4())
    with pytest.raises(IncompatibleTransitionContextError):
        PropertyStateMachine.evaluate(
            make_request(
                prop,
                PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED,
                actor=actor,
                requested_state=PropertyOperationalState.CLEANING_SCHEDULED,
                reason="approved",
            )
        )
    request = valid_case(
        PropertyOperationalState.BLOCKED_BY_OWNER,
        PropertyStateTrigger.OWNER_MANAGER_UNBLOCKED,
        PropertyOperationalState.CLEANING_SCHEDULED,
    )
    assert (
        PropertyStateMachine.evaluate(request).transition.to_state
        is PropertyOperationalState.CLEANING_SCHEDULED
    )


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


def test_critical_to_high_uses_all_active_incidents():
    prop = make_property(PropertyOperationalState.CRITICAL_INCIDENT)
    changed = make_incident(prop, IncidentSeverity.HIGH)
    remaining_critical = make_incident(prop, IncidentSeverity.CRITICAL)
    request = make_request(
        prop,
        PropertyStateTrigger.INCIDENT_HIGH,
        context=PropertyTransitionContext(incidents=(changed, remaining_critical)),
        source=changed.id,
    )
    with pytest.raises(NoOperationalStateChangeError):
        PropertyStateMachine.evaluate(request)


@pytest.mark.parametrize("extra_high_count", [0, 2])
def test_critical_to_high_resolves_to_maintenance_without_active_critical(extra_high_count):
    prop = make_property(PropertyOperationalState.CRITICAL_INCIDENT)
    changed = make_incident(prop, IncidentSeverity.HIGH)
    other_highs = tuple(make_incident(prop, IncidentSeverity.HIGH) for _ in range(extra_high_count))
    result = PropertyStateMachine.evaluate(
        make_request(
            prop,
            PropertyStateTrigger.INCIDENT_HIGH,
            context=PropertyTransitionContext(incidents=(changed, *other_highs)),
            source=changed.id,
        )
    )
    assert result.transition.to_state is PropertyOperationalState.MAINTENANCE_REQUIRED


def test_cleaning_completion_rejects_active_reservation_through_evaluate():
    prop = make_property(PropertyOperationalState.CLEANING_IN_PROGRESS)
    task = make_cleaning(prop, CleaningTaskStatus.COMPLETED)
    active = make_reservation(prop)
    with pytest.raises(IncompatibleTransitionContextError, match="active reservation"):
        PropertyStateMachine.evaluate(
            make_request(
                prop,
                PropertyStateTrigger.CLEANING_COMPLETED,
                context=PropertyTransitionContext(
                    reservations=(active,),
                    cleaning_tasks=(task,),
                ),
                source=task.id,
                instant=datetime(2026, 1, 1, 16, tzinfo=timezone.utc),
            )
        )


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
