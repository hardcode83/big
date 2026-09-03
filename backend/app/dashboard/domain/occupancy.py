"""Occupied nights over the current calendar week (`dashboard-occupancy-series` R1, R2, D3).

One small rule in its own module, the construction `next_action.py` and `financials.py`
already use: the whole computation is a pure function over dates, so the seven points can be
asserted against hand-built fixtures with no database in the way.

**Two independent checks, unioned — never summed** (R2.1, D3). A day's occupied properties
are a `set` of property ids, so a flat that is both reserved and blocked on the same day
cannot be counted twice; "sin doble conteo" is structural here rather than a subtraction
someone has to remember.

* **Reservation coverage** — `check_in_date <= day < check_out_date` with a `status` outside
  `FREE_STATUSES`. That frozenset is **imported** from `app/pricing/domain/occupancy.py`
  rather than redeclared: R2.1 asks for "el mismo `FREE_STATUSES`", and a second copy would
  be a second definition of what "occupied" means, free to drift.
* **Blocked / out-of-service coverage** — reconstructed from the property's
  `PropertyStateTransition` history (R2.2), *never* from `properties.operational_state`,
  which only knows today.

**The end-of-day snapshot, and what it costs** (D3, confirmed with the user at the design
gate of 2026-09-02). R2.2 is read as the operational definition of R2.1's "estuvo en ... en
algún instante de D", not as a second competing rule: the state "in effect" for day `D` is
the `to_state` of the last transition whose `created_at` is before `D`'s exclusive end
(midnight UTC of `D + 1`). A flat blocked and released again *within the same day* therefore
does **not** surface as occupied — the transition leaving `BLOCKED_BY_OWNER` is inside the
day too, and it is the one in effect at the day's last instant. That is an accepted,
deliberate consequence, and `tests/dashboard/test_occupancy_series.py` pins it explicitly so
nobody "fixes" it by accident.

Days **after** today need no special case: a future day's history is whatever transitions
already exist at or before its end, which carries the current block forward. `today` is used
in exactly one place, `week_bounds`, and `occupancy_series` never sees it.

Pure Python: no pydantic, no sqlalchemy, no I/O. `tests/test_layering.py` enforces it.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.dashboard.domain.read_models import OccupancyPoint
from app.pricing.domain.occupancy import FREE_STATUSES
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState
from app.reservations.domain.entities import Reservation

#: Seven points, one per day of the ISO week (R1.1). Named so the series length and the
#: Sunday offset in `week_bounds` cannot disagree.
DAYS_IN_WEEK = 7

#: The two operational states R2.1 counts as an occupied night on their own, with no
#: reservation involved. Everything else — `VACANT_READY`, `AWAITING_CLEANING`, even
#: `OCCUPIED_ESTIMATED` — is left to the reservation criterion: `OCCUPIED_ESTIMATED` is a
#: *guess* the state machine makes from the calendar this function reads directly, so
#: counting it too would double the calendar's vote and let an estimate outlive the
#: reservation that produced it.
OCCUPYING_STATES: frozenset[PropertyOperationalState] = frozenset(
    {PropertyOperationalState.BLOCKED_BY_OWNER, PropertyOperationalState.OUT_OF_SERVICE}
)

_ONE_DECIMAL = Decimal("0.1")


def week_bounds(today: date) -> tuple[date, date]:
    """Monday and Sunday of `today`'s ISO week, both **inclusive** (R1.1, D3).

    **ASSUMPTION.** Neither the PRD nor the frontend contract defines the series window —
    "current ISO week" is the literal reading of the mockup, decided at the design gate of
    2026-09-02 (D3). Not a rolling 7-day window ending today, and not configurable; a caller
    that wants either of those needs its own function.

    Inclusive on both ends because that is what section 1's `history_for_properties` wants:
    its adapter turns `end` into `datetime.combine(end + timedelta(days=1), time.min)`, so
    Sunday 23:59:59 UTC is inside the window and Monday 00:00 UTC is outside. A caller must
    pass this pair straight through, without pre-converting or adding a day.
    """
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=DAYS_IN_WEEK - 1)


def end_of_day_exclusive(day: date) -> datetime:
    """Midnight UTC of the day *after* `day` — the instant `day` stops.

    The same conversion `SqlAlchemyPropertyStateTransitionRepository.history_for_properties`
    applies to its window end, so "the last instant of day D" here and "the end of the
    adapter's window" there mean the same thing (R2.4).
    """
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)


def occupancy_series(
    week_start: date,
    active_property_ids: Iterable[uuid.UUID],
    reservations: Iterable[Reservation],
    transitions_by_property: Mapping[uuid.UUID, Sequence[PropertyStateTransition]],
) -> tuple[OccupancyPoint, ...]:
    """The seven points of the week beginning `week_start`, Monday to Sunday (R1.1).

    `active_property_ids` is the denominator *and* the filter: a reservation or a transition
    belonging to a property outside it is ignored, so an inactive flat cannot push
    `occupied_properties` above `total_properties`. Duplicates in it are collapsed.

    `transitions_by_property` is **sparse** — it comes from `history_for_properties`, which
    omits a property that has no transition before or during the window rather than mapping
    it to `()`. A missing key and an empty sequence are treated identically: "neither blocked
    nor out of service", which is R2.3 exactly.

    Each sequence is re-`sorted` by `(created_at, id)` here. The adapter already returns them
    that way, so this is defensive rather than corrective: the forward pointer walk below is
    only correct on ordered input, and a hand-built fixture or a future second adapter should
    not be able to make it silently wrong.

    `created_at` must be timezone-aware; the column is `DateTime(timezone=True)` and the
    boundary it is compared against is UTC, so a naive value raises rather than being
    reinterpreted in some local zone.
    """
    days = tuple(week_start + timedelta(days=offset) for offset in range(DAYS_IN_WEEK))
    property_ids = tuple(dict.fromkeys(active_property_ids))
    in_scope = frozenset(property_ids)
    total_properties = len(property_ids)

    occupied: tuple[set[uuid.UUID], ...] = tuple(set() for _ in days)

    for reservation in reservations:
        if reservation.property_id not in in_scope or reservation.status in FREE_STATUSES:
            continue
        for index, day in enumerate(days):
            if reservation.check_in_date <= day < reservation.check_out_date:
                occupied[index].add(reservation.property_id)

    for property_id in property_ids:
        transitions = sorted(
            transitions_by_property.get(property_id, ()),
            key=lambda transition: (transition.created_at, transition.id),
        )
        # One forward pass per property, not one per property and day: the pointer only ever
        # advances, so the whole walk is O(transitions) rather than O(7 x transitions).
        pointer = 0
        state_in_effect: PropertyOperationalState | None = None
        for index, day in enumerate(days):
            boundary = end_of_day_exclusive(day)
            while pointer < len(transitions) and transitions[pointer].created_at < boundary:
                state_in_effect = transitions[pointer].to_state
                pointer += 1
            if state_in_effect in OCCUPYING_STATES:
                occupied[index].add(property_id)

    return tuple(
        OccupancyPoint(
            date=day,
            occupied_properties=len(occupied[index]),
            total_properties=total_properties,
            occupancy_pct=_occupancy_pct(len(occupied[index]), total_properties),
        )
        for index, day in enumerate(days)
    )


def _occupancy_pct(occupied_properties: int, total_properties: int) -> Decimal | None:
    """`occupied / total * 100` to one decimal place, or `None` for an empty portfolio.

    R1.3: a tenant with no active properties gets `null` on all seven days, "nunca una
    división por cero". `ROUND_HALF_UP` matches `app/pricing/domain/calculator.py` rather
    than `Decimal`'s banker's-rounding default.
    """
    if total_properties == 0:
        return None
    percentage = Decimal(occupied_properties) * Decimal(100) / Decimal(total_properties)
    return percentage.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP)
