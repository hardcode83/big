"""R3.4-R3.7, R5.1-R5.3, R5.5 — the invariants of `CleaningTask`, in the entity.

`steering/backend-architecture.md` uses `CleaningTask.complete()` as its worked example of
"entidad con invariante real", and `steering/testing.md` requires TDD for the cleaning
checklist. Pure Python: no repository, no session, no mocks.

The status × method matrix is exhaustive on purpose — DoD §28.19 asks for the invalid
transitions to be tested too, and this is the task-level equivalent of that rule.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.cleaning.domain.entities import LIVE_STATUSES, CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.cleaning.domain.exceptions import (
    TASK_NOT_FOUND_MESSAGE,
    BlockingIncidentError,
    ChecklistIncompleteError,
    CleaningTaskNotFoundError,
    InvalidCleaningTransitionError,
    PhotosIncompleteError,
)
from app.cleaning.domain.value_objects import CleaningCompletionEvidence

NOW = datetime(2026, 8, 6, 11, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
CLEANER = uuid.uuid4()
OTHER_CLEANER = uuid.uuid4()


def _task(status=CleaningTaskStatus.CREATED, assigned=None):
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        checklist_template_id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        status=status,
        assigned_cleaner_id=assigned,
    )


def _evidence(
    required=(), completed=(), critical=False, required_photos=(), uploaded_photos=()
):
    return CleaningCompletionEvidence(
        required_item_ids=frozenset(required),
        completed_item_ids=frozenset(completed),
        has_unresolved_critical_incident=critical,
        required_photo_types=frozenset(required_photos),
        uploaded_photo_types=frozenset(uploaded_photos),
    )


# --- assign -----------------------------------------------------------------------

def test_assign_from_created():
    task = _task()

    task.assign(CLEANER, LATER)

    assert task.status is CleaningTaskStatus.ASSIGNED
    assert task.assigned_cleaner_id == CLEANER
    assert task.updated_at == LATER


def test_reassign_before_acceptance_is_allowed():
    task = _task(CleaningTaskStatus.ASSIGNED, assigned=CLEANER)

    task.assign(OTHER_CLEANER, LATER)

    assert task.assigned_cleaner_id == OTHER_CLEANER


@pytest.mark.parametrize(
    "status",
    [
        CleaningTaskStatus.ACCEPTED,
        CleaningTaskStatus.IN_PROGRESS,
        CleaningTaskStatus.REJECTED,
        CleaningTaskStatus.COMPLETED,
        CleaningTaskStatus.CANCELLED,
        CleaningTaskStatus.FAILED,
        CleaningTaskStatus.PENDING_REVIEW,
    ],
)
def test_assign_is_refused_from_every_other_status(status):
    with pytest.raises(InvalidCleaningTransitionError):
        _task(status, assigned=CLEANER).assign(OTHER_CLEANER, LATER)


# --- accept / reject / start ------------------------------------------------------

def test_accept_by_the_assigned_cleaner():
    task = _task(CleaningTaskStatus.ASSIGNED, assigned=CLEANER)

    task.accept(CLEANER, LATER)

    assert task.status is CleaningTaskStatus.ACCEPTED
    assert task.accepted_at == LATER


@pytest.mark.parametrize("operation", ["accept", "reject", "start", "complete"])
def test_an_unassigned_task_is_invisible_to_every_cleaner(operation):
    """R7.2/R7.3 on the shape a checkout actually leaves: `assigned_cleaner_id IS NULL`.

    The QA reviewer of `/sdd:review` found this path implemented and deliberate but never
    asserted — the only place it was exercised was the authorisation matrix, which checked
    `!= 403` and so passed on any code at all. An unassigned task belongs to nobody, so for
    every cleaner it must be indistinguishable from one that does not exist.
    """
    task = _task(CleaningTaskStatus.CREATED, assigned=None)
    args = (CLEANER, _evidence(), LATER) if operation == "complete" else (CLEANER, LATER)

    with pytest.raises(CleaningTaskNotFoundError) as raised:
        getattr(task, operation)(*args)

    assert str(raised.value) == TASK_NOT_FOUND_MESSAGE


@pytest.mark.parametrize("operation", ["accept", "reject", "start"])
def test_someone_elses_task_is_indistinguishable_from_a_missing_one(operation):
    """R7.2, R7.3 — 404, not 409, and the status must not leak.

    Found by the security panel of section 1: the guard used to raise a transition error
    whose message names the current status, and it ran *after* the status check, so an
    unrelated cleaner learned both that the task exists and what it is doing.
    """
    task = _task(CleaningTaskStatus.ACCEPTED, assigned=CLEANER)

    with pytest.raises(CleaningTaskNotFoundError) as raised:
        getattr(task, operation)(OTHER_CLEANER, LATER)

    # Byte-identical to what an unknown id produces — not merely "does not mention the
    # status". Two 404s with different bodies are the same probe one layer down.
    assert str(raised.value) == TASK_NOT_FOUND_MESSAGE
    assert str(raised.value) == str(CleaningTaskNotFoundError())
    assert str(task.id) not in str(raised.value)


@pytest.mark.parametrize(
    "status",
    [s for s in CleaningTaskStatus if s is not CleaningTaskStatus.ASSIGNED],
)
def test_accept_is_refused_from_every_other_status(status):
    with pytest.raises(InvalidCleaningTransitionError):
        _task(status, assigned=CLEANER).accept(CLEANER, LATER)


@pytest.mark.parametrize(
    "status", [CleaningTaskStatus.ASSIGNED, CleaningTaskStatus.ACCEPTED]
)
def test_reject_keeps_the_rejecter_on_the_row(status):
    """Design D3: that column IS the record of who rejected; the replacement task is
    what frees the slot."""
    task = _task(status, assigned=CLEANER)

    task.reject(CLEANER, LATER)

    assert task.status is CleaningTaskStatus.REJECTED
    assert task.assigned_cleaner_id == CLEANER


@pytest.mark.parametrize(
    "status",
    [
        s
        for s in CleaningTaskStatus
        if s not in (CleaningTaskStatus.ASSIGNED, CleaningTaskStatus.ACCEPTED)
    ],
)
def test_reject_is_refused_from_every_other_status(status):
    with pytest.raises(InvalidCleaningTransitionError):
        _task(status, assigned=CLEANER).reject(CLEANER, LATER)


@pytest.mark.parametrize(
    "status", [s for s in CleaningTaskStatus if s is not CleaningTaskStatus.ACCEPTED]
)
def test_start_is_refused_from_every_other_status(status):
    with pytest.raises(InvalidCleaningTransitionError):
        _task(status, assigned=CLEANER).start(CLEANER, LATER)


@pytest.mark.parametrize(
    "status", [s for s in CleaningTaskStatus if s is not CleaningTaskStatus.COMPLETED]
)
def test_manual_validation_is_refused_from_every_other_status(status):
    with pytest.raises(InvalidCleaningTransitionError):
        _task(status, assigned=CLEANER).record_manual_validation(
            validator_user_id=uuid.uuid4(),
            status=CleaningValidationStatus.PASSED,
            now=LATER,
        )


def test_a_rejected_task_is_terminal():
    task = _task(CleaningTaskStatus.REJECTED, assigned=CLEANER)

    for operation in (
        lambda: task.assign(OTHER_CLEANER, LATER),
        lambda: task.accept(CLEANER, LATER),
        lambda: task.reject(CLEANER, LATER),
        lambda: task.start(CLEANER, LATER),
        lambda: task.complete(CLEANER, _evidence(), LATER),
    ):
        with pytest.raises(InvalidCleaningTransitionError):
            operation()


def test_start_from_accepted():
    task = _task(CleaningTaskStatus.ACCEPTED, assigned=CLEANER)

    task.start(CLEANER, LATER)

    assert task.status is CleaningTaskStatus.IN_PROGRESS
    assert task.started_at == LATER


def test_start_before_accepting_is_refused():
    """PRD §11's flow is accept → start; skipping the acceptance loses the SLA answer."""
    task = _task(CleaningTaskStatus.ASSIGNED, assigned=CLEANER)

    with pytest.raises(InvalidCleaningTransitionError):
        task.start(CLEANER, LATER)


