"""R3.1, R3.2 — PRD §11's auto-assignment rule, as a pure function.

Extracted from `ProvisionCleaningTaskUseCase` after the architecture panel of section 4:
the policy is now testable without a tenant, a roster or a session, which is the point of
keeping rules in `domain/`.

`cleaning-assign-preconditions` adds the second policy of the same module, `assignment_blocker`
(its R3.1/R3.3, design D4): whether a task can be assigned *right now*, and if not, which of
the two parties is refusing. Written test-first because `steering/testing.md` requires TDD in
`domain/` for a real invariant, and this one is real — the whole change exists because the
system attributed the property's refusal to the task.
"""

import inspect
import uuid
from datetime import UTC, datetime

import pytest

from app.cleaning.domain import assignment as assignment_module
from app.cleaning.domain.assignment import assignment_blocker, resolve_auto_assignee
from app.cleaning.domain.entities import CleaningTask
from app.cleaning.domain.enums import CleaningAssignmentBlocker, CleaningTaskStatus
from app.cleaning.domain.exceptions import InvalidCleaningTransitionError
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger

A = uuid.uuid4()
B = uuid.uuid4()


def test_exactly_one_active_cleaner_is_assigned():
    assert resolve_auto_assignee(active_cleaner_ids=[A], total_active=1, rejecter_ids=set()) == A


def test_no_active_cleaner_leaves_it_pending():
    assert (
        resolve_auto_assignee(active_cleaner_ids=[], total_active=0, rejecter_ids=set()) is None
    )


@pytest.mark.parametrize("total", [2, 3, 17])
def test_more_than_one_active_cleaner_is_the_managers_choice(total):
    """`total_active`, not the page length: the count is the unpaginated one."""
    assert (
        resolve_auto_assignee(active_cleaner_ids=[A, B], total_active=total, rejecter_ids=set())
        is None
    )


def test_a_page_holding_one_row_of_a_larger_roster_does_not_qualify():
    """The probe page is 2 rows, so a tenant of five arrives as one row plus a total of five."""
    assert (
        resolve_auto_assignee(active_cleaner_ids=[A], total_active=5, rejecter_ids=set()) is None
    )


def test_the_single_cleaner_who_rejected_is_not_reassigned():
    """Design D3 — otherwise the replacement task returns to them for ever."""
    assert (
        resolve_auto_assignee(active_cleaner_ids=[A], total_active=1, rejecter_ids={A}) is None
    )


def test_a_rejecter_who_is_not_the_single_cleaner_is_irrelevant():
    assert resolve_auto_assignee(active_cleaner_ids=[A], total_active=1, rejecter_ids={B}) == A


def test_a_count_of_one_with_an_empty_page_declines():
    """A disagreement between the count and the page is not a tie to break."""
    assert (
        resolve_auto_assignee(active_cleaner_ids=[], total_active=1, rejecter_ids=set()) is None
    )


# --- assignment_blocker: is this task assignable right now, and who says no? -------


@pytest.mark.parametrize(
    "property_state",
    [
        PropertyOperationalState.AWAITING_CLEANING,
        PropertyOperationalState.OCCUPIED_ESTIMATED,
        None,
    ],
)
def test_a_task_outside_its_assignable_states_is_blocked_by_the_task(property_state):
    """The first branch, and it wins whatever the property is doing (D4).

    The order matters and reproduces the use case: `CleaningTask.assign` is what rejects an
    `IN_PROGRESS` task, and it rejects it before anything looks at the property. A blocker that
    answered `PROPERTY_STATE` here would send the manager to fix a flat that is not the
    problem.
    """
    assert (
        assignment_blocker(
            task_status=CleaningTaskStatus.IN_PROGRESS, property_state=property_state
        )
        is CleaningAssignmentBlocker.TASK_STATUS
    )


def test_a_created_task_on_a_property_that_refuses_the_trigger_is_blocked_by_the_property():
    """The second branch — the 409 an operator actually hit in dev on 2026-08-22."""
    assert (
        assignment_blocker(
            task_status=CleaningTaskStatus.CREATED,
            property_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
        )
        is CleaningAssignmentBlocker.PROPERTY_STATE
    )


def test_a_created_task_on_a_property_awaiting_cleaning_is_assignable():
    """The path that worked: same screen, same user, the one state the matrix admits."""
    assert (
        assignment_blocker(
            task_status=CleaningTaskStatus.CREATED,
            property_state=PropertyOperationalState.AWAITING_CLEANING,
        )
        is None
    )


