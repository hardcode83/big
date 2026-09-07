"""The occupied-night rule (`dashboard-occupancy-series` R1.1, R1.3, R2, design D3, D4).

Written before `occupancy_series` existed: `steering/testing.md` requires TDD "en `domain/`
con invariante real", and the invariant here has genuine solution variance — the state of a
flat on a past day is *reconstructed* from its transition history, and "in effect at the end
of the day" is one of several defensible readings of R2.1's "en algún instante de D". D3
chose the end-of-day snapshot with the user at the design gate of 2026-09-02, so the case
that reading gives up on (`test_a_same_day_block_and_release_does_not_surface`) is pinned
here on purpose rather than left as an accident nobody would notice.

No database and no mocks: the whole module is pure, so every fixture below is a literal.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.dashboard.domain.occupancy import (
    OCCUPYING_STATES,
    end_of_day_exclusive,
    occupancy_series,
    week_bounds,
)
from app.dashboard.domain.read_models import OccupancyPoint
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import (
    PropertyOperationalState,
    StateTransitionTriggeredBy,
)
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus

STATE = PropertyOperationalState

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
PROPERTY = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_PROPERTY = uuid.UUID("33333333-3333-3333-3333-333333333333")

#: A Monday, so `MONDAY + n` is the n-th day of the series and every assertion below can
#: index the week by hand.
MONDAY = date(2026, 8, 31)
WEDNESDAY = MONDAY + timedelta(days=2)


def a_reservation(
    *,
    property_id: uuid.UUID = PROPERTY,
    check_in: date,
    check_out: date,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
) -> Reservation:
    created = datetime(2026, 8, 1, tzinfo=UTC)
    return Reservation(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        property_id=property_id,
        channel=ReservationChannel.DIRECT,
        check_in_date=check_in,
        check_out_date=check_out,
        nights=(check_out - check_in).days,
        created_at=created,
        updated_at=created,
        status=status,
    )


def a_transition(
    *,
    to_state: PropertyOperationalState,
    created_at: datetime,
    property_id: uuid.UUID = PROPERTY,
) -> PropertyStateTransition:
    return PropertyStateTransition(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        property_id=property_id,
        to_state=to_state,
        triggered_by=StateTransitionTriggeredBy.USER,
        created_at=created_at,
    )


def occupied_days(points: tuple[OccupancyPoint, ...]) -> list[date]:
    return [point.date for point in points if point.occupied_properties > 0]


# --- week_bounds (R1.1) ------------------------------------------------------------------


def test_week_bounds_of_a_midweek_day_is_monday_to_sunday() -> None:
    """R1.1: "la semana calendario en curso (ISO, lunes a domingo)". A Wednesday must resolve
    backwards to its own Monday, not forwards to the next one."""
    start, end = week_bounds(WEDNESDAY)

    assert start == MONDAY
    assert end == date(2026, 9, 6)
    assert start.weekday() == 0
    assert end.weekday() == 6
    assert (end - start).days == 6


@pytest.mark.parametrize("offset", range(7))
def test_every_day_of_a_week_resolves_to_the_same_bounds(offset: int) -> None:
    """The bounds are a property of the week, not of the day asked about."""
    assert week_bounds(MONDAY + timedelta(days=offset)) == (MONDAY, MONDAY + timedelta(days=6))


def test_the_end_bound_is_the_inclusive_sunday_not_the_next_monday() -> None:
    """`history_for_properties` turns `end` into midnight UTC of `end + 1`, so an exclusive
    Monday here would read an eighth day of history."""
    _, end = week_bounds(MONDAY)

    assert end == MONDAY + timedelta(days=6)
    assert end_of_day_exclusive(end) == datetime(2026, 9, 7, tzinfo=UTC)


# --- shape of the series (R1.1, R1.2) ---------------------------------------------------


def test_the_series_is_seven_points_in_monday_to_sunday_order() -> None:
    """R1.1: "exactamente siete puntos ... ordenados de lunes a domingo"."""
    points = occupancy_series(MONDAY, [PROPERTY], [], {})

    assert len(points) == 7
    assert [point.date for point in points] == [MONDAY + timedelta(days=n) for n in range(7)]


def test_every_point_reports_the_portfolio_total() -> None:
    """R1.2: `total_properties` is the tenant's active portfolio, the same on all seven days
    — it is a denominator, not a per-day count."""
    points = occupancy_series(MONDAY, [PROPERTY, OTHER_PROPERTY], [], {})

    assert {point.total_properties for point in points} == {2}


def test_a_property_listed_twice_is_counted_once() -> None:
    """Otherwise a duplicated id would inflate the denominator and depress every percentage
    below it."""
    points = occupancy_series(MONDAY, [PROPERTY, PROPERTY], [], {})

    assert points[0].total_properties == 1


# --- R2.1, condition one: reservation coverage ------------------------------------------


def test_a_reservation_occupies_its_nights_and_not_the_checkout_day() -> None:
    """R2.1: the range is `[check_in_date, check_out_date)` — the check-out day is not a
    night, the same half-open reading `occupancy_pct_for` already uses."""
    reservation = a_reservation(check_in=MONDAY + timedelta(days=1), check_out=MONDAY + timedelta(days=3))

    points = occupancy_series(MONDAY, [PROPERTY], [reservation], {})

    assert occupied_days(points) == [MONDAY + timedelta(days=1), MONDAY + timedelta(days=2)]


@pytest.mark.parametrize(
    "status",
    [ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW],
    ids=lambda status: status.value,
)
def test_a_cancelled_or_no_show_reservation_occupies_nothing(status: ReservationStatus) -> None:
    """R2.1 imports the definition from `app/pricing/domain/occupancy.py`: a cancellation and
    a no-show are the two states that describe a night which ended up free."""
    reservation = a_reservation(check_in=MONDAY, check_out=MONDAY + timedelta(days=3), status=status)

    points = occupancy_series(MONDAY, [PROPERTY], [reservation], {})

    assert occupied_days(points) == []


@pytest.mark.parametrize(
    "status",
    [
        ReservationStatus.PENDING,
        ReservationStatus.CONFIRMED,
        ReservationStatus.CHECKED_IN_ESTIMATED,
        ReservationStatus.CHECKED_OUT_ESTIMATED,
        ReservationStatus.COMPLETED,
    ],
    ids=lambda status: status.value,
)
def test_every_other_status_occupies_its_nights(status: ReservationStatus) -> None:
    """`PENDING` included: it is a night the PMS calendar already blocks even though nobody
    confirmed it."""
    reservation = a_reservation(check_in=MONDAY, check_out=MONDAY + timedelta(days=1), status=status)

    points = occupancy_series(MONDAY, [PROPERTY], [reservation], {})

    assert occupied_days(points) == [MONDAY]


def test_a_reservation_of_a_property_outside_the_portfolio_is_ignored() -> None:
    """`active_property_ids` is the filter as well as the denominator: an inactive flat's
    stay must not push `occupied_properties` past `total_properties`."""
    reservation = a_reservation(
        property_id=OTHER_PROPERTY, check_in=MONDAY, check_out=MONDAY + timedelta(days=7)
    )

    points = occupancy_series(MONDAY, [PROPERTY], [reservation], {})

    assert occupied_days(points) == []
    assert {point.total_properties for point in points} == {1}


def test_a_stay_spanning_the_whole_week_occupies_all_seven_days() -> None:
    reservation = a_reservation(
        check_in=MONDAY - timedelta(days=3), check_out=MONDAY + timedelta(days=10)
    )

    points = occupancy_series(MONDAY, [PROPERTY], [reservation], {})

    assert all(point.occupied_properties == 1 for point in points)


# --- R2.1, conditions two and three: blocked / out of service ---------------------------


@pytest.mark.parametrize(
    "state",
    [STATE.BLOCKED_BY_OWNER, STATE.OUT_OF_SERVICE],
    ids=lambda state: state.value,
)
def test_a_property_left_in_a_blocking_state_is_occupied_from_that_day_on(
    state: PropertyOperationalState,
) -> None:
    """R2.1's second and third conditions, and R2.2's reconstruction: the transition entered
    the state on Wednesday and nothing followed, so Wednesday to Sunday are occupied."""
    transitions = (a_transition(to_state=state, created_at=datetime(2026, 9, 2, 10, tzinfo=UTC)),)

    points = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: transitions})

    assert occupied_days(points) == [MONDAY + timedelta(days=n) for n in (2, 3, 4, 5, 6)]


def test_a_transition_before_the_week_carries_its_state_into_every_day() -> None:
    """R2.2: the state in effect on Monday comes from the last transition *before* Monday —
    the "entering transition" section 1's reader deliberately fetches."""
    transitions = (
        a_transition(to_state=STATE.OUT_OF_SERVICE, created_at=datetime(2026, 8, 20, tzinfo=UTC)),
    )

    points = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: transitions})

    assert all(point.occupied_properties == 1 for point in points)


