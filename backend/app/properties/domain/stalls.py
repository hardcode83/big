"""When the calendar wants a transition the flat's state will not admit (R1, design D1).

The gap this closes, measured in `dev` on 2026-08-22: REDES11 sat in `CLEANING_IN_PROGRESS`
since the 16th with a `CONFIRMED` stay from the 19th to the 23rd, and the check-in never
happened. `AdvancePropertyStatesUseCase` asks for its candidates with
`list_by_state(tenant_id, source_states_for(trigger))`, so a flat whose state is not a source
of the trigger never becomes a candidate at all: it incremented no bucket, `not_eligible`
included. The tick's report was correct and empty of it. **It does not discard the flat, it
never looks at it** — which is why R1 cannot be satisfied by adding a bucket, and why this
module detects the mismatch *outside* the candidate query.

**Three conditions, and the third is what makes this a stall detector.** A mismatch is
`PropertyStateMachine.is_due(request)`, `state not in source_states_for(trigger)`, **and** no
transition already recorded for that `(reservation, trigger)` pair. The first two alone describe
everything *downstream* of the trigger, not what is stuck: `is_due` for `CHECKIN_TIME_REACHED`
holds for the whole stay and for `CHECKOUT_TIME_REACHED` forever after the checkout — they answer
"did that moment arrive", not "is this flat still waiting for it" — while the complement of the
source states contains every state a flat legitimately occupies *after* passing through that same
trigger. Measured on the two-condition version: a flat `OCCUPIED_ESTIMATED` mid-stay and one
`AWAITING_CLEANING` fresh from a checkout were both reported, so the count was the size of the
active portfolio and REDES11 was indistinguishable from a healthy flat (design D1, amended
2026-08-23).

Neither of the first two halves is recomputed here, and that is the point rather than tidiness:
`clock_triggers.py`
records that an earlier draft of *that* module reimplemented the machine's own
`start <= now < end` comparisons, "los dos coincidían aquel día y nada los mantenía en sync".
A second copy of "is it due" living here would be the same bug with a new address.

**One definition, two consumers** (design D1): the clock job counts these into
`AdvanceReport.blocked`, and the queryable collection behind
`GET /api/v1/blocked-transitions` lists them. If each computed its own, the count and the
screen would disagree and nothing would notice.

Pure policy: no I/O, no clock — `now` is the caller's. That is what keeps it in `domain/`
under the dependency rule of `steering/backend-architecture.md`, enforced by
`tests/test_layering.py`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.reservations.domain.entities import Reservation

from .clock_triggers import effective_bounds, opens_checkin_window
from .state_machine import PropertyStateMachine
from .transition_enums import PropertyStateTrigger
from .value_objects import (
    PropertyStateChangeRequest,
    PropertyTransitionContext,
    TransitionActor,
    TransitionEvidenceIds,
)

#: The three triggers a clock fires, in the order `scheduler/tasks.py` schedules them
#: (`check_checkin_windows`, `mark_occupied_estimated`, `process_checkouts`). Only these:
#: `RESERVATION_CANCELLED_BEFORE_CHECKIN` is driven by a cancellation arriving, not by time
#: passing, so a flat cannot be "stuck" waiting for it.
CLOCK_TRIGGERS: tuple[PropertyStateTrigger, ...] = (
    PropertyStateTrigger.CHECKIN_WINDOW_OPENED,
    PropertyStateTrigger.CHECKIN_TIME_REACHED,
    PropertyStateTrigger.CHECKOUT_TIME_REACHED,
)


@dataclass(frozen=True)
class BlockedTransition:
    """One transition the calendar required and the state refused.

    Keyed by `(property_id, reservation_id, trigger)`: a flat with two overlapping stays in
    the window produces two of these, because they are two distinct facts. Collapsing them
    here would hide the second guest. The job's `blocked` bucket counts *properties* and
    does its own collapsing, which it can only do if it is given both.

    `due_since` is the instant the machine considers overdue, so it answers "since when" —
    for REDES11, the 19th of August and not the day someone happened to look.
    """

    property_id: uuid.UUID
    reservation_id: uuid.UUID
    trigger: PropertyStateTrigger
    blocking_state: PropertyOperationalState
    due_since: datetime


def detect(
    property: Property,
    reservations: tuple[Reservation, ...],
    now: datetime,
    checkin_window: timedelta,
    applied: frozenset[tuple[uuid.UUID, str]],
) -> tuple[BlockedTransition, ...]:
    """Every mismatch between what the calendar requires of `property` and what its state admits.

    `applied` is the `(reservation_id, trigger_value)` pairs that already have a transition
    recorded — `PropertyStateTransitionRepository.applied_clock_triggers` produces it. Passed in
    rather than read here so this stays a pure function (design D1); the trigger side is the
    **stored text**, never the enum, so that no read path rebuilds a retired member.
    """
    blocking_state = property.current_operational_state
    found: list[BlockedTransition] = []
    for trigger in CLOCK_TRIGGERS:
        if blocking_state in PropertyStateMachine.source_states_for(trigger):
            # A candidate, not a stall: the job will move it on its next tick.
            continue
        for reservation in reservations:
            if (reservation.id, trigger.value) in applied:
                # This flat already made this transition for this stay, so it is downstream of
                # the trigger rather than stuck before it. Checked first because it is the
                # cheapest of the three and the one that rules out the whole healthy portfolio.
                continue
            # `is_due` FIRST, and the order is a tenant-isolation guarantee rather than a
            # preference. It runs `_validate_request`, which is what raises
            # `TransitionScopeMismatchError` for a reservation belonging to another tenant or
            # another property. `effective_bounds` performs no scope check at all, so calling
            # it first — as the first draft of this module did — meant a foreign reservation
            # that *also* had an unresolvable local time raised
            # `IncompatibleTransitionContextError` from the date arithmetic and got skipped as
            # ordinary bad data, with the scope check never reached. The guard was real only
            # for foreign reservations whose dates happened to parse.
            if not PropertyStateMachine.is_due(_probe(property, reservation, trigger, now)):
                # False also covers the local time that does not exist, is ambiguous without a
                # fold, or the checkout that is not after the check-in: for these three
                # triggers `_validate_trigger_preconditions` materialises the bounds itself and
                # answers `IncompatibleTransitionContextError`, which `is_due` reports as "not
                # due". That is the job's `unresolvable_time` — it needs a person, and it must
                # not abort the sweep for a whole tenant over one broken booking.
                continue
            # Cannot raise here: every member of `CLOCK_TRIGGERS` is a reservation trigger
            # whose preconditions already resolved these same bounds, so `is_due` returning
            # True is proof they materialise. Only reached to report `due_since`.
            start, end = effective_bounds(property, reservation)
            if trigger is PropertyStateTrigger.CHECKIN_WINDOW_OPENED and not opens_checkin_window(
                property, reservation, now, checkin_window
            ):
                # The operator's window, applied for the same reason the job applies it
                # (`clock_triggers.opens_checkin_window`, design D7 of `celery-jobs`): the
                # machine accepts any instant of the check-in *date*, so without this clamp
                # detection would report a stall hours before the job would have fired, and
                # the count and the report would stop describing the same thing.
                continue
            found.append(
                BlockedTransition(
                    property_id=property.id,
                    reservation_id=reservation.id,
                    trigger=trigger,
                    blocking_state=blocking_state,
                    due_since=_due_since(trigger, start, end, checkin_window),
                )
            )
    return tuple(found)


def _due_since(
    trigger: PropertyStateTrigger, start: datetime, end: datetime, checkin_window: timedelta
) -> datetime:
    if trigger is PropertyStateTrigger.CHECKIN_WINDOW_OPENED:
        return start - checkin_window
    if trigger is PropertyStateTrigger.CHECKOUT_TIME_REACHED:
        return end
    return start


def _probe(
    property: Property,
    reservation: Reservation,
    trigger: PropertyStateTrigger,
    now: datetime,
) -> PropertyStateChangeRequest:
    """A request built only to be asked `is_due`, never to be performed.

    The evidence ids are thrown away with it. They are still built here rather than deferred
    because `TransitionEvidenceIds` validates that the two differ, and moving that late would
    take a guarantee out of the request's own construction — the same reasoning
    `AdvancePropertyStatesUseCase._request_for` records.

    The actor is `SYSTEM` because that is who would perform the transition if the state
    allowed it, and `_validate_request` demands an actor whether or not one will act.
    """
    return PropertyStateChangeRequest(
        property=property,
        trigger=trigger,
        context=PropertyTransitionContext(reservations=(reservation,)),
        actor=TransitionActor(triggered_by=StateTransitionTriggeredBy.SYSTEM),
        reference_instant=now,
        evidence_ids=TransitionEvidenceIds(
            transition_id=uuid.uuid4(), timeline_event_id=uuid.uuid4()
        ),
        source_entity_id=reservation.id,
        reservation_id=reservation.id,
    )
