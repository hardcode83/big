"""`cleaning/domain/windows.py` — the two instants the cleaner's context reports (R2.1-R2.4).

Pure domain, no fakes and no database, same shape as `tests/properties/test_clock_triggers.py`.
Written before the implementation (`steering/testing.md` § TDD en `domain/`): these are rules
with a real invariant, and `domain/` is Python with no infra to stand up.

What they pin that a use-case test could not: that a checkout whose local time cannot exist
comes back as `None` rather than as `now`. That difference is design D5's reason for **not**
reusing `_effective_checkout` — degrading to `now` is right for a scheduling hint and is an
invented departure time on a cleaner's screen.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.properties.domain.entities import Property
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus

CREATED = datetime(2026, 8, 1, tzinfo=UTC)
MADRID = ZoneInfo("Europe/Madrid")


def _property(*, zone: str = "Europe/Madrid", check_out: time = time(11, 0)) -> Property:
    return Property(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Redes 11",
        internal_code="REDES11",
        created_at=CREATED,
        updated_at=CREATED,
        timezone=zone,
        default_check_out_time=check_out,
    )


def _reservation(
    prop: Property,
    *,
    check_in: date,
    nights: int = 2,
    check_in_time: time | None = None,
    check_out_time: time | None = None,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
) -> Reservation:
    return Reservation.create(
        id=uuid.uuid4(),
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=nights),
        now=CREATED,
        adults=2,
        check_in_time=check_in_time,
        check_out_time=check_out_time,
        status=status,
    )


class TestResolveCheckout:
    def test_it_returns_the_reservations_own_checkout_time_in_the_properties_zone(self) -> None:
        """R2.1's first half, and R2.4: the instant carries the zone, not a bare wall time."""
        prop = _property()
        reservation = _reservation(prop, check_in=date(2026, 8, 10), check_out_time=time(10, 30))

        from app.cleaning.domain.windows import resolve_checkout

        checkout = resolve_checkout(prop, reservation)

        assert checkout == datetime(2026, 8, 12, 10, 30, tzinfo=MADRID)
        assert checkout is not None and checkout.utcoffset() == timedelta(hours=2)

    def test_it_falls_back_to_the_properties_default_when_the_reservation_has_none(self) -> None:
        """R2.1's second half. The fallback is `effective_bounds`', not a copy of it."""
        prop = _property(check_out=time(11, 0))
        reservation = _reservation(prop, check_in=date(2026, 8, 10), check_out_time=None)

        from app.cleaning.domain.windows import resolve_checkout

        assert resolve_checkout(prop, reservation) == datetime(2026, 8, 12, 11, 0, tzinfo=MADRID)

    def test_a_checkout_whose_local_time_cannot_exist_is_none_and_not_now(self) -> None:
        """02:30 does not exist in Madrid on 2026-03-29, so `effective_bounds` refuses.

        Design D5: `_effective_checkout` answers `now` here because a planning hint is better
        approximate than absent. A departure time shown to a cleaner is not — `null` is the
        honest answer and this is the test that keeps the two apart.
        """
        prop = _property()
        reservation = _reservation(prop, check_in=date(2026, 3, 27), check_out_time=time(2, 30))

        from app.cleaning.domain.windows import resolve_checkout

        assert resolve_checkout(prop, reservation) is None


class TestNextArrivalAfter:
    def test_it_returns_the_earliest_confirmed_arrival_at_or_after_the_anchor(self) -> None:
        """R2.2 — the *minimum*, not the first in the sequence."""
        prop = _property()
        anchor = datetime(2026, 8, 12, 11, 0, tzinfo=MADRID)
        far = _reservation(prop, check_in=date(2026, 8, 20), check_in_time=time(15, 0))
        near = _reservation(prop, check_in=date(2026, 8, 13), check_in_time=time(16, 0))

        from app.cleaning.domain.windows import next_arrival_after

        assert next_arrival_after(prop, [far, near], anchor) == datetime(
            2026, 8, 13, 16, 0, tzinfo=MADRID
        )

    def test_an_arrival_before_the_anchor_is_not_a_deadline(self) -> None:
        prop = _property()
        anchor = datetime(2026, 8, 12, 11, 0, tzinfo=MADRID)
        past = _reservation(prop, check_in=date(2026, 8, 5), check_in_time=time(15, 0))

        from app.cleaning.domain.windows import next_arrival_after

        assert next_arrival_after(prop, [past], anchor) is None

    def test_it_skips_the_excluded_reservation(self) -> None:
        """The projection's own outgoing stay must not be counted as an arrival (R2.2)."""
        prop = _property()
        anchor = datetime(2026, 8, 10, 11, 0, tzinfo=MADRID)
        own = _reservation(prop, check_in=date(2026, 8, 12), check_in_time=time(15, 0))

        from app.cleaning.domain.windows import next_arrival_after

        assert next_arrival_after(prop, [own], anchor, exclude_id=own.id) is None

    def test_without_an_exclusion_it_skips_nothing(self) -> None:
        """`exclude_id=None` is the projection's case for a task with no reservation (D6)."""
        prop = _property()
        anchor = datetime(2026, 8, 10, 11, 0, tzinfo=MADRID)
        arrival = _reservation(prop, check_in=date(2026, 8, 12), check_in_time=time(15, 0))

        from app.cleaning.domain.windows import next_arrival_after

        assert next_arrival_after(prop, [arrival], anchor) == datetime(
            2026, 8, 12, 15, 0, tzinfo=MADRID
        )

    def test_a_pending_arrival_imposes_no_deadline(self) -> None:
        """Inherited from `_next_checkin` rather than diverged from, and visible in the
        response: `CONFIRMED` only, so a `PENDING` arrival answers `None`."""
        prop = _property()
        anchor = datetime(2026, 8, 10, 11, 0, tzinfo=MADRID)
        pending = _reservation(
            prop,
            check_in=date(2026, 8, 12),
            check_in_time=time(15, 0),
            status=ReservationStatus.PENDING,
        )

        from app.cleaning.domain.windows import next_arrival_after

        assert next_arrival_after(prop, [pending], anchor) is None

    def test_a_candidate_whose_local_time_cannot_exist_is_ignored_not_fatal(self) -> None:
        """02:30 does not exist in Madrid on 2026-03-29. One unmaterialisable stay must not
        cost the deadline that a later, healthy one would give."""
        prop = _property()
        anchor = datetime(2026, 3, 1, 11, 0, tzinfo=MADRID)
        broken = _reservation(prop, check_in=date(2026, 3, 29), check_in_time=time(2, 30))
        healthy = _reservation(prop, check_in=date(2026, 3, 30), check_in_time=time(15, 0))

        from app.cleaning.domain.windows import next_arrival_after

        assert next_arrival_after(prop, [broken, healthy], anchor) == datetime(
            2026, 3, 30, 15, 0, tzinfo=MADRID
        )

    def test_no_candidates_at_all_is_none(self) -> None:
        """R2.3 — `null`, not an invented date and not an error."""
        prop = _property()

        from app.cleaning.domain.windows import next_arrival_after

        assert next_arrival_after(prop, [], datetime(2026, 8, 12, 11, 0, tzinfo=MADRID)) is None


