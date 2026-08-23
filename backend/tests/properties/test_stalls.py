"""What `detect` calls a blocked transition (`cleaning-stall-blocks-next-stay` R1, design D1).

One definition of "mismatch" for the job's count and for the queryable collection. If the
two diverged, the report and the screen would count different things and nobody would
notice — which is the failure mode this change exists to end.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.cleaning.domain.entities import CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.exceptions import TransitionScopeMismatchError
from app.properties.domain.stalls import CLOCK_TRIGGERS, BlockedTransition, _probe, detect
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus


NOW = datetime(2026, 8, 22, 8, 18, tzinfo=timezone.utc)
CHECKIN_WINDOW = timedelta(hours=4)

#: No transition has ever been recorded for any stay — the state of a fresh tenant, and the
#: case where the first two conditions carry the whole answer.
NO_EVIDENCE: frozenset[tuple[uuid.UUID, str]] = frozenset()


def already_applied(*pairs):
    """`(reservation, trigger)` pairs as `applied_clock_triggers` returns them.

    The trigger is the **stored text**, matching the port's contract: the enum is deliberately
    never rebuilt from persisted metadata.
    """
    return frozenset((reservation.id, trigger.value) for reservation, trigger in pairs)


def make_property(state=PropertyOperationalState.CLEANING_IN_PROGRESS, *, tz="UTC", tenant_id=None):
    return Property(
        uuid.uuid4(), tenant_id or uuid.uuid4(), "Redes 11", "REDES11", NOW, NOW,
        timezone=tz, current_operational_state=state,
        default_check_in_time=time(15), default_check_out_time=time(11),
    )


def make_reservation(prop, check_in, check_out, *, status=ReservationStatus.CONFIRMED):
    return Reservation(
        uuid.uuid4(), prop.tenant_id, prop.id, ReservationChannel.MANUAL,
        check_in, check_out, (check_out - check_in).days, NOW, NOW, status=status,
    )


def test_the_redes11_case_is_one_blocked_transition():
    """The flat that stalled in `dev` on 2026-08-22, as a value object.

    `CLEANING_IN_PROGRESS` since the 16th; the stay of the 19th to the 23rd never became
    `OCCUPIED_ESTIMATED`. The job's report was correct and empty of it, because a flat whose
    state is not a source of the trigger never becomes a candidate.
    """
    prop = make_property()
    stay = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))

    found = detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE)

    assert found == (
        BlockedTransition(
            property_id=prop.id,
            reservation_id=stay.id,
            trigger=PropertyStateTrigger.CHECKIN_TIME_REACHED,
            blocking_state=PropertyOperationalState.CLEANING_IN_PROGRESS,
            due_since=datetime(2026, 8, 19, 15, tzinfo=timezone.utc),
        ),
    )


def test_the_destination_shortcut_does_not_mask_a_second_stalled_stay():
    """The masking the section-7 panel found and reproduced, refused.

    Two stays are running at once. A's check-in was applied, so the flat sits in
    `OCCUPIED_ESTIMATED` — the destination of `CHECKIN_TIME_REACHED`. B's check-in never happened
    and is genuinely stuck. A first version of the destination short-circuit skipped the whole
    trigger the moment the flat matched the destination, so B vanished from both the job's count
    and the collection: the very bug this change exists to close, reintroduced for overlapping
    stays — which D8 calls "un estado real, no una hipotesis".

    The short-circuit is now scoped to the unambiguous case: with two stays due, the property's
    single state cannot say which one it refers to, so each is judged on its own evidence.
    """
    prop = make_property(PropertyOperationalState.OCCUPIED_ESTIMATED)
    stay_a = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 25))
    stay_b = make_reservation(prop, date(2026, 8, 20), date(2026, 8, 26))

    found = detect(
        prop,
        (stay_a, stay_b),
        NOW,
        CHECKIN_WINDOW,
        already_applied((stay_a, PropertyStateTrigger.CHECKIN_TIME_REACHED)),
    )

    assert [entry.reservation_id for entry in found] == [stay_b.id]
    assert found[0].trigger is PropertyStateTrigger.CHECKIN_TIME_REACHED


def test_a_flat_already_in_the_triggers_destination_is_not_a_stall():
    """R2.4, and the bug only the live run of task 7.5 exposed.

    Cancelling a cleaning moves the flat to `OCCUPIED_ESTIMATED` — exactly where
    `CHECKIN_TIME_REACHED` was taking it — but records a `CLEANING_CANCELLED` transition whose
    source entity is the *task*, with no `reservation_id`. So the `applied` evidence cannot see
    it and, with only the first three conditions, the collection kept reporting a flat that had
    just been fixed. Every unit test missed it because each one simulated the resolution by
    hand-writing a transition row carrying a `reservation_id`, which the real writer never
    writes — the fixture and the real writer disagreed.

    Being in the destination means the calendar's demand is satisfied, however the flat got
    there. That is what R2.4 asks for.
    """
    prop = make_property(PropertyOperationalState.OCCUPIED_ESTIMATED)
    stay = make_reservation(prop, date(2026, 8, 20), date(2026, 8, 25))

    assert PropertyOperationalState.OCCUPIED_ESTIMATED in PropertyStateMachine.destination_states_for(
        PropertyStateTrigger.CHECKIN_TIME_REACHED
    )
    # No evidence at all: the third condition cannot help here, only the fourth.
    assert detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) == ()


def test_a_flat_awaiting_cleaning_after_an_overdue_checkout_is_not_a_stall():
    """The same short-circuit on the trigger whose due-ness never expires."""
    prop = make_property(PropertyOperationalState.AWAITING_CLEANING)
    past = make_reservation(prop, date(2026, 8, 10), date(2026, 8, 14))

    assert PropertyOperationalState.AWAITING_CLEANING in PropertyStateMachine.destination_states_for(
        PropertyStateTrigger.CHECKOUT_TIME_REACHED
    )
    assert detect(prop, (past,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) == ()


def test_every_clock_trigger_has_exactly_one_destination():
    """What makes the destination short-circuit meaningful rather than approximate.

    Each clock trigger leaves a property in exactly one state across all its matrix rows, so
    "already in the destination" is a single, unambiguous check. If a row ever gives one of them a
    second destination, this fails and whoever added it has to decide what the short-circuit
    should mean — rather than it silently becoming a partial test.
    """
    for trigger in CLOCK_TRIGGERS:
        assert len(PropertyStateMachine.destination_states_for(trigger)) == 1, trigger


def test_a_recorded_checkin_stops_a_later_blocking_state_being_a_stall():
    """The evidence condition, on a state that is neither source nor destination.

    `is_due` for `CHECKIN_TIME_REACHED` stays true for the whole stay, and `CLEANING_IN_PROGRESS`
    is neither a source nor the destination — so the first three conditions all hold and only the
    evidence separates two very different situations: a flat whose check-in never happened
    (REDES11, a stall) from one that checked in and later had a cleaning opened mid-stay (not a
    stall — the calendar got what it asked for).
    """
    prop = make_property(PropertyOperationalState.CLEANING_IN_PROGRESS)
    stay = make_reservation(prop, date(2026, 8, 20), date(2026, 8, 25))

    assert PropertyOperationalState.CLEANING_IN_PROGRESS not in PropertyStateMachine.source_states_for(
        PropertyStateTrigger.CHECKIN_TIME_REACHED
    )
    assert PropertyOperationalState.CLEANING_IN_PROGRESS not in PropertyStateMachine.destination_states_for(
        PropertyStateTrigger.CHECKIN_TIME_REACHED
    )
    assert PropertyStateMachine.is_due(
        _probe(prop, stay, PropertyStateTrigger.CHECKIN_TIME_REACHED, NOW)
    ) is True

    assert detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) != ()
    assert detect(
        prop,
        (stay,),
        NOW,
        CHECKIN_WINDOW,
        already_applied((stay, PropertyStateTrigger.CHECKIN_TIME_REACHED)),
    ) == ()


def test_a_recorded_checkout_stops_a_later_blocking_state_being_a_stall():
    """The same, on the trigger whose due-ness never expires.

    `is_due` for `CHECKOUT_TIME_REACHED` is true *forever* after the checkout instant, and
    `MAINTENANCE_REQUIRED` is neither its source nor its destination — so without the evidence
    every flat that ever had a checkout and later took a fault would be reported for as long as
    the 30-day window kept the stay in view.
    """
    prop = make_property(PropertyOperationalState.MAINTENANCE_REQUIRED)
    past = make_reservation(prop, date(2026, 8, 10), date(2026, 8, 14))

    assert detect(prop, (past,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) != ()
    assert detect(
        prop,
        (past,),
        NOW,
        CHECKIN_WINDOW,
        already_applied((past, PropertyStateTrigger.CHECKOUT_TIME_REACHED)),
    ) == ()


def test_evidence_is_per_reservation_not_per_flat():
    """Why `applied` is keyed on the stay: one flat can have applied one check-in and not another.

    Collapsing the evidence to the flat would let a stay that did check in vouch for one that
    never did — hiding exactly the case this change exists to surface.
    """
    prop = make_property()
    stalled = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))
    other = make_reservation(prop, date(2026, 8, 20), date(2026, 8, 24))

    found = detect(
        prop,
        (stalled, other),
        NOW,
        CHECKIN_WINDOW,
        already_applied((other, PropertyStateTrigger.CHECKIN_TIME_REACHED)),
    )

    assert [entry.reservation_id for entry in found] == [stalled.id]


def test_evidence_for_a_different_trigger_does_not_vouch_for_this_one():
    """A recorded window-opening says nothing about whether the check-in ever happened."""
    prop = make_property()
    stay = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))

    found = detect(
        prop,
        (stay,),
        NOW,
        CHECKIN_WINDOW,
        already_applied((stay, PropertyStateTrigger.CHECKIN_WINDOW_OPENED)),
    )

    assert [entry.trigger for entry in found] == [PropertyStateTrigger.CHECKIN_TIME_REACHED]


def test_the_redes11_stall_survives_its_own_window_evidence():
    """REDES11 had its check-in window opened and then stalled — it is still a stall.

    The distinguishing fact is the missing `CHECKIN_TIME_REACHED`, not the absence of all
    history, so evidence of earlier steps must not suppress it.
    """
    prop = make_property()
    stay = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))

    found = detect(
        prop,
        (stay,),
        NOW,
        CHECKIN_WINDOW,
        already_applied(
            (stay, PropertyStateTrigger.CHECKIN_WINDOW_OPENED),
        ),
    )

    assert len(found) == 1
    assert found[0].trigger is PropertyStateTrigger.CHECKIN_TIME_REACHED
    assert found[0].blocking_state is PropertyOperationalState.CLEANING_IN_PROGRESS


@pytest.mark.parametrize(
    "state",
    [PropertyOperationalState.OUT_OF_SERVICE, PropertyOperationalState.BLOCKED_BY_OWNER],
    ids=lambda s: s.value,
)
def test_a_deliberately_offline_flat_with_a_due_stay_is_still_reported(state):
    """Pinned because it is a decision, not an accident (raised by the section-3 panel).

    Someone took the flat out of circulation and left a confirmed stay on it whose hour has come.
    That is a booking nobody can fulfil, so it is reported — but it also means retiring a flat
    *without cancelling its reservations* produces warnings until they are cancelled.
    `docs/celery-jobs.md` says so out loud rather than letting an operator discover it.
    """
    prop = make_property(state)
    stay = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))

    found = detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE)

    assert [entry.blocking_state for entry in found] == [state]


def test_a_property_in_a_source_state_produces_nothing():
    """Half of the definition: a candidate is not a stall, however overdue it looks.

    `AWAITING_CHECKIN` *is* a source of `CHECKIN_TIME_REACHED`, so the job will move this
    flat on its next tick. Reporting it would turn the collection into a list of pending
    work instead of a list of things that cannot proceed.
    """
    prop = make_property(PropertyOperationalState.AWAITING_CHECKIN)
    stay = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))

    assert PropertyOperationalState.AWAITING_CHECKIN in PropertyStateMachine.source_states_for(
        PropertyStateTrigger.CHECKIN_TIME_REACHED
    )
    assert detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) == ()


def test_an_hour_that_has_not_come_produces_nothing():
    """The other half: blocked means due *and* refused, not merely refused."""
    prop = make_property()
    future = make_reservation(prop, date(2026, 9, 10), date(2026, 9, 14))

    assert detect(prop, (future,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) == ()


def test_two_overlapping_stays_are_two_entries_keyed_by_reservation():
    """The double-count risk the design names, made explicit rather than hoped away.

    Two overlapping stays on one flat are two distinct facts, and the value object's key is
    `(property_id, reservation_id, trigger)`. What must not double-count is the *job's*
    `blocked` bucket, which counts properties — that is task 3.2's problem, and it can only
    solve it if `detect` hands it both entries here.
    """
    prop = make_property()
    first = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))
    second = make_reservation(prop, date(2026, 8, 20), date(2026, 8, 24))

    found = detect(prop, (first, second), NOW, CHECKIN_WINDOW, NO_EVIDENCE)

    assert len(found) == 2
    assert {entry.reservation_id for entry in found} == {first.id, second.id}
    assert len({(e.property_id, e.reservation_id, e.trigger) for e in found}) == 2


def test_a_cancelled_stay_is_not_due():
    prop = make_property()
    cancelled = make_reservation(
        prop, date(2026, 8, 19), date(2026, 8, 23), status=ReservationStatus.CANCELLED
    )

    assert detect(prop, (cancelled,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) == ()


def test_an_overdue_checkout_on_a_blocked_state_is_reported_with_its_own_trigger():
    """`CHECKOUT_TIME_REACHED` has no day clamp, so this is the trigger that stays due."""
    prop = make_property(PropertyOperationalState.MAINTENANCE_REQUIRED)
    past = make_reservation(prop, date(2026, 8, 10), date(2026, 8, 14))

    found = detect(prop, (past,), NOW, CHECKIN_WINDOW, NO_EVIDENCE)

    assert [entry.trigger for entry in found] == [PropertyStateTrigger.CHECKOUT_TIME_REACHED]
    assert found[0].due_since == datetime(2026, 8, 14, 11, tzinfo=timezone.utc)
    assert found[0].blocking_state is PropertyOperationalState.MAINTENANCE_REQUIRED


def test_an_unresolvable_local_time_is_skipped_rather_than_raising():
    """A stay whose local time does not exist is the job's `unresolvable_time`, not a stall.

    Letting `IncompatibleTransitionContextError` escape would make one broken booking abort
    the detection sweep for an entire tenant. Since the scope-ordering fix this is answered
    inside `is_due` — `_validate_trigger_preconditions` materialises the bounds and reports
    the gap as "not due" — rather than by a `try` around `effective_bounds` in `detect`.
    """
    prop = make_property(tz="Europe/Madrid")
    prop.default_check_in_time = time(2, 30)
    gap = make_reservation(prop, date(2026, 3, 29), date(2026, 4, 2))

    assert detect(prop, (gap,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) == ()


@pytest.mark.parametrize("trigger", CLOCK_TRIGGERS, ids=lambda t: t.value)
def test_every_clock_trigger_materialises_the_bounds_inside_is_due(trigger):
    """The invariant that lets `detect` call `effective_bounds` without a guard.

    `detect` reads `start, end` only *after* `is_due` said True, and does not wrap that call:
    an uncaught `IncompatibleTransitionContextError` there would abort a whole tenant's sweep.
    What makes it safe is that `_validate_trigger_preconditions` materialises the very same
    bounds for every one of these triggers, so an unresolvable local time is already answered
    as "not due". Asserted per trigger rather than trusted, because a fourth member added to
    `CLOCK_TRIGGERS` without a matching branch there would break it silently — the section-2
    panel asked what would enforce this, and this is the answer.
    """
    prop = make_property(tz="Europe/Madrid")
    prop.default_check_in_time = time(2, 30)  # does not exist: spring-forward gap
    gap = make_reservation(prop, date(2026, 3, 29), date(2026, 4, 2))

    assert PropertyStateMachine.is_due(_probe(prop, gap, trigger, NOW)) is False


def test_no_state_skips_the_reservation_loop_of_every_clock_trigger():
    """Why the scope check in `detect` is always reachable.

    `detect` skips a trigger's reservation loop when the flat's state is one of that trigger's
    **source** states. If some state did that for **all three**, no reservation would ever be
    examined, and a foreign one would leave as an empty result instead of a
    `TransitionScopeMismatchError` — rule 1 of `steering/security.md` turned back into the silent
    under-report this module exists to prevent.

    **Asserted over source union destination**, widened after the section-7 panel: the destination
    short-circuit added a second way to skip a stay. It now lives *inside* the loop, so it can no
    longer skip the scope check at all — but pinning the union keeps this guard true of the whole
    skip surface rather than of the half it originally covered. Both reviewers raised it, and the
    union is what a future `_POLICY` edit could close.
    """
    for state in PropertyOperationalState:
        answering = [
            t
            for t in CLOCK_TRIGGERS
            if state
            in PropertyStateMachine.source_states_for(t)
            | PropertyStateMachine.destination_states_for(t)
        ]
        assert len(answering) < len(CLOCK_TRIGGERS), state


def test_detect_does_not_reach_for_a_clock_of_its_own():
    """`now` is the caller's, so the same instant always yields the same answer."""
    prop = make_property()
    stay = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))

    assert detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE) == detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE)


