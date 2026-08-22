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


# --- R6: what reporting an incident does, and does not do, to closing the task -------------
#
# `cleaner-incident-report` changes **not one line** of `complete()`. What it adds is a
# surface that creates the very incidents this clause reads, so the coupling stops being
# hypothetical — and the tests below are what keep the two halves of it honest.


def test_the_blocking_message_names_the_cause_and_never_the_incident() -> None:
    """R6.3, behaviourally.

    `CLEANER` does not hold `READ_INCIDENTS`, so the body of this refusal is the one place a
    cleaner could learn something about an incident she may not read. It names the cause — an
    unresolved `CRITICAL` incident — and no identifier, no title and no description.
    """
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)

    with pytest.raises(BlockingIncidentError) as refusal:
        task.complete(CLEANER, _evidence(required={"a"}, completed={"a"}, critical=True), LATER)

    assert str(refusal.value) == (
        "An unresolved CRITICAL incident blocks completing this cleaning"
    )


def test_the_incident_a_cleaner_reports_blocks_her_own_close_only_once_classified() -> None:
    """R6.2 and R6.4 — the whole journey, as declared behaviour rather than as a surprise.

    This is the coupling R6 exists to write down. Three moments:

    1. **She reports.** The incident is born `MEDIUM` (`Incident.severity`'s default — the alta
       sets no severity, R3.2), so at that instant it does not block anything.
    2. **She closes the task.** It succeeds. Reporting a problem does not lock the cleaner out
       of finishing her own work, which is the outcome a cleaner would otherwise learn by
       hitting a `409` she could not explain.
    3. **The classifier raises it to `CRITICAL`.** *Now* the property has an unresolved critical
       incident, and the next `complete()` on that property is refused.

    Run against the real `Incident` entity and the real `CleaningTask`, not a boolean flipped by
    hand: the point is that `MEDIUM`-at-birth and `CRITICAL`-after-classification are the
    entity's own behaviour, and a change to either default would break this rather than pass.
    """
    from decimal import Decimal

    from app.maintenance.domain.entities import Incident
    from app.maintenance.domain.enums import (
        IncidentCategory,
        IncidentSeverity,
        IncidentSource,
        IncidentStatus,
    )
    from app.maintenance.domain.value_objects import IncidentClassification

    property_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # 1. She reports, from a task she is working on.
    incident = Incident(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        source=IncidentSource.CLEANER,
        title="Caldera rota",
        description="No sale agua caliente.",
        created_at=NOW,
        updated_at=NOW,
        reported_by_user_id=CLEANER,
        cleaning_task_id=uuid.uuid4(),
    )
    assert incident.severity is IncidentSeverity.MEDIUM
    assert incident.status is IncidentStatus.OPEN

    # 2. It does not block her own close: the evidence gatherer asks for unresolved *CRITICAL*
    #    incidents, and hers is not one.
    blocking_now = incident.severity is IncidentSeverity.CRITICAL
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)
    task.complete(
        CLEANER, _evidence(required={"a"}, completed={"a"}, critical=blocking_now), LATER
    )
    assert task.status is CleaningTaskStatus.COMPLETED

    # 3. The classifier raises it. Same incident, same property.
    incident.classify(
        IncidentClassification(
            category=IncidentCategory.PLUMBING,
            severity=IncidentSeverity.CRITICAL,
            confidence=Decimal("0.95"),
            summary="Hot water supply failure",
            vocabulary=frozenset({"Hot water supply failure"}),
        ),
        confidence_threshold=Decimal("0.7"),
        adapter="deterministic",
        now=LATER,
    )
    assert incident.severity is IncidentSeverity.CRITICAL

    # The next cleaning of that property cannot be closed while it is unresolved.
    blocking_later = incident.severity is IncidentSeverity.CRITICAL
    next_task = _task(CleaningTaskStatus.IN_PROGRESS, assigned=CLEANER)
    with pytest.raises(BlockingIncidentError) as refusal:
        next_task.complete(
            CLEANER,
            _evidence(required={"a"}, completed={"a"}, critical=blocking_later),
            LATER,
        )

    # **The message and not only the code** (Risks): R2.5's `409`
    # (`InvalidCleaningTransitionError`) and R6.3's arrive through the same `_MAPPING`, so a
    # test asserting the status alone could not tell which refusal it got.
    assert str(refusal.value) == (
        "An unresolved CRITICAL incident blocks completing this cleaning"
    )
    assert next_task.status is CleaningTaskStatus.IN_PROGRESS