def test_pending_is_not_a_verdict_from_the_only_valid_status():
    """Pinned separately from the status matrix: `COMPLETED` is the one status where the
    method is otherwise legal, so this is the only place the verdict check is reachable."""
    task = _task(CleaningTaskStatus.COMPLETED, assigned=CLEANER)

    with pytest.raises(InvalidCleaningTransitionError):
        task.record_manual_validation(
            validator_user_id=uuid.uuid4(),
            status=CleaningValidationStatus.PENDING,
            now=LATER,
        )


# --- complete: PRD §11's validation rule ------------------------------------------

def test_completing_someone_elses_task_is_a_404_too():
    """The guard `complete` was missing until the security panel of `/sdd:review`.

    It was the only lifecycle method without it, which made the one operation that actually
    closes the work the one with no second layer behind the use case's filter.
    """
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    with pytest.raises(CleaningTaskNotFoundError) as raised:
        task.complete(OTHER_CLEANER, _evidence(), LATER)

    assert str(raised.value) == TASK_NOT_FOUND_MESSAGE
    assert task.status is CleaningTaskStatus.IN_PROGRESS


def test_complete_with_every_required_item_done():
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    task.complete(CLEANER, _evidence(required={"a"}, completed={"a", "b"}), LATER)

    assert task.status is CleaningTaskStatus.COMPLETED
    assert task.completed_at == LATER
    assert task.validation_status is CleaningValidationStatus.PASSED