@pytest.mark.parametrize("foreign", ["tenant", "property"])
def test_a_foreign_reservation_is_refused_and_not_silently_dropped(foreign):
    """Rule 1 of `steering/security.md`: a scope mismatch is a bug, not an absence.

    `detect` feeds `PropertyStateMachine.is_due`, whose `TransitionScopeMismatchError`
    escapes on purpose. Swallowing it here would make a foreign context read as "no stall" —
    an under-report that looks exactly like a healthy tenant.

    Both halves of the check, because they are separate branches of `_validate_request`: a
    regression that dropped only the `property_id` comparison would let one flat's detection
    consume another flat's stay within the same tenant.
    """
    prop = make_property()
    tenant_id = uuid.uuid4() if foreign == "tenant" else prop.tenant_id
    property_id = prop.id if foreign == "tenant" else uuid.uuid4()
    intruder = Reservation(
        uuid.uuid4(), tenant_id, property_id, ReservationChannel.MANUAL,
        date(2026, 8, 19), date(2026, 8, 23), 4, NOW, NOW,
    )

    with pytest.raises(TransitionScopeMismatchError):
        detect(prop, (intruder,), NOW, CHECKIN_WINDOW, NO_EVIDENCE)


@pytest.mark.parametrize("foreign", ["tenant", "property"])
def test_an_unresolvable_date_cannot_shadow_a_scope_violation(foreign):
    """The regression test for the ordering bug the section-2 panel found.

    `effective_bounds` performs no scope check. While `detect` called it *before* `is_due`,
    a foreign reservation that also had an unresolvable local time raised
    `IncompatibleTransitionContextError` from the date arithmetic and was skipped as ordinary
    bad data — so the isolation guard held only for foreign reservations whose dates happened
    to parse. Same intruder as above, now carrying a spring-forward gap: it must still be
    refused, not silently dropped.
    """
    prop = make_property(tz="Europe/Madrid")
    prop.default_check_in_time = time(2, 30)
    tenant_id = uuid.uuid4() if foreign == "tenant" else prop.tenant_id
    property_id = prop.id if foreign == "tenant" else uuid.uuid4()
    intruder = Reservation(
        uuid.uuid4(), tenant_id, property_id, ReservationChannel.MANUAL,
        date(2026, 3, 29), date(2026, 4, 2), 4, NOW, NOW,
    )

    with pytest.raises(TransitionScopeMismatchError):
        detect(prop, (intruder,), NOW, CHECKIN_WINDOW, NO_EVIDENCE)


