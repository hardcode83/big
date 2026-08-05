"""`clock_triggers` — the candidate window and the check-in window (`celery-jobs` R3).

Pure domain, no fakes and no database: these pin the arithmetic the scheduled jobs lean on.

The lookahead test exists because both reviewers of section 3 caught the same thing — the
constant's own comment claimed a test pinned it and no such test existed. The claim it
makes is load-bearing (it is why a two-day lookahead is a derivation rather than a guess),
so it gets a test rather than a softer comment.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, available_timezones

import pytest

from app.properties.domain.clock_triggers import (
    CANDIDATE_LOOKAHEAD,
    CANDIDATE_LOOKBEHIND,
    candidate_window,
    opens_checkin_window,
)
from app.properties.domain.entities import Property
from app.properties.domain.exceptions import (
    IncompatibleTransitionContextError,
    InvalidTransitionInputError,
)
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus

CREATED = datetime(2026, 8, 1, tzinfo=UTC)

# The extremes of the IANA offset range plus a non-integer one, which is the case a
# "hours" mental model quietly gets wrong.
EDGE_ZONES = (
    "Pacific/Kiritimati",  # UTC+14, the maximum any zone reaches
    "Etc/GMT+12",  # UTC-12, the minimum
    "Pacific/Chatham",  # UTC+12:45 / +13:45, a quarter-hour offset
    "Asia/Kathmandu",  # UTC+05:45
    "Europe/Madrid",
    "UTC",
)


def _property(zone: str) -> Property:
    return Property(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="REDES11",
        internal_code="REDES11",
        created_at=CREATED,
        updated_at=CREATED,
        timezone=zone,
    )


def _reservation(prop: Property, *, check_in: date, check_in_time: time | None) -> Reservation:
    return Reservation.create(
        id=uuid.uuid4(),
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=2),
        now=CREATED,
        adults=2,
        check_in_time=check_in_time,
        status=ReservationStatus.CONFIRMED,
    )


def test_the_lookahead_covers_every_timezone_offset() -> None:
    """The invariant `CANDIDATE_LOOKAHEAD`'s comment claims.

    A forward-looking trigger is clamped to the property's local *day*, so the only
    reservations that can fire are those whose `check_in_date` is today **in that zone**.
    This asserts that such a date always falls inside the fetched range, for every hour of
    the UTC day and at both ends of the offset range — which is what makes two days a
    derivation and not a guess.
    """
    for zone_name in EDGE_ZONES:
        zone = ZoneInfo(zone_name)
        for hour in range(24):
            now = datetime(2026, 8, 10, hour, 30, tzinfo=UTC)
            date_from, date_to = candidate_window(now)
            local_today = now.astimezone(zone).date()
            assert date_from <= local_today <= date_to, (zone_name, hour)


def test_no_timezone_shifts_the_local_date_by_more_than_a_day() -> None:
    """The premise underneath the previous test, checked against the real IANA database
    rather than against the two zones a reader happens to remember.

    If a zone ever exceeded ±24h from UTC the lookahead reasoning would break silently, so
    this walks every zone the runtime knows and measures the actual shift. It also shows
    the margin: the maximum is one day, and the constant allows two.
    """
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    shifts = {
        (now.astimezone(ZoneInfo(name)).date() - now.date()).days
        for name in available_timezones()
    }

    assert shifts <= {-1, 0, 1}
    assert CANDIDATE_LOOKAHEAD >= timedelta(days=max(abs(shift) for shift in shifts))


def test_the_window_is_asymmetric_and_reaches_further_back() -> None:
    """`CHECKOUT_TIME_REACHED` has no day clamp, so a missed checkout stays due; the
    lookbehind is what makes an outage recoverable (design D3, section-3 QA panel)."""
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    date_from, date_to = candidate_window(now)

    assert date_to - now.date() == CANDIDATE_LOOKAHEAD
    assert now.date() - date_from == CANDIDATE_LOOKBEHIND
    assert CANDIDATE_LOOKBEHIND > CANDIDATE_LOOKAHEAD


class TestOpensCheckinWindow:
    def test_it_opens_inside_the_window_on_the_local_day(self) -> None:
        prop = _property("Europe/Madrid")
        reservation = _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))

        madrid = ZoneInfo("Europe/Madrid")
        assert opens_checkin_window(
            prop, reservation, datetime(2026, 8, 10, 13, 0, tzinfo=madrid), timedelta(hours=2)
        )
        assert not opens_checkin_window(
            prop, reservation, datetime(2026, 8, 10, 12, 59, tzinfo=madrid), timedelta(hours=2)
        )

    def test_a_window_wider_than_the_day_still_cannot_reach_yesterday(self) -> None:
        """An operator setting 100 hours gets the whole check-in day, not four days."""
        prop = _property("Europe/Madrid")
        reservation = _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))
        madrid = ZoneInfo("Europe/Madrid")

        assert not opens_checkin_window(
            prop, reservation, datetime(2026, 8, 9, 23, 59, tzinfo=madrid), timedelta(hours=100)
        )
        assert opens_checkin_window(
            prop, reservation, datetime(2026, 8, 10, 0, 0, tzinfo=madrid), timedelta(hours=100)
        )

    def test_it_refuses_a_naive_instant_with_the_domains_own_error(self) -> None:
        """It runs before `PropertyStateMachine.evaluate` gets to reject one, so without
        this guard the caller would see a bare `TypeError` from datetime arithmetic."""
        prop = _property("Europe/Madrid")
        reservation = _reservation(prop, check_in=date(2026, 8, 10), check_in_time=time(15, 0))

        with pytest.raises(InvalidTransitionInputError):
            opens_checkin_window(prop, reservation, datetime(2026, 8, 10, 13, 0), timedelta(hours=2))

    def test_an_impossible_local_time_surfaces_as_a_domain_error(self) -> None:
        """02:30 does not exist in Madrid on 2026-03-29; the caller counts it apart from
        "not due yet" (R3.4) precisely because this raises instead of returning False."""
        prop = _property("Europe/Madrid")
        reservation = _reservation(prop, check_in=date(2026, 3, 29), check_in_time=time(2, 30))

        with pytest.raises(IncompatibleTransitionContextError):
            opens_checkin_window(
                prop,
                reservation,
                datetime(2026, 3, 29, 10, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                timedelta(hours=2),
            )