def test_complete_enumerates_the_missing_required_items():
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    with pytest.raises(ChecklistIncompleteError) as raised:
        task.complete(CLEANER, _evidence(required={"a", "b"}, completed={"b"}), LATER)

    assert raised.value.missing_item_ids == ("a",)
    assert task.status is CleaningTaskStatus.IN_PROGRESS


def test_optional_items_do_not_block_completion():
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    task.complete(CLEANER, _evidence(required=set(), completed=set()), LATER)

    assert task.status is CleaningTaskStatus.COMPLETED


def test_an_unresolved_critical_incident_blocks_completion():
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    with pytest.raises(BlockingIncidentError):
        task.complete(CLEANER, _evidence(required={"a"}, completed={"a"}, critical=True), LATER)

    assert task.status is CleaningTaskStatus.IN_PROGRESS


# --- complete: the third clause, the one `cleaning-photos-storage` brings (R4) -----
#
# `test_completion_does_not_yet_require_photos` used to sit here, pinning the *gap* so it was
# visible in the suite and not only in the proposal, and saying in its own docstring that the
# change closing the gap is the one that has to change it. This is that change, and these are
# the tests that replaced it.


def test_a_missing_required_photo_blocks_completion_and_says_which():
    """R4.1, R4.2, R4.4 — the red test of task 5.1, written before the entity knew the rule.

    Enumerating is half the requirement: "you cannot finish" without saying what is left is an
    answer a cleaner standing in the flat cannot act on, which is exactly why
    `ChecklistIncompleteError` carries its ids. The order is asserted because R4.4 asks for a
    stable one — `frozenset` iteration order is not, so a body built straight from the set
    difference would differ between runs and between processes.
    """
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    with pytest.raises(PhotosIncompleteError) as raised:
        task.complete(
            CLEANER,
            _evidence(required_photos={"kitchen", "bathroom"}, uploaded_photos={"kitchen"}),
            LATER,
        )

    assert raised.value.missing_photo_types == ("bathroom",)
    assert task.status is CleaningTaskStatus.IN_PROGRESS
    assert task.completed_at is None


def test_the_missing_photo_types_come_out_sorted():
    """R4.4 — same guarantee `missing_required_item_ids` gives, and for the same reason."""
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    with pytest.raises(PhotosIncompleteError) as raised:
        task.complete(
            CLEANER,
            _evidence(required_photos={"kitchen", "bathroom", "bedroom", "living"}),
            LATER,
        )

    assert raised.value.missing_photo_types == ("bathroom", "bedroom", "kitchen", "living")