def test_the_operator_window_gates_the_checkin_window_trigger():
    """The one place `detect` layers a condition on top of `is_due`, and both its sides.

    The machine accepts any instant of the check-in *date*, while the job narrows that to the
    last `checkin_window` before the hour (`clock_triggers.opens_checkin_window`). `detect`
    applies the same clamp, because D1 promises the count and the screen share one definition
    of "mismatch": without it detection would report a stall hours before the job would have
    fired. Amended into design D2 after the section-2 panel called the two-question formula
    incomplete.
    """
    prop = make_property()
    same_day = make_reservation(prop, date(2026, 8, 22), date(2026, 8, 26))
    opens_at = datetime(2026, 8, 22, 11, tzinfo=timezone.utc)  # 15:00 check-in minus 4h

    assert PropertyOperationalState.CLEANING_IN_PROGRESS not in PropertyStateMachine.source_states_for(
        PropertyStateTrigger.CHECKIN_WINDOW_OPENED
    )
    assert detect(prop, (same_day,), opens_at - timedelta(minutes=1), CHECKIN_WINDOW, NO_EVIDENCE) == ()

    found = detect(prop, (same_day,), opens_at, CHECKIN_WINDOW, NO_EVIDENCE)
    assert found == (
        BlockedTransition(
            property_id=prop.id,
            reservation_id=same_day.id,
            trigger=PropertyStateTrigger.CHECKIN_WINDOW_OPENED,
            blocking_state=PropertyOperationalState.CLEANING_IN_PROGRESS,
            due_since=opens_at,
        ),
    )


def test_the_blocking_state_is_whatever_the_flat_is_actually_in():
    prop = make_property(PropertyOperationalState.CLEANING_SCHEDULED)
    stay = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))

    found = detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE)

    assert found[0].blocking_state is PropertyOperationalState.CLEANING_SCHEDULED


def test_cleaning_tasks_are_not_part_of_the_question():
    """`detect` reads the flat's state and its stays, and nothing else.

    A live cleaning task is why the flat is stuck, not evidence of the stall — the state
    already carries that. Taking tasks as input would give `detect` a second opinion about
    something `current_operational_state` settles.
    """
    prop = make_property()
    stay = make_reservation(prop, date(2026, 8, 19), date(2026, 8, 23))
    task = CleaningTask(uuid.uuid4(), prop.tenant_id, prop.id, uuid.uuid4(), NOW, NOW, status=CleaningTaskStatus.IN_PROGRESS)

    assert task.status is CleaningTaskStatus.IN_PROGRESS
    assert len(detect(prop, (stay,), NOW, CHECKIN_WINDOW, NO_EVIDENCE)) == 1
