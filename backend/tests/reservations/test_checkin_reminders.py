"""`SendCheckinRemindersUseCase` against fakes (`guest-scheduled-comms` R1, R4; design D1-D8).

Unit tests with in-memory fakes of the ports, as `steering/backend-architecture.md` prescribes
for `application/`: fakes, never the real DB and never a SQLAlchemy mock. `tests/reservations/
doubles.py` already supplies `FakePropertyRepository`, `FakeGuestRepository` and
`FakeReservationRepository`; this file adds the one double those tests do not need —
`FakeNotificationLogRepository`, which is the one port this use case dedups and writes through.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.entities import Guest
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus, NotificationType
from app.properties.domain.entities import Property
from app.reservations.application.use_cases import SendCheckinRemindersUseCase
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus

from .doubles import (
    FakeGuestRepository,
    FakePropertyRepository,
    FakeReservationRepository,
    FakeUnitOfWork,
)

TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()


@dataclass
class FakeNotificationLogRepository:
    """`NotificationLogRepository`, of which only `add` and `exists_for` are reachable from
    this use case."""

    rows: list[NotificationLog] = field(default_factory=list)

    async def add(self, tenant_id: uuid.UUID, log: NotificationLog) -> None:
        if log.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="notification_log", entity_tenant_id=log.tenant_id, acting_tenant_id=tenant_id
            )
        self.rows.append(log)

    async def exists_for(
        self, tenant_id: uuid.UUID, *, related_type: str, related_id: uuid.UUID, notification_type: str
    ) -> bool:
        assert related_type is not None and related_id is not None
        return any(
            row.tenant_id == tenant_id
            and row.related_type == related_type
            and row.related_id == related_id
            and row.notification_type == notification_type
            for row in self.rows
        )

    # The rest of the Protocol is unreachable from this use case; a call here is a bug.
    async def list_sla_breach_candidates(self, tenant_id, now):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")

    async def mark_breached(self, tenant_id, log):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")

    async def list_pending(self, tenant_id, limit):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")

    async def list_for_recipient(self, tenant_id, recipient_user_id, *, page, per_page, unread=None, channel=NotificationChannel.IN_APP):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")

    async def mark_read(self, tenant_id, user_id, log_id):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")

    async def count_unread(self, tenant_id, user_id, *, channel=NotificationChannel.IN_APP):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")

    async def mark_all_read(self, tenant_id, user_id):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")

    async def record_attempt(self, tenant_id, log_id, *, status, attempts, sent_at, last_error):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")

    async def cancel_sla_deadline(self, tenant_id, *, related_type, related_id, notification_type):  # pragma: no cover
        raise AssertionError("not exercised by SendCheckinRemindersUseCase")


def _now() -> datetime:
    return datetime(2026, 9, 13, 0, 0, tzinfo=UTC)


def _property(**overrides: Any) -> Property:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Casa Sol",
        internal_code="CS-01",
        created_at=_now(),
        updated_at=_now(),
        timezone="Europe/Madrid",
        default_check_in_time=time(15, 0),
    )
    defaults.update(overrides)
    return Property(**defaults)


def _reservation(
    *, property_id: uuid.UUID, check_in_date: date, guest_id: uuid.UUID | None, **overrides: Any
) -> Reservation:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        property_id=property_id,
        channel=ReservationChannel.MANUAL,
        check_in_date=check_in_date,
        check_out_date=check_in_date + timedelta(days=2),
        nights=2,
        created_at=_now(),
        updated_at=_now(),
        guest_id=guest_id,
        status=ReservationStatus.CONFIRMED,
    )
    defaults.update(overrides)
    return Reservation(**defaults)


def _guest(*, email: str | None = "guest@example.com", **overrides: Any) -> Guest:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        full_name="Ana Guest",
        created_at=_now(),
        updated_at=_now(),
        email=email,
    )
    defaults.update(overrides)
    return Guest(**defaults)


def _checkin_instant(prop: Property, reservation: Reservation) -> datetime:
    """The same computation `effective_bounds` performs, used only to derive `now` for a test
    — never imported by the use case itself."""
    zone = ZoneInfo(prop.timezone)
    check_in_time = reservation.check_in_time or prop.default_check_in_time
    naive = datetime.combine(reservation.check_in_date, check_in_time)
    return naive.replace(tzinfo=zone).astimezone(UTC)


@dataclass
class World:
    properties: FakePropertyRepository
    reservations: FakeReservationRepository
    guests: FakeGuestRepository
    notifications: FakeNotificationLogRepository
    uow: FakeUnitOfWork
    use_case: SendCheckinRemindersUseCase


def _world() -> World:
    properties = FakePropertyRepository()
    reservations = FakeReservationRepository()
    guests = FakeGuestRepository()
    notifications = FakeNotificationLogRepository()
    uow = FakeUnitOfWork()
    use_case = SendCheckinRemindersUseCase(
        properties=properties,
        reservations=reservations,
        guests=guests,
        notifications=notifications,
        uow=uow,
    )
    return World(properties, reservations, guests, notifications, uow, use_case)


@pytest.mark.asyncio
async def test_the_24h_window_fires_exactly_once() -> None:
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant - timedelta(hours=20)  # inside the 24h window, outside the 2h one

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 1
    assert len(world.notifications.rows) == 1
    row = world.notifications.rows[0]
    assert row.notification_type == NotificationType.CHECKIN_REMINDER_24H.value
    assert row.channel is NotificationChannel.EMAIL
    assert row.status is NotificationStatus.PENDING
    assert row.recipient_contact == "guest@example.com"
    assert row.related_type == "reservation"
    assert row.related_id == reservation.id
    assert row.sla_deadline_at is None
    assert world.uow.commits == 1


@pytest.mark.asyncio
async def test_the_2h_window_also_fires_and_both_are_independent() -> None:
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant - timedelta(hours=1)  # inside both windows

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 2
    types = {row.notification_type for row in world.notifications.rows}
    assert types == {
        NotificationType.CHECKIN_REMINDER_24H.value,
        NotificationType.CHECKIN_REMINDER_2H.value,
    }


@pytest.mark.asyncio
async def test_a_second_run_does_not_duplicate_either_type() -> None:
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant - timedelta(hours=1)

    first = await world.use_case.execute(tenant_id=TENANT, now=now)
    second = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert first.written == 2
    assert second.written == 0
    assert len(world.notifications.rows) == 2


@pytest.mark.asyncio
async def test_a_reservation_with_no_guest_email_is_skipped_and_counted() -> None:
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest(email=None))
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant - timedelta(hours=1)

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 0
    assert report.skipped_missing_email == 1
    assert report.candidates == 1
    assert world.notifications.rows == []


@pytest.mark.asyncio
async def test_a_reservation_with_no_guest_id_is_skipped_and_counted() -> None:
    world = _world()
    prop = world.properties.add_property(_property())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=None
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant - timedelta(hours=1)

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 0
    assert report.skipped_missing_email == 1


@pytest.mark.asyncio
async def test_a_dst_invalid_local_time_is_skipped_and_counted_not_raised() -> None:
    """Europe/Madrid springs forward on the last Sunday of March: 2026-03-29 02:00 local time
    does not exist. `effective_bounds` raises `IncompatibleTransitionContextError`, and the use
    case must swallow it per-candidate rather than let it abort the tenant's sweep (R4, design
    *Risks*)."""
    world = _world()
    prop = world.properties.add_property(
        _property(default_check_in_time=time(2, 30))
    )
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 3, 29), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    now = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 0
    assert report.skipped_invalid_local_time == 1
    assert world.notifications.rows == []


@pytest.mark.asyncio
async def test_a_dst_invalid_property_does_not_abort_the_rest_of_the_sweep() -> None:
    world = _world()
    bad_property = world.properties.add_property(
        _property(default_check_in_time=time(2, 30))
    )
    good_property = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())

    bad_reservation = _reservation(
        property_id=bad_property.id, check_in_date=date(2026, 3, 29), guest_id=guest.id
    )
    world.reservations.reservations[bad_reservation.id] = bad_reservation

    good_reservation = _reservation(
        property_id=good_property.id, check_in_date=date(2026, 3, 30), guest_id=guest.id
    )
    world.reservations.reservations[good_reservation.id] = good_reservation
    checkin_instant = _checkin_instant(good_property, good_reservation)
    now = checkin_instant - timedelta(hours=1)

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.skipped_invalid_local_time == 1
    assert report.written == 2
    assert {row.related_id for row in world.notifications.rows} == {good_reservation.id}


@pytest.mark.asyncio
async def test_a_reservation_far_outside_either_window_writes_nothing() -> None:
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant - timedelta(hours=48)

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 0
    assert world.notifications.rows == []


@pytest.mark.asyncio
async def test_the_24h_lower_bound_is_inclusive_and_fires() -> None:
    """D3's lower bound: `checkin_instant - lead <= now` — `now` exactly at the 24h threshold
    must still fire `CHECKIN_REMINDER_24H` (not `<`, which would miss this tick)."""
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant - timedelta(hours=24)  # exactly the 24h threshold, inclusive

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 1
    assert len(world.notifications.rows) == 1
    row = world.notifications.rows[0]
    assert row.notification_type == NotificationType.CHECKIN_REMINDER_24H.value
    assert row.status is NotificationStatus.PENDING


@pytest.mark.asyncio
async def test_the_upper_bound_is_exclusive_at_the_checkin_instant() -> None:
    """D3's upper bound: `now < checkin_instant` — `now` exactly equal to `checkin_instant`
    must not fire either reminder (the stay has already begun, so `<` and not `<=`)."""
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant  # exactly at check-in, the upper bound is exclusive

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 0
    assert world.notifications.rows == []


@pytest.mark.asyncio
async def test_a_reservation_whose_check_in_already_passed_writes_nothing() -> None:
    """D3's upper bound: `now < checkin_instant` — a stay already begun must not retroactively
    fire a stale reminder."""
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id, check_in_date=date(2026, 9, 20), guest_id=guest.id
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant + timedelta(hours=1)

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.written == 0
    assert world.notifications.rows == []


@pytest.mark.asyncio
async def test_a_reservation_not_confirmed_is_not_a_candidate_at_all() -> None:
    world = _world()
    prop = world.properties.add_property(_property())
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(
        property_id=prop.id,
        check_in_date=date(2026, 9, 20),
        guest_id=guest.id,
        status=ReservationStatus.PENDING,
    )
    world.reservations.reservations[reservation.id] = reservation
    checkin_instant = _checkin_instant(prop, reservation)
    now = checkin_instant - timedelta(hours=1)

    report = await world.use_case.execute(tenant_id=TENANT, now=now)

    assert report.candidates == 0
    assert report.written == 0


@pytest.mark.asyncio
async def test_no_properties_short_circuits_without_touching_other_ports() -> None:
    world = _world()

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report == type(report)()
    assert world.uow.commits == 0