def test_leaving_the_blocking_state_frees_that_day_and_the_days_after() -> None:
    """The release is the transition in effect at the end of Thursday, so Thursday onwards is
    free even though the flat was blocked for most of that morning — see the same-day case
    below for why that is the accepted reading."""
    transitions = (
        a_transition(to_state=STATE.BLOCKED_BY_OWNER, created_at=datetime(2026, 8, 25, tzinfo=UTC)),
        a_transition(to_state=STATE.VACANT_READY, created_at=datetime(2026, 9, 3, 9, tzinfo=UTC)),
    )

    points = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: transitions})

    assert occupied_days(points) == [MONDAY + timedelta(days=n) for n in (0, 1, 2)]


def test_a_non_blocking_state_is_not_occupancy_on_its_own() -> None:
    """R2.1 names exactly two states. `AWAITING_CLEANING` is a flat with work pending, not a
    night sold, and `OCCUPIED_ESTIMATED` is the state machine's *guess* from the same
    calendar this function already reads (`state_resolution.py:164-166`) — counting it would
    let an estimate outlive the reservation that produced it."""
    for state in (STATE.AWAITING_CLEANING, STATE.OCCUPIED_ESTIMATED, STATE.VACANT_READY):
        transitions = (a_transition(to_state=state, created_at=datetime(2026, 8, 20, tzinfo=UTC)),)

        points = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: transitions})

        assert occupied_days(points) == [], state


