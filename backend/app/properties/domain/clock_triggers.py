"""Which reservations a clock trigger should consider (`celery-jobs` R3).

Pure policy, no clock of its own: the caller supplies `now`.

**What this module deliberately does NOT do**: decide whether a transition is legal. That
is `PropertyStateMachine`'s job and design D10 rejects re-checking it here ("comprobar el
estado antes de llamar — duplicaría la política fuera de la máquina"). An earlier draft of
this file re-implemented the machine's own `status is CONFIRMED` / `start <= now < end` /
`now >= end` comparisons and decided "not due" without ever consulting it; the two agreed
that day and nothing kept them in sync. The caller now asks the machine about every
reservation and classifies by its verdict.

What is left here is only what the machine cannot answer:

* **the fetch window** — which reservations are even worth loading (design D3);
* **the check-in window** — `TenantConfig.checkin_window_hours_before`, which is the
  operator's choice of *when within the legal day* to fire, not a question of legality
  (design D7);
* **materialising local bounds** — so the caller can tell "this reservation's local time
  cannot exist" apart from "its hour has not come". Both reach the machine as the same
  `IncompatibleTransitionContextError`, and only the first will never fix itself (R3.4).

Note on `ContextualStateResolver._effective_bounds`: reached the same way
`state_machine.py` reaches it — as a module-internal helper of this domain package. Its
DST policy (reject the spring gap, demand an explicit `fold` in the autumn one) is the one
piece of arithmetic that must never be reimplemented.
"""

from datetime import date, datetime, timedelta

from app.properties.domain.entities import Property
from app.properties.domain.state_resolution import ContextualStateResolver
from app.reservations.domain.entities import Reservation

from .exceptions import InvalidTransitionInputError

#: How far **ahead** of `now` to fetch. Two days is not arbitrary: every forward-looking
#: trigger is clamped to the property's local *day* (`opens_checkin_window` below), and no
#: IANA zone is more than 14 hours from UTC, so a reservation that could fire today is
#: always inside 48 hours. Pinned by `test_the_lookahead_covers_every_timezone_offset`.
CANDIDATE_LOOKAHEAD = timedelta(days=2)

#: How far **behind** `now` to fetch, and this one is a real operational limit rather than
#: a derivation. `CHECKOUT_TIME_REACHED` has no day clamp — it fires whenever `now >= end`
#: — so a checkout the scheduler missed stays due indefinitely. With a symmetric two-day
#: window (the first version of this module) a worker outage longer than two days left the
#: property in `OCCUPIED_ESTIMATED` **for ever**, reported as `not_eligible` and therefore
#: indistinguishable from "nothing to do". Thirty days makes the backlog recoverable
#: without an unbounded scan; beyond it the property needs a manual transition, and
#: `docs/celery-jobs.md` says so rather than leaving it to be discovered.
CANDIDATE_LOOKBEHIND = timedelta(days=30)


def candidate_window(now: datetime) -> tuple[date, date]:
    """The date range to fetch reservations for, as `(date_from, date_to)`."""
    return (now - CANDIDATE_LOOKBEHIND).date(), (now + CANDIDATE_LOOKAHEAD).date()


def effective_bounds(
    property: Property, reservation: Reservation
) -> tuple[datetime, datetime]:
    """The stay's start and end as real instants in the property's zone.

    Raises `IncompatibleTransitionContextError` when the local time does not exist (spring
    forward), is ambiguous without an explicit `fold` (autumn), or the checkout is not
    after the check-in. The caller counts those apart from "not due yet" (R3.4).
    """
    return ContextualStateResolver._effective_bounds(property, reservation)


def opens_checkin_window(
    property: Property,
    reservation: Reservation,
    now: datetime,
    checkin_window: timedelta,
) -> bool:
    """Whether the operator's check-in window has opened for this stay (design D7).

    Two conditions, and the second is not redundant. The machine accepts any instant of
    the check-in *date*; the window narrows that to the last `checkin_window` before the
    hour. Without the date clamp, an early check-in with a wide window would look "due"
    the day before — an instant the machine rejects, so the job would ask and be refused
    on every tick for hours.

    The clamp is also what bounds `CANDIDATE_LOOKAHEAD`: a stay whose local date is not
    today cannot fire, however wide the configured window. An operator who sets 100 hours
    does not get a four-day early transition; they get the whole check-in day.

    Guards its own precondition on `now`, like every other value object in this domain:
    this runs *before* `PropertyStateMachine.evaluate` gets a chance to reject a naive
    instant, so without the guard a caller that forgot `tzinfo` would get a bare
    `TypeError` from datetime arithmetic instead of the domain's own error.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise InvalidTransitionInputError("now must be timezone-aware")
    zone = ContextualStateResolver._zone(property)
    start, _ = effective_bounds(property, reservation)
    same_local_day = now.astimezone(zone).date() == start.astimezone(zone).date()
    return same_local_day and now >= start - checkin_window
