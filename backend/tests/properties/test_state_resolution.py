import uuid
from datetime import date, datetime, time, timezone

import pytest

from app.cleaning.domain.entities import CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import IncidentCategory, IncidentSeverity, IncidentSource, IncidentStatus
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.exceptions import IncompatibleTransitionContextError, TransitionScopeMismatchError
from app.properties.domain.state_resolution import ContextualStateResolver
from app.properties.domain.value_objects import PropertyTransitionContext
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def prop(*, tz="UTC", tenant_id=None, property_id=None, check_in=time(15), check_out=time(11)):
    return Property(property_id or uuid.uuid4(), tenant_id or uuid.uuid4(), "Home", "H1", NOW, NOW, timezone=tz, default_check_in_time=check_in, default_check_out_time=check_out)


def reservation(p, start=date(2026, 1, 1), end=date(2026, 1, 3), *, status=ReservationStatus.CONFIRMED, in_time=None, out_time=None):
    return Reservation(uuid.uuid4(), p.tenant_id, p.id, ReservationChannel.MANUAL, start, end, (end-start).days, NOW, NOW, status=status, check_in_time=in_time, check_out_time=out_time)


def cleaning(p, status):
    return CleaningTask(uuid.uuid4(), p.tenant_id, p.id, uuid.uuid4(), NOW, NOW, status=status)


def incident(p, severity, status=IncidentStatus.OPEN):
    return Incident(uuid.uuid4(), p.tenant_id, p.id, IncidentSource.SYSTEM, "Issue", "Description", NOW, NOW, category=IncidentCategory.OTHER, severity=severity, status=status)


@pytest.mark.parametrize(
    "incidents,expected",
    [
        ((IncidentSeverity.CRITICAL,), PropertyOperationalState.CRITICAL_INCIDENT),
        ((IncidentSeverity.HIGH,), PropertyOperationalState.MAINTENANCE_REQUIRED),
    ],
)
def test_incident_precedence(incidents, expected):
    p = prop()
    context = PropertyTransitionContext(incidents=tuple(incident(p, severity) for severity in incidents))
    assert ContextualStateResolver.after_incident_resolution(p, context, NOW) is expected


def test_critical_precedes_high_and_resolved_cancelled_are_excluded():
    p = prop()
    contexts = PropertyTransitionContext(incidents=(
        incident(p, IncidentSeverity.HIGH), incident(p, IncidentSeverity.CRITICAL),
        incident(p, IncidentSeverity.CRITICAL, IncidentStatus.RESOLVED),
        incident(p, IncidentSeverity.HIGH, IncidentStatus.CANCELLED),
    ))
    assert ContextualStateResolver.after_incident_resolution(p, contexts, NOW) is PropertyOperationalState.CRITICAL_INCIDENT


@pytest.mark.parametrize(
    "status,expected",
    [(CleaningTaskStatus.IN_PROGRESS, PropertyOperationalState.CLEANING_IN_PROGRESS),
     (CleaningTaskStatus.CREATED, PropertyOperationalState.AWAITING_CLEANING),
     (CleaningTaskStatus.ASSIGNED, PropertyOperationalState.AWAITING_CLEANING),
     (CleaningTaskStatus.ACCEPTED, PropertyOperationalState.AWAITING_CLEANING)],
)
def test_cleaning_precedence(status, expected):
    p = prop()
    assert ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(cleaning_tasks=(cleaning(p, status),)), NOW) is expected


@pytest.mark.parametrize(
    "start,end,instant,expected",
    [(date(2026, 1, 1), date(2026, 1, 2), datetime(2026, 1, 1, 15, tzinfo=timezone.utc), PropertyOperationalState.OCCUPIED_ESTIMATED),
     (date(2026, 1, 1), date(2026, 1, 2), datetime(2026, 1, 2, 11, tzinfo=timezone.utc), PropertyOperationalState.VACANT_READY)],
)
def test_reservation_interval_is_half_open(start, end, instant, expected):
    p = prop()
    r = reservation(p, start, end)
    assert ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(r,)), instant) is expected


@pytest.mark.parametrize(
    "start,expected",
    [(date(2026, 1, 1), PropertyOperationalState.AWAITING_CHECKIN),
     (date(2026, 1, 3), PropertyOperationalState.READY_FOR_NEXT_GUEST)],
)
def test_next_reservation_context(start, expected):
    p = prop()
    r = reservation(p, start, start.replace(day=start.day + 2))
    assert ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(r,)), NOW) is expected