def test_completion_is_allowed_once_every_required_photo_is_there():
    """R4.1 — "at least one per required type", so extra types and extra photos are fine.

    `uploaded_photos` is a set of *types*, not of photos: R2.6 admits several shots of the same
    room on purpose, and the rule never counts them.
    """
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    task.complete(
        CLEANER,
        _evidence(
            required_photos={"kitchen", "bathroom"},
            uploaded_photos={"kitchen", "bathroom", "balcony"},
        ),
        LATER,
    )

    assert task.status is CleaningTaskStatus.COMPLETED


def test_a_template_that_requires_no_photo_closes_without_any():
    """**R4.5, and it is the criterion most likely to be broken by a well-meaning edit.**

    The rule is "the required ones", not "some". A template whose `required_photos` are all
    `required: false` — or that declares none at all — must still close with zero photos
    uploaded, exactly as a checklist with no required item does. Turning the condition into
    "any photo at all" would pass every other test in this section and break this one.
    """
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    task.complete(CLEANER, _evidence(required_photos=set(), uploaded_photos=set()), LATER)

    assert task.status is CleaningTaskStatus.COMPLETED


def test_the_items_clause_is_checked_before_the_photos_one():
    """Task 5.3's ordering, and it is observable: which error comes out when both are unmet.

    Not cosmetic. The checklist is what the cleaner works through first, so reporting the open
    items before the missing photos matches the order the work happens in — and an ordering
    nothing asserts is an ordering the next refactor is free to invert.
    """
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    with pytest.raises(ChecklistIncompleteError):
        task.complete(
            CLEANER, _evidence(required={"a"}, required_photos={"kitchen"}), LATER
        )


def test_the_photos_clause_is_checked_before_the_critical_incident_one():
    """The other half of task 5.3's ordering: photos, then the blocking incident."""
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    with pytest.raises(PhotosIncompleteError):
        task.complete(
            CLEANER, _evidence(required_photos={"kitchen"}, critical=True), LATER
        )


@pytest.mark.parametrize(
    "status", [s for s in CleaningTaskStatus if s is not CleaningTaskStatus.IN_PROGRESS]
)
def test_complete_is_refused_from_every_other_status(status):
    with pytest.raises(InvalidCleaningTransitionError):
        _task(status, assigned=CLEANER).complete(CLEANER, _evidence(), LATER)


# --- manual validation ------------------------------------------------------------

def test_manual_validation_records_who_and_when():
    task = _task(CleaningTaskStatus.COMPLETED, assigned=CLEANER)
    manager = uuid.uuid4()

    task.record_manual_validation(
        validator_user_id=manager, status=CleaningValidationStatus.WAIVED, now=LATER
    )

    assert task.validation_status is CleaningValidationStatus.WAIVED
    assert task.validated_by_user_id == manager
    assert task.validated_at == LATER


# --- LIVE_STATUSES ----------------------------------------------------------------

def test_live_statuses_match_what_the_resolver_treats_as_pending_cleaning():
    """The partial index of design D2 and `ContextualStateResolver` must agree.

    If someone adds a status to one and not the other, a property can end up with a task
    the resolver counts and the index does not (or the reverse), which is how
    `AWAITING_CLEANING` became terminal in the first place.

    The resolver inlines its statuses in `_contextual_reservation_cleaning`
    (`app/properties/domain/state_resolution.py:143-147`) rather than exposing a set, so
    the correspondence is pinned here by enumeration.
    """
    assert LIVE_STATUSES == {
        CleaningTaskStatus.CREATED,
        CleaningTaskStatus.ASSIGNED,
        CleaningTaskStatus.ACCEPTED,
        CleaningTaskStatus.IN_PROGRESS,
    }


def test_pending_review_is_deliberately_not_live():
    """The resolver does not count it, so neither does the index (design D2).

    Nothing in this change produces `PENDING_REVIEW` — `complete()` goes straight to
    `COMPLETED`. Whoever gives it a writer has to decide both sides at once, and this
    assertion plus `test_live_task_index.py` is what forces that.
    """
    assert CleaningTaskStatus.PENDING_REVIEW not in LIVE_STATUSES


