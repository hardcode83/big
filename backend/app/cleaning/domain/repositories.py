"""Ports owned by the cleaning domain (design D6).

Every method takes `tenant_id` explicitly — the same contract the rest of the project uses
(`reservations`, `properties`, `notifications`), where the parameter is the authoritative
mechanism and the global loader criteria of `app/core/db.py` are only the net.

**For `CleaningChecklistCompletionRepository` there is no net.** Its table has no
`tenant_id` column: `domain-foundation-ops` scopes it transitively through
`cleaning_task_id`, and `tenant_scoped_classes()` selects mapped classes **by column**
(`app/core/db.py:62`), so `with_loader_criteria` never sees it. The `JOIN` its adapter
performs is the whole isolation mechanism, which is why R7.5 demands a dedicated test
rather than relying on the module's generic one. No method here accepts a bare
`cleaning_task_id`, so an implementation cannot be written without the tenant — and no
method carries the same task id twice, so an implementation cannot validate one copy and
write the other.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.cleaning.domain.entities import (
    CleaningChecklistCompletion,
    CleaningChecklistTemplate,
    CleaningTask,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.value_objects import CleaningTaskSummary


@dataclass(frozen=True)
class CleaningTaskFilters:
    """The filters of `GET /cleaning-tasks`, combined with AND.

    `assigned_cleaner_id` is **not** a client-supplied filter dressed up as one: the use
    case sets it from the authenticated role when that role is `CLEANER` (design D7), so
    the row-level restriction of R7.2 cannot be dropped by omitting a query parameter.
    """

    property_id: uuid.UUID | None = None
    status: CleaningTaskStatus | None = None
    assigned_cleaner_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Page:
    """One page of results plus the total the client needs for `total_pages` (PRD §23)."""

    items: tuple[CleaningTask, ...]
    total: int


@dataclass(frozen=True)
class TemplatePage:
    items: tuple[CleaningChecklistTemplate, ...]
    total: int


class CleaningTaskRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID, task_id: uuid.UUID) -> CleaningTask | None:
        """The task, or `None` when it does not exist **within this tenant**.

        Returning `None` rather than raising keeps the 404-vs-403 decision (R7.3) in the
        use case, which is also where the row-level restriction of R7.2 applies.
        """
        ...

    async def add(self, tenant_id: uuid.UUID, task: CleaningTask) -> None:
        """Append a task; refuses an entity of another tenant.

        Raises `DuplicateLiveCleaningTaskError` when
        `uq_cleaning_tasks_live_reservation` rejects it (design D2), so the partial index
        stays the authority over a read-then-write check.
        """
        ...

    async def save(self, tenant_id: uuid.UUID, task: CleaningTask) -> None:
        """Persist the mutated aggregate; refuses an entity of another tenant."""
        ...

    async def list_live_for_reservation(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> Sequence[CleaningTask]:
        """Tasks of that reservation still in a `LIVE_STATUSES` status (R2.5)."""
        ...

    async def list_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[CleaningTask]:
        """Every task of the property — the `PropertyTransitionContext` needs them all.

        `ContextualStateResolver` decides "is there pending cleaning" over the collection
        it is handed (`app/properties/domain/state_resolution.py:143-147`), so handing it
        a pre-filtered slice would move that decision out of the machine.
        """
        ...

    async def list_live_for_properties(
        self, tenant_id: uuid.UUID, property_ids: Sequence[uuid.UUID]
    ) -> Sequence[CleaningTaskSummary]:
        """Live tasks of a batch of properties, in ONE query (`dashboard-api` R1.7).

        **Returns `CleaningTaskSummary`, not `CleaningTask`.** The entity carries `notes`
        — free text, a rule-11 sink of `steering/security.md` — plus `assigned_cleaner_id`
        and `validated_by_user_id`, and this reader feeds a dashboard that needs none of
        them. `api/schemas.py:8-13` already records the same hazard for this entity; the
        projection makes it structural instead of a discipline each serialiser must
        remember.

        The batch counterpart of `list_live_for_reservation`, with the shape
        `ReservationRepository.list_for_properties` established (that change's design D2):
        the dashboard collection composes cards for N properties and must not issue N
        queries. The caller groups by `property_id` in memory.

        **`Sequence`, not `list`** — this Protocol declares a method called `list`, which
        shadows the builtin inside the class body and would make `list[CleaningTask]` a
        `TypeError` at import time. The same note `ReservationRepository` carries.

        Same `LIVE_STATUSES` criterion as the per-reservation reader, and for the same
        reason it is not a parameter: which statuses count as live is the domain's
        decision, and letting a caller choose would put a second copy of it in the caller.

        An empty `property_ids` returns an empty sequence without querying.
        """
        ...

    async def list_rejecters_for_reservation(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> Sequence[uuid.UUID]:
        """Cleaners who already rejected a task of this reservation (design D3).

        Auto-assignment excludes them; without this the single active cleaner of a tenant
        would be handed the replacement task they just declined, for ever.
        """
        ...

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: CleaningTaskFilters,
        *,
        page: int,
        per_page: int,
    ) -> Page:
        """Filtered, ordered and paginated. The order must be stable (`created_at`, `id`)."""
        ...


class CleaningChecklistTemplateRepository(Protocol):
    async def get(
        self, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> CleaningChecklistTemplate | None: ...

    async def add(self, tenant_id: uuid.UUID, template: CleaningChecklistTemplate) -> None: ...

    async def list_candidates_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[CleaningChecklistTemplate]:
        """Active templates of the property **and** the tenant-wide ones.

        Both levels in one query so `resolve_template` can apply precedence *and* detect
        ambiguity (R1.4); fetching only the winning level would hide the second one.
        """
        ...

    async def list(
        self, tenant_id: uuid.UUID, *, page: int, per_page: int
    ) -> TemplatePage: ...


class CleaningChecklistCompletionRepository(Protocol):
    async def list_for_task(
        self, tenant_id: uuid.UUID, task_id: uuid.UUID
    ) -> Sequence[CleaningChecklistCompletion]: ...

    async def upsert(
        self, tenant_id: uuid.UUID, completion: CleaningChecklistCompletion
    ) -> None:
        """Idempotent write against `uq_cleaning_checklist_completions_...` (R4.4).

        **One task identifier, and it is the one inside the entity.** An earlier shape took
        `task_id` beside `completion` so the adapter could validate it, which left two
        independently-settable ids for the same thing: an adapter could check one and write
        the other, and since this table has no `tenant_id` and no loader-criteria net, the
        row would land against a task nobody proved belongs to `tenant_id`. The tenancy
        reviewer of section 1 named it. With a single id there is nothing to diverge —
        the adapter resolves `completion.cleaning_task_id` **within** `tenant_id` and
        refuses when it does not resolve.
        """
        ...