def test_the_occupying_states_are_exactly_the_two_the_requirement_names() -> None:
    """Stated as literals rather than derived from the module, so a third state cannot be
    added to the constant without a requirement to point at."""
    assert OCCUPYING_STATES == {STATE.BLOCKED_BY_OWNER, STATE.OUT_OF_SERVICE}


# --- R2.3: no history at all ------------------------------------------------------------


def test_a_property_absent_from_the_history_is_neither_blocked_nor_out_of_service() -> None:
    """R2.3, and the sparse contract of `history_for_properties`: a property with no
    transition before or during the window is **absent from the dict**, not mapped to `()`.
    A `KeyError` here would be the endpoint's 500."""
    points = occupancy_series(MONDAY, [PROPERTY, OTHER_PROPERTY], [], {})

    assert occupied_days(points) == []
    assert {point.total_properties for point in points} == {2}


def test_a_missing_key_and_an_empty_sequence_agree() -> None:
    """The two spellings of "no transitions" must not produce different series."""
    absent = occupancy_series(MONDAY, [PROPERTY], [], {})
    empty = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: ()})

    assert absent == empty


# --- R2.1: the union, without double counting -------------------------------------------


def test_a_day_both_reserved_and_blocked_counts_the_property_once() -> None:
    """R2.1: "cualquiera de estas tres condiciones (unión, sin doble conteo)". The day's
    occupied properties are a set, so this cannot report 2 out of 1."""
    reservation = a_reservation(check_in=MONDAY, check_out=MONDAY + timedelta(days=2))
    transitions = (
        a_transition(to_state=STATE.BLOCKED_BY_OWNER, created_at=datetime(2026, 8, 20, tzinfo=UTC)),
    )

    points = occupancy_series(MONDAY, [PROPERTY], [reservation], {PROPERTY: transitions})

    assert all(point.occupied_properties == 1 for point in points)
    assert {point.occupancy_pct for point in points} == {Decimal("100.0")}


def test_two_overlapping_reservations_on_one_property_count_once() -> None:
    """Two rows covering Monday are one occupied flat, not two."""
    points = occupancy_series(
        MONDAY,
        [PROPERTY],
        [
            a_reservation(check_in=MONDAY, check_out=MONDAY + timedelta(days=2)),
            a_reservation(check_in=MONDAY, check_out=MONDAY + timedelta(days=1)),
        ],
        {},
    )

    assert points[0].occupied_properties == 1