def test_the_next_arrival_horizon_is_fourteen_days_and_not_the_schedulers_lookahead() -> None:
    """Design D10, pinned. The constant's comment claims it is deliberately *not*
    `CANDIDATE_LOOKAHEAD`; reusing that two-day window would reproduce the defect the live
    projection exists to fix, so the difference gets a test rather than a comment alone."""
    from app.properties.domain.clock_triggers import CANDIDATE_LOOKAHEAD

    from app.cleaning.domain.windows import NEXT_ARRIVAL_HORIZON

    assert NEXT_ARRIVAL_HORIZON == timedelta(days=14)
    assert NEXT_ARRIVAL_HORIZON != CANDIDATE_LOOKAHEAD


class TestNextArrivalWithinHorizon:
    """The bound the projection applies (D10). `next_arrival_after` stays unbounded for the job."""

    def test_an_arrival_exactly_at_the_horizon_still_counts(self) -> None:
        """The threshold is inclusive, and that is a decision, not an accident.

        Pinned because a mutant flipping `>` to `>=` would otherwise survive the whole suite: every
        other test in this file sits a day or more from the boundary. D10 says `null` means "no
        `CONFIRMED` arrival **within** 14 days", and an arrival at exactly 14 days is within them.
        """
        from app.cleaning.domain.windows import NEXT_ARRIVAL_HORIZON, next_arrival_within_horizon

        prop = _property()
        anchor = datetime(2026, 8, 12, 15, 0, tzinfo=MADRID)
        exactly = anchor + NEXT_ARRIVAL_HORIZON
        arrival = _reservation(prop, check_in=exactly.date(), check_in_time=exactly.timetz())

        assert next_arrival_within_horizon(prop, [arrival], anchor) == exactly

    def test_an_arrival_one_hour_past_the_horizon_does_not(self) -> None:
        """The other side of the same boundary."""
        from app.cleaning.domain.windows import NEXT_ARRIVAL_HORIZON, next_arrival_within_horizon

        prop = _property()
        anchor = datetime(2026, 8, 12, 15, 0, tzinfo=MADRID)
        past = anchor + NEXT_ARRIVAL_HORIZON + timedelta(hours=1)
        arrival = _reservation(prop, check_in=past.date(), check_in_time=past.timetz())

        assert next_arrival_within_horizon(prop, [arrival], anchor) is None

    def test_it_still_prefers_the_earliest_arrival_inside_the_horizon(self) -> None:
        """Clamping must not turn `min` into "the first one that fits"."""
        from app.cleaning.domain.windows import next_arrival_within_horizon

        prop = _property()
        anchor = datetime(2026, 8, 12, 11, 0, tzinfo=MADRID)
        far = _reservation(prop, check_in=date(2026, 8, 24), check_in_time=time(15, 0))
        near = _reservation(prop, check_in=date(2026, 8, 14), check_in_time=time(16, 0))

        assert next_arrival_within_horizon(prop, [far, near], anchor) == datetime(
            2026, 8, 14, 16, 0, tzinfo=MADRID
        )


def test_a_naive_anchor_is_the_domains_own_error_not_a_bare_typeerror() -> None:
    """`effective_bounds` returns aware instants, so a naive anchor would blow up mid-comparison.

    Same reason as `opens_checkin_window` in `clock_triggers`, but a `ValueError` rather than that
    module's `InvalidTransitionInputError`: raising `properties`' error from `cleaning` would have
    it answered by the wrong module's handler. No production caller can reach this — both anchor on
    aware values — so it pins the guard rather than a live bug.
    """
    from app.cleaning.domain.windows import next_arrival_after

    prop = _property()
    arrival = _reservation(prop, check_in=date(2026, 8, 13), check_in_time=time(16, 0))

    with pytest.raises(ValueError, match="timezone-aware"):
        next_arrival_after(prop, [arrival], datetime(2026, 8, 12, 11, 0))