def test_cleaning_completion_has_only_reservation_destinations():
    p = prop()
    assert ContextualStateResolver.after_cleaning_completion(p, PropertyTransitionContext(), NOW) is PropertyOperationalState.VACANT_READY
    r = reservation(p, date(2026, 1, 1), date(2026, 1, 2))
    assert ContextualStateResolver.after_cleaning_completion(p, PropertyTransitionContext(reservations=(r,)), NOW) is PropertyOperationalState.AWAITING_CHECKIN


@pytest.mark.parametrize(
    "reservations,instant,expected",
    [
        ((reservation(prop(), date(2026, 1, 1), date(2026, 1, 2)),), datetime(2026, 1, 1, 16, tzinfo=timezone.utc), PropertyOperationalState.OCCUPIED_ESTIMATED),
        ((reservation(prop(), date(2026, 1, 2), date(2026, 1, 3)),), NOW, PropertyOperationalState.READY_FOR_NEXT_GUEST),
        ((), NOW, PropertyOperationalState.VACANT_READY),
    ],
)
def test_cleaning_completion_contextual_destinations(reservations, instant, expected):
    if reservations:
        # Rebind the generated reservation to one shared property for scope validity.
        p = prop()
        source = reservation(p, reservations[0].check_in_date, reservations[0].check_out_date)
        context = PropertyTransitionContext(reservations=(source,))
    else:
        p = prop()
        context = PropertyTransitionContext()
    assert ContextualStateResolver.after_cleaning_completion(p, context, instant) is expected


def test_reservation_overrides_and_property_defaults_are_used():
    p = prop(check_in=time(14), check_out=time(10))
    r = reservation(p, date(2026, 1, 1), date(2026, 1, 2), in_time=time(16), out_time=time(9))
    assert ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(r,)), datetime(2026, 1, 1, 15, tzinfo=timezone.utc)) is PropertyOperationalState.AWAITING_CHECKIN
    assert ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(r,)), datetime(2026, 1, 1, 16, tzinfo=timezone.utc)) is PropertyOperationalState.OCCUPIED_ESTIMATED


def test_timezone_conversion_and_dst_edge_are_deterministic():
    p = prop(tz="Europe/Madrid")
    r = reservation(p, date(2026, 3, 29), date(2026, 3, 30))
    instant = datetime(2026, 3, 29, 13, 0, tzinfo=timezone.utc)
    first = ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(r,)), instant)
    second = ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(r,)), instant)
    assert first is second is PropertyOperationalState.OCCUPIED_ESTIMATED


def test_incomplete_temporal_data_is_rejected():
    p = prop()
    with pytest.raises(IncompatibleTransitionContextError):
        ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(), datetime(2026, 1, 1))


def test_overlapping_active_reservations_are_rejected():
    p = prop()
    r1 = reservation(p, date(2026, 1, 1), date(2026, 1, 3))
    r2 = reservation(p, date(2026, 1, 2), date(2026, 1, 4))
    with pytest.raises(IncompatibleTransitionContextError, match="overlap"):
        ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(r2, r1)), datetime(2026, 1, 2, 16, tzinfo=timezone.utc))


def test_cross_tenant_and_cross_property_entities_are_rejected():
    p = prop()
    other_tenant = reservation(p)
    other_tenant.tenant_id = uuid.uuid4()
    with pytest.raises(TransitionScopeMismatchError):
        ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(other_tenant,)), NOW)
    other_property = reservation(p)
    other_property.property_id = uuid.uuid4()
    with pytest.raises(TransitionScopeMismatchError):
        ContextualStateResolver.after_incident_resolution(p, PropertyTransitionContext(reservations=(other_property,)), NOW)


@pytest.mark.parametrize("target,valid", [(PropertyOperationalState.VACANT_READY, True), (PropertyOperationalState.AWAITING_CHECKIN, False), (PropertyOperationalState.OCCUPIED_ESTIMATED, False)])
def test_explicit_target_is_validated_against_context(target, valid):
    p = prop()
    context = PropertyTransitionContext()
    if valid:
        ContextualStateResolver.validate_explicit_target(target, p, context, NOW)
    else:
        with pytest.raises(IncompatibleTransitionContextError):
            ContextualStateResolver.validate_explicit_target(target, p, context, NOW)