def test_is_live_reflects_the_status():
    assert _task(CleaningTaskStatus.ASSIGNED).is_live
    assert not _task(CleaningTaskStatus.REJECTED).is_live


# --- `cancel` (`cleaning-stall-blocks-next-stay` R3.1, R3.4, design D9) --------------------


@pytest.mark.parametrize("status", sorted(LIVE_STATUSES, key=lambda s: s.value))
def test_a_live_task_can_be_cancelled(status) -> None:
    """R3.1: exactly `LIVE_STATUSES`, which is the set that means "this stay is being handled".

    Parametrized over the set itself rather than a literal list, so a status added to
    `LIVE_STATUSES` is covered the day it is added — and one removed stops being asserted.
    """
    task = _task(status, assigned=CLEANER)

    task.cancel(LATER, reason="the cleaner never came back")

    assert task.status is CleaningTaskStatus.CANCELLED
    assert task.updated_at == LATER


@pytest.mark.parametrize(
    "status",
    sorted(set(CleaningTaskStatus) - set(LIVE_STATUSES), key=lambda s: s.value),
)
def test_a_task_that_is_not_live_cannot_be_cancelled(status) -> None:
    """R3.4, and the divergence D9 declares from its wording.

    R3.4 says "IF la tarea ya está en un estado terminal", and `PENDING_REVIEW` is refused too
    although it is not terminal: nothing writes it (`complete()` goes straight to `COMPLETED`)
    and a task that reached it has already resolved the property's state, so there is nothing to
    unstick. The complement of `LIVE_STATUSES` is the honest way to say that, and it is derived
    here rather than listed so the two sets cannot drift.
    """
    task = _task(status, assigned=CLEANER)

    with pytest.raises(InvalidCleaningTransitionError) as raised:
        task.cancel(LATER, reason="too late")

    # D9: "el `409` lleva el estado en el mensaje" — a manager who raced someone else needs to
    # know what the task is now, not merely that they lost.
    assert status.value in str(raised.value)
    assert task.status is status


def test_cancelling_keeps_the_record_of_who_had_it() -> None:
    """Same reasoning `reject` records: the assignee column is the evidence of who held it."""
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    task.cancel(LATER, reason="abandoned")

    assert task.assigned_cleaner_id == CLEANER


def test_cancelling_does_not_pretend_the_cleaning_finished() -> None:
    """`completed_at` and the validation verdict stay untouched: nothing was completed."""
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    task.cancel(LATER, reason="abandoned")

    assert task.completed_at is None
    assert task.validation_status is CleaningValidationStatus.PENDING
    assert task.validated_by_user_id is None


def test_cancel_is_not_an_assignee_operation() -> None:
    """A manager retires someone else's task, so there is no `cleaner_id` to match (R3.1).

    Deliberately unlike `accept`/`reject`/`start`/`complete`, which all call
    `_require_assignee`: those are the cleaner's own acts. The permission for this one is
    `MANAGE_CLEANING_TASKS` at the route, and the entity takes no actor — pinned so that
    "no assignee guard" reads as a decision rather than an omission.
    """
    task = _task(CleaningTaskStatus.ACCEPTED, assigned=OTHER_CLEANER)

    task.cancel(LATER, reason="the guest is still in the flat")

    assert task.status is CleaningTaskStatus.CANCELLED


def test_cancel_requires_a_reason() -> None:
    """`reason` is not optional, and the machine is not what makes it so.

    `CLEANING_CANCELLED` is not in `PropertyStateMachine`'s `manual` set, so nothing downstream
    demands one. Retiring another person's work is exactly what an `AuditLog` has to be able to
    explain six months later (*Data & interfaces*), so the entity refuses a blank.
    """
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    for blank in ("", "   "):
        with pytest.raises(InvalidCleaningTransitionError):
            task.cancel(LATER, reason=blank)

    assert task.status is CleaningTaskStatus.IN_PROGRESS