def test_the_union_adds_up_across_different_properties() -> None:
    """One flat reserved, the other blocked: the day has two occupied properties out of two.
    The union is per property, not per source."""
    reservation = a_reservation(check_in=MONDAY, check_out=MONDAY + timedelta(days=1))
    transitions = (
        a_transition(
            to_state=STATE.OUT_OF_SERVICE,
            created_at=datetime(2026, 8, 20, tzinfo=UTC),
            property_id=OTHER_PROPERTY,
        ),
    )

    points = occupancy_series(
        MONDAY, [PROPERTY, OTHER_PROPERTY], [reservation], {OTHER_PROPERTY: transitions}
    )

    assert points[0].occupied_properties == 2
    assert points[0].occupancy_pct == Decimal("100.0")
    assert points[1].occupied_properties == 1


# --- D3's accepted consequence: the end-of-day snapshot ---------------------------------


def test_a_same_day_block_and_release_does_not_surface() -> None:
    """**Design D3, confirmed with the user at the design gate of 2026-09-02.** R2.2 is the
    operational definition of R2.1's "en algún instante de D", not a competing rule: the
    state in effect is the one at the day's last instant. A flat blocked at 09:00 on
    Wednesday and released at 17:00 the same Wednesday is therefore **not** occupied that
    day, because the transition *leaving* the blocked state is also inside the day.

    This is the case the chosen reading gives up on, and it is deliberate — an any-instant
    interval overlap was the rejected alternative. Anyone "fixing" this test is reopening a
    decision, not correcting a bug."""
    transitions = (
        a_transition(to_state=STATE.BLOCKED_BY_OWNER, created_at=datetime(2026, 9, 2, 9, tzinfo=UTC)),
        a_transition(to_state=STATE.VACANT_READY, created_at=datetime(2026, 9, 2, 17, tzinfo=UTC)),
    )

    points = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: transitions})

    assert occupied_days(points) == []


def test_a_block_that_survives_the_day_does_surface() -> None:
    """The other half of the same rule: released at 00:30 the *next* day, so Wednesday ends
    blocked and counts. Same two transitions, eight hours apart — this is what
    `test_a_same_day_block_and_release_does_not_surface` is contrasted against."""
    transitions = (
        a_transition(to_state=STATE.BLOCKED_BY_OWNER, created_at=datetime(2026, 9, 2, 9, tzinfo=UTC)),
        a_transition(to_state=STATE.VACANT_READY, created_at=datetime(2026, 9, 3, 0, 30, tzinfo=UTC)),
    )

    points = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: transitions})

    assert occupied_days(points) == [WEDNESDAY]


def test_a_block_entered_at_the_last_instant_of_the_day_counts_for_that_day() -> None:
    """23:59:59 UTC is inside the day; midnight UTC of the next day is the exclusive end."""
    transitions = (
        a_transition(
            to_state=STATE.BLOCKED_BY_OWNER,
            created_at=datetime(2026, 9, 2, 23, 59, 59, tzinfo=UTC),
        ),
    )

    points = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: transitions})

    assert occupied_days(points) == [MONDAY + timedelta(days=n) for n in (2, 3, 4, 5, 6)]


def test_a_block_entered_at_midnight_utc_belongs_to_the_new_day() -> None:
    """The boundary is half-open, so the instant that starts Thursday is Thursday's, not
    Wednesday's — the same convention section 1's adapter applies to its window end."""
    transitions = (
        a_transition(to_state=STATE.BLOCKED_BY_OWNER, created_at=datetime(2026, 9, 3, tzinfo=UTC)),
    )

    points = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: transitions})

    assert occupied_days(points) == [MONDAY + timedelta(days=n) for n in (3, 4, 5, 6)]


def test_out_of_order_transitions_are_sorted_before_the_walk() -> None:
    """The forward pointer walk is only correct on ordered input, so the function sorts
    defensively by `(created_at, id)` instead of trusting the adapter. Same series either
    way, whatever order the sequence arrives in."""
    block = a_transition(
        to_state=STATE.BLOCKED_BY_OWNER, created_at=datetime(2026, 9, 2, 9, tzinfo=UTC)
    )
    release = a_transition(
        to_state=STATE.VACANT_READY, created_at=datetime(2026, 9, 4, 9, tzinfo=UTC)
    )

    in_order = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: (block, release)})
    reversed_order = occupancy_series(MONDAY, [PROPERTY], [], {PROPERTY: (release, block)})

    assert in_order == reversed_order
    assert occupied_days(in_order) == [WEDNESDAY, MONDAY + timedelta(days=3)]


