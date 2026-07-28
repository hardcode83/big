import uuid
from datetime import date, datetime, timezone

from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.state_resolution import ContextualStateResolver
from app.properties.domain.value_objects import PropertyTransitionContext
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus


def _property() -> Property:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Property(uuid.uuid4(), uuid.uuid4(), "Home", "H1", now, now, timezone="UTC")


def _reservation(property: Property, check_in: date, check_out: date, status: ReservationStatus) -> Reservation:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Reservation(uuid.uuid4(), property.tenant_id, property.id, ReservationChannel.MANUAL, check_in, check_out, (check_out-check_in).days, now, now, status=status)


def test_resolver_uses_half_open_reservation_interval() -> None:
    prop = _property()
    reservation = _reservation(prop, date(2026, 1, 1), date(2026, 1, 2), ReservationStatus.CONFIRMED)
    context = PropertyTransitionContext(reservations=(reservation,))
    assert ContextualStateResolver.after_incident_resolution(prop, context, datetime(2026, 1, 1, 15, tzinfo=timezone.utc)) is PropertyOperationalState.OCCUPIED_ESTIMATED
    assert ContextualStateResolver.after_incident_resolution(prop, context, datetime(2026, 1, 2, 11, tzinfo=timezone.utc)) is PropertyOperationalState.VACANT_READY
