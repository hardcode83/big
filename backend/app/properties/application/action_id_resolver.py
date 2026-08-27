"""Resolve the action ids (cleaning_task_id, incident_id) for a page of stalls.

A pure data layer: given a tenant_id and a list of `(property_id, blocking_state)` tuples,
returns a `dict[property_id, (cleaning_task_id | None, incident_id | None)]`. The caller
(`ListBlockedTransitionsUseCase`) reads the mapping to rebuild its rows with the ids
populated — the resolver never touches the row dataclass itself, which is `frozen` so a
mutation would have been a `FrozenInstanceError` anyway.

The split by `blocking_state` family (R2.5) is the rule, not an optimisation: a row in the
cleaning bucket never queries `incidents`, and vice versa. A `blocking_state` added in the
future that lands in neither set falls into the incident bucket — the safe default for the
dashboard's "this is the resource a button would call".

**Batch by design (R3.4).** Two ports, two calls per page — at most one call to
`cleaning_tasks` and one to `incidents` regardless of how many stalls the page contains.
The split is what makes the bound one-call-per-table-per-page independent of the page size.
"""

import uuid
from collections.abc import Sequence

from app.cleaning.domain.repositories import CleaningTaskRepository
from app.maintenance.domain.repositories import IncidentReader
from app.properties.domain.enums import PropertyOperationalState

# The three "cleaning family" states whose presence means the resolver should query
# `cleaning_tasks` (R2.1). Everything else routes to `incidents` (R2.2). Frozen so the
# membership check is hash-stable and immune to accidental mutation.
CLEANING_BLOCKING_STATES: frozenset[PropertyOperationalState] = frozenset(
    {
        PropertyOperationalState.AWAITING_CLEANING,
        PropertyOperationalState.CLEANING_IN_PROGRESS,
        PropertyOperationalState.CLEANING_SCHEDULED,
    }
)


def _partition_by_family(
    rows: Sequence[tuple[uuid.UUID, PropertyOperationalState]],
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """`(cleaning_property_ids, incident_property_ids)`, partitioned by `blocking_state`.

    A row whose `blocking_state` is in `CLEANING_BLOCKING_STATES` lands in the cleaning
    bucket; everything else lands in the incident bucket. Both buckets may be empty (a page
    with no stalls, or a page where every stall is in the same family), and the caller
    short-circuits the empty buckets so it does not issue a query for `property_ids=()`.
    """
    cleaning: set[uuid.UUID] = set()
    incident: set[uuid.UUID] = set()
    for property_id, state in rows:
        if state in CLEANING_BLOCKING_STATES:
            cleaning.add(property_id)
        else:
            incident.add(property_id)
    return cleaning, incident


def _one_live_task_per_property(
    tasks: Sequence,  # Sequence[CleaningTaskSummary] without the cross-domain import
) -> dict[uuid.UUID, uuid.UUID]:
    """Pick ONE cleaning task id per property, deterministically.

    Mirrors `app/dashboard/application/use_cases.py::_one_live_task_per_property` so the
    dashboard and this resolver do not disagree on which task wins when a property happens
    to have two live tasks (R2.5 forbids that case at the schema level via
    `uq_cleaning_tasks_live_reservation`, but the resolver does not assume it).

    The tie-break is `str(task.id)`: a UUID is a UUID is a UUID, and sorting the textual
    form is a stable total order without dragging a clock in. Returning the **id**, not
    the summary, keeps this resolver from leaking `CleaningTaskStatus` into a module that
    does not need it — the API layer would only have used the id anyway (R1.3: `null` or
    a UUID string on the wire, nothing else).
    """
    chosen: dict[uuid.UUID, uuid.UUID] = {}
    for task in sorted(tasks, key=lambda item: str(item.id)):
        chosen.setdefault(task.property_id, task.id)
    return chosen


class ActionIdResolver:
    """Populate `cleaning_task_id` / `incident_id` for a page of stalls.

    Two ports injected via constructor: `CleaningTaskRepository` (live tasks, batch — the
    cleaning module's existing `list_live_for_properties`) and `IncidentReader` (open
    incidents, batch — the sibling added by this change, see
    `backend/app/maintenance/domain/repositories.py::IncidentReader.list_open_for_properties`).

    No state, no side effects beyond the two awaited calls — the same callable instance
    can serve every page of the listing without re-allocating.
    """

    def __init__(
        self,
        cleaning_tasks: CleaningTaskRepository,
        incidents: IncidentReader,
    ) -> None:
        self._cleaning_tasks = cleaning_tasks
        self._incidents = incidents

    async def resolve(
        self,
        rows: Sequence[tuple[uuid.UUID, PropertyOperationalState]],
        tenant_id: uuid.UUID,
    ) -> dict[uuid.UUID, tuple[uuid.UUID | None, uuid.UUID | None]]:
        """Returns `{property_id: (cleaning_task_id, incident_id)}` for the whole page.

        For every `property_id` present in `rows`, exactly one of the two ids is `None`:
        the partition in `_partition_by_family` is total, so a cleaning-bucket row never
        queries `incidents` and vice versa (R2.5). Both ids are `None` when the
        corresponding lookup finds nothing (R2.3, R2.4 — the absence of an open task or
        incident is a real answer).

        Tenant scope is enforced by the ports: every call is keyed on the verified
        `tenant_id`. The resolver itself never reads `tenant_id` from path, body or query
        (R3.3) — it is a positional argument the caller (the use case) injects from the
        token it received upstream.
        """
        cleaning_ids, incident_ids = _partition_by_family(rows)
        result: dict[uuid.UUID, tuple[uuid.UUID | None, uuid.UUID | None]] = {}

        # Cleaning bucket: ONE batch query for all cleaning-state properties.
        # Empty set → empty call (`list_live_for_properties` is documented to no-op on
        # empty input); the `if` keeps the call off the wire when nothing to look up.
        if cleaning_ids:
            tasks = await self._cleaning_tasks.list_live_for_properties(
                tenant_id, sorted(cleaning_ids)
            )
            tasks_by_property = _one_live_task_per_property(tasks)
            for property_id in cleaning_ids:
                result[property_id] = (tasks_by_property.get(property_id), None)

        # Incident bucket: ONE batch query for all non-cleaning-state properties.
        if incident_ids:
            incidents_by_property = await self._incidents.list_open_for_properties(
                tenant_id, sorted(incident_ids)
            )
            for property_id in incident_ids:
                result[property_id] = (None, incidents_by_property.get(property_id))

        return result