@pytest.mark.parametrize(
    "property_state",
    [*list(PropertyOperationalState), None],
    ids=lambda state: state.value if state is not None else "unresolved",
)
def test_repointing_an_assigned_task_never_depends_on_the_property(property_state):
    """`ASSIGNED` → `ASSIGNED` does not fire `CLEANER_ASSIGNED`, so the property is irrelevant.

    Only the *first* assignment transitions the flat (`use_cases.py`, `AssignCleaningTaskUseCase`
    calls `_transition` only when the previous status was `CREATED`). Blocking a re-point on the
    property's state would forbid an operation the backend accepts — the opposite of the failure
    this change fixes, and just as wrong.
    """
    assert (
        assignment_blocker(
            task_status=CleaningTaskStatus.ASSIGNED, property_state=property_state
        )
        is None
    )


def test_an_unresolved_property_state_fails_open():
    """R3.3 — the UI guard is a courtesy, not a permission.

    The page read may not resolve a property (a row the second query missed). Answering
    `PROPERTY_STATE` there would hide a button that works; answering `None` offers it and lets
    the backend be the authority, which is what R3.3 says it is.
    """
    assert (
        assignment_blocker(task_status=CleaningTaskStatus.CREATED, property_state=None) is None
    )


@pytest.mark.parametrize(
    "property_state", list(PropertyOperationalState), ids=lambda state: state.value
)
def test_the_verdict_agrees_with_the_matrix_for_every_state(property_state):
    """D4 — the policy is *derived* from the matrix: "nunca de una constante".

    Every real operational state, checked against what the real machine says about
    `CLEANER_ASSIGNED`. That makes the test the matrix's shadow: widen `_POLICY` and the
    expectation widens with it, so a hand-written copy of today's set stops agreeing the moment
    the matrix moves — which is precisely the silent drift D4 rejects.

    Deliberately **not** written by monkeypatching `PropertyStateMachine.source_states_for` to
    move the matrix, which was the first draft and which the architecture and QA reviewers of
    this section both rejected against `steering/testing.md`: "Mockear solo en la frontera de
    adapters — nunca mockear repositorios ni la state machine en tests de dominio". The rule has
    no carve-out for "I am only checking that the read happens", and it does not need one: this
    version pins the same invariant using the real machine, and
    `test_the_module_names_no_operational_state_at_all` below closes the remaining hole — a copy
    that happens to equal today's set cannot be written without naming a state.
    """
    legal = PropertyStateMachine.source_states_for(PropertyStateTrigger.CLEANER_ASSIGNED)
    expected = None if property_state in legal else CleaningAssignmentBlocker.PROPERTY_STATE

    assert (
        assignment_blocker(
            task_status=CleaningTaskStatus.CREATED, property_state=property_state
        )
        is expected
    )


def test_the_module_names_no_operational_state_at_all():
    """The structural half of D4: there is no second copy of the matrix to drift.

    The test above proves the verdict *agrees* with the matrix; this one proves there is nothing
    else for the function to read. The pair matters because either alone has a hole: agreement is
    satisfied by a copy that happens to equal today's set, and silence about state names is
    satisfied by a function that reads the wrong trigger.

    Module-wide and not just over the function body, because a constant at module level would be
    exactly the drift the decision rejects — and so would a docstring naming the state, which is
    why the docstrings say "the matrix" instead.
    """
    source = inspect.getsource(assignment_module)

    named = [state.name for state in PropertyOperationalState if state.name in source]

    assert named == []


@pytest.mark.parametrize(
    "task_status", list(CleaningTaskStatus), ids=lambda status: status.value
)
def test_the_task_branch_agrees_with_the_entity_it_mirrors(task_status):
    """`_ASSIGNABLE_TASK_STATUSES` is a copy of what `CleaningTask.assign` accepts.

    D4 makes the *property* half derive from the matrix so it cannot drift; the task half has
    no equivalent accessor, because the entity keeps its precondition inside the operation. So
    the copy is pinned here instead, by driving the real entity for every status and requiring
    the two verdicts to agree. Add a status to `assign`'s `_require_status` set and forget this
    module, and this test is what goes red.
    """
    now = datetime.now(UTC)
    task = CleaningTask(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        checklist_template_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        status=task_status,
    )
    try:
        task.assign(uuid.uuid4(), now)
    except InvalidCleaningTransitionError:
        entity_refuses = True
    else:
        entity_refuses = False

    blocker = assignment_blocker(
        task_status=task_status, property_state=PropertyOperationalState.AWAITING_CLEANING
    )

    assert (blocker is CleaningAssignmentBlocker.TASK_STATUS) is entity_refuses
