"""Cleaning-assignment policy: who a new task goes to, and whether it can go at all.

Two pure functions over inputs the caller already fetched, exactly like `resolve_template` in
`templates.py` — and for the same reason: these are **business policies**, not steps of
orchestration, and `steering/backend-architecture.md` §Don'ts is explicit that a rule belongs
in `domain/`.

* `resolve_auto_assignee` — PRD §11's rule ("automática si hay una activa, si no queda
  pendiente"), R3.1/R3.2 and design D3 of `cleaning`. It lived inline in
  `ProvisionCleaningTaskUseCase._auto_assign` until the architecture reviewer of section 4
  named it: the `if` that decided eligibility sat between the two repository calls that
  fetched its inputs, so the policy and the plumbing could not be read — or tested — apart.
* `assignment_blocker` — whether a task is assignable *right now* and, if not, which party is
  refusing (`cleaning-assign-preconditions` R3.1/R3.3, design D4). It is here rather than in
  the router or the use case for the same reason as its neighbour, and it answers the same
  question the API answers with two different 409 codes.
"""

import uuid
from collections.abc import Collection, Sequence

from app.cleaning.domain.enums import CleaningAssignmentBlocker, CleaningTaskStatus
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.state_machine import PropertyStateMachine
from app.properties.domain.transition_enums import PropertyStateTrigger

#: The statuses `CleaningTask.assign` admits. A mirror of the set that method passes to
#: `_require_status`, and the only reason it is a mirror rather than a shared constant is that
#: the entity keeps its precondition where the operation is. `test_assignment.py` pins the two
#: together by driving the real entity, so the copy cannot drift in silence.
_ASSIGNABLE_TASK_STATUSES = frozenset(
    {CleaningTaskStatus.CREATED, CleaningTaskStatus.ASSIGNED}
)


def resolve_auto_assignee(
    *,
    active_cleaner_ids: Sequence[uuid.UUID],
    total_active: int,
    rejecter_ids: Collection[uuid.UUID],
) -> uuid.UUID | None:
    """The cleaner to auto-assign, or `None` to leave the task pending.

    Three conditions, and each has its own reason:

    * **`total_active` must be exactly 1.** PRD §11 auto-assigns only when the tenant has a
      single active cleaner; with two, the choice is the manager's and picking one would be a
      tie-break nobody asked for. `total_active` is the *unpaginated* count on purpose — a
      page that happened to hold one row must not make a tenant of five look like a tenant of
      one.
    * **That one must not have rejected a task of this reservation** (design D3). Rejection
      creates a replacement task, so without this the single cleaner of a tenant would be
      handed back the work they just declined, for ever.
    * **`active_cleaner_ids` must actually contain them.** Belt to the count's braces: the
      caller reads a page, and a count of one with an empty page is a disagreement worth
      declining rather than guessing at.
    """
    if total_active != 1:
        return None
    eligible = [
        cleaner_id for cleaner_id in active_cleaner_ids if cleaner_id not in rejecter_ids
    ]
    if len(eligible) != 1:
        return None
    return eligible[0]


def assignment_blocker(
    *,
    task_status: CleaningTaskStatus,
    property_state: PropertyOperationalState | None,
) -> CleaningAssignmentBlocker | None:
    """Which party refuses to assign this task right now, or `None` if nobody does.

    The order of the two branches reproduces the order of the use case, and that is the whole
    correctness argument: `CleaningTask.assign` runs first and rejects a task past its
    assignable statuses without ever looking at the flat, so a task that is out of the game
    must be reported as `TASK_STATUS` even when the flat would also have refused.

    1. `task_status` outside `_ASSIGNABLE_TASK_STATUSES` → `TASK_STATUS`.
    2. A first assignment (`CREATED`) whose property is in a state the matrix does not admit
       for `CLEANER_ASSIGNED` → `PROPERTY_STATE`. Only the first assignment fires that trigger;
       re-pointing a task that is already `ASSIGNED` does not touch the property, so it does
       not depend on its state.
    3. Otherwise `None`.

    The legal states come from `PropertyStateMachine.source_states_for`, **never** from a
    literal here (design D4). A hand-kept copy would derive from the matrix the first time a
    transition is added, and derive silently: widening the matrix is explicitly out of this
    change's scope but foreseen, and with a constant the screen would keep blocking for ever.
    `source_states_for` exists for exactly this reason — `celery-jobs` already rejected the
    hand-kept list, in those words.

    `property_state is None` — the page read did not resolve that property — returns `None`:
    it **fails open**, offers the control and leaves the backend as the authority (R3.3).
    """
    if task_status not in _ASSIGNABLE_TASK_STATUSES:
        return CleaningAssignmentBlocker.TASK_STATUS
    if task_status is CleaningTaskStatus.CREATED and property_state is not None:
        legal = PropertyStateMachine.source_states_for(PropertyStateTrigger.CLEANER_ASSIGNED)
        if property_state not in legal:
            return CleaningAssignmentBlocker.PROPERTY_STATE
    return None
