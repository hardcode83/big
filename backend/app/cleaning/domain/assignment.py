"""Who a new cleaning task is handed to, if anyone (R3.1, R3.2, design D3).

Pure function over inputs the caller already fetched, exactly like `resolve_template` in
`templates.py` — and for the same reason: PRD §11's rule ("automática si hay una activa, si
no queda pendiente") is a **business policy**, not a step of orchestration, and
`steering/backend-architecture.md` §Don'ts is explicit that a rule belongs in `domain/`.

It lived inline in `ProvisionCleaningTaskUseCase._auto_assign` until the architecture
reviewer of section 4 named it: the `if` that decided eligibility sat between the two
repository calls that fetched its inputs, so the policy and the plumbing could not be read —
or tested — apart.
"""

import uuid
from collections.abc import Collection, Sequence


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