# --- R1.3, D4: the percentage -----------------------------------------------------------


def test_an_empty_portfolio_gets_a_null_percentage_on_all_seven_days() -> None:
    """R1.3: "IF `total_properties` es cero ... THEN THE SYSTEM SHALL devolver
    `occupancy_pct: null` para los siete días, nunca una división por cero"."""
    points = occupancy_series(MONDAY, [], [], {})

    assert len(points) == 7
    assert all(point.occupancy_pct is None for point in points)
    assert all(point.total_properties == 0 for point in points)
    assert all(point.occupied_properties == 0 for point in points)


def test_an_empty_day_of_a_real_portfolio_is_zero_and_not_null() -> None:
    """`null` means "no denominator", not "nothing occupied": collapsing the two would make
    an empty tenant indistinguishable from a quiet week."""
    points = occupancy_series(MONDAY, [PROPERTY], [], {})

    assert all(point.occupancy_pct == Decimal("0.0") for point in points)


def test_the_percentage_is_quantized_to_one_decimal() -> None:
    """Design D4: `Decimal`, one decimal place. One property in three is `33.3`, not
    `33.33333...`, and not a float."""
    reservation = a_reservation(check_in=MONDAY, check_out=MONDAY + timedelta(days=1))
    third = uuid.UUID("44444444-4444-4444-4444-444444444444")

    points = occupancy_series(MONDAY, [PROPERTY, OTHER_PROPERTY, third], [reservation], {})

    assert points[0].occupancy_pct == Decimal("33.3")
    assert points[0].occupancy_pct is not None
    assert points[0].occupancy_pct.as_tuple().exponent == -1
    assert isinstance(points[0].occupancy_pct, Decimal)


def test_the_percentage_rounds_half_up() -> None:
    """Two of three is `66.666...` → `66.7`, matching `calculator.py`'s `ROUND_HALF_UP`
    rather than `Decimal`'s banker's-rounding default."""
    third = uuid.UUID("44444444-4444-4444-4444-444444444444")
    reservations = [
        a_reservation(check_in=MONDAY, check_out=MONDAY + timedelta(days=1)),
        a_reservation(
            property_id=OTHER_PROPERTY, check_in=MONDAY, check_out=MONDAY + timedelta(days=1)
        ),
    ]

    points = occupancy_series(MONDAY, [PROPERTY, OTHER_PROPERTY, third], reservations, {})

    assert points[0].occupancy_pct == Decimal("66.7")


@pytest.mark.parametrize(
    ("occupied", "expected"),
    [(0, Decimal("0.0")), (1, Decimal("50.0")), (2, Decimal("100.0"))],
)
def test_the_percentage_stays_between_zero_and_one_hundred(
    occupied: int, expected: Decimal
) -> None:
    """R1.3: "un valor numérico entre 0 y 100"."""
    ids = [PROPERTY, OTHER_PROPERTY]
    reservations = [
        a_reservation(property_id=ids[index], check_in=MONDAY, check_out=MONDAY + timedelta(days=1))
        for index in range(occupied)
    ]

    points = occupancy_series(MONDAY, ids, reservations, {})

    assert points[0].occupancy_pct == expected
    assert points[0].occupied_properties == occupied


# --- shape guarantees -------------------------------------------------------------------


def test_a_point_is_immutable() -> None:
    import dataclasses

    point = occupancy_series(MONDAY, [PROPERTY], [], {})[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        point.occupied_properties = 99  # type: ignore[misc]


def test_the_series_does_not_consume_a_generator_of_ids_twice() -> None:
    """Section 3 may well pass a comprehension over the property rows. If the ids were
    iterated once per day, the denominator would come out zero on Tuesday onwards."""
    points = occupancy_series(MONDAY, (id_ for id_ in (PROPERTY, OTHER_PROPERTY)), [], {})

    assert {point.total_properties for point in points} == {2}
