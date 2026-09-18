"""`ListCleaningTasksUseCase` against fakes of its two ports — no database.

Only `cleaner-list-property-projection`'s slice of the use case: that each row's
`property_name`/`property_internal_code` come from the same batched `property_ids` already
computed for `states_for` (R2.1, R2.2), and that a `property_id` the fake `list_for_ids` does
not resolve leaves both fields `None` rather than raising (R1.3) — the identical fails-open
criterion `blocker` already applies via `states.get(...)`.

The pre-existing `assignment_blocker` behaviour (`cleaning-assign-preconditions`) is not
re-tested here; every task below uses `CREATED` with no operational state on file, which
`assignment_blocker` maps to `None`, so the fixture stays out of this test's way.
"""

import uuid
from datetime import UTC, datetime
from typing import Sequence

import pytest

from app.cleaning.application.use_cases import (
    CleaningActor,
    ListCleaningTasksUseCase,
)
from app.cleaning.domain.entities import CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.repositories import CleaningTaskFilters, Page
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
TENANT = uuid.uuid4()


def _property(name: str, code: str, *, tenant_id: uuid.UUID = TENANT) -> Property:
    return Property(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        internal_code=code,
        created_at=NOW,
        updated_at=NOW,
        address_line1="Calle de prueba 1",
        address_line2=None,
        city="Madrid",
        province="Madrid",
        postal_code="28029",
        country="ES",
        timezone="Europe/Madrid",
        access_notes=None,
        cleaning_notes=None,
        emergency_notes=None,
    )


def _task(prop: Property, *, status: CleaningTaskStatus = CleaningTaskStatus.CREATED) -> CleaningTask:
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        checklist_template_id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        status=status,
    )


class FakeCleaningTaskRepository:
    """One page, handed back verbatim — the filters and pagination are not this test's claim."""

    def __init__(self, tasks: Sequence[CleaningTask]) -> None:
        self._tasks = tuple(tasks)

    async def list(
        self, tenant_id: uuid.UUID, filters: CleaningTaskFilters, *, page: int, per_page: int
    ) -> Page:
        return Page(items=self._tasks, total=len(self._tasks))


class FakePropertyRepository:
    """Records every call to `list_for_ids`, so "one batched call" (R2.1) is demonstrated and
    not merely assumed. Resolves only the properties it was constructed with — anything else,
    including a dangling `property_id`, is simply absent from what it returns (the real
    contract's own promise)."""

    def __init__(self, properties: Sequence[Property]) -> None:
        self._properties = {p.id: p for p in properties}
        self.list_for_ids_calls: list[tuple[uuid.UUID, frozenset[uuid.UUID]]] = []

    async def states_for(
        self, tenant_id: uuid.UUID, property_ids
    ) -> dict[uuid.UUID, PropertyOperationalState]:
        return {}

    async def list_for_ids(self, tenant_id: uuid.UUID, property_ids) -> Sequence[Property]:
        ids = frozenset(property_ids)
        self.list_for_ids_calls.append((tenant_id, ids))
        return [
            prop
            for prop in self._properties.values()
            if prop.id in ids and prop.tenant_id == tenant_id
        ]


def _actor() -> CleaningActor:
    from app.auth.domain.enums import UserRole

    return CleaningActor(user_id=uuid.uuid4(), role=UserRole.PROPERTY_MANAGER)


async def _execute(tasks: FakeCleaningTaskRepository, properties: FakePropertyRepository):
    use_case = ListCleaningTasksUseCase(tasks=tasks, properties=properties)
    return await use_case.execute(
        tenant_id=TENANT,
        actor=_actor(),
        property_id=None,
        status=None,
        page=1,
        per_page=20,
    )


@pytest.mark.asyncio
async def test_each_row_gets_its_own_propertys_name_and_code() -> None:
    """R1.1 — two distinct flats on the same page, each row carrying its own property."""
    redes = _property("Redes 11", "REDES11")
    goya = _property("Goya 3", "GOYA3")
    task_redes = _task(redes)
    task_goya = _task(goya)
    tasks = FakeCleaningTaskRepository([task_redes, task_goya])
    properties = FakePropertyRepository([redes, goya])

    result = await _execute(tasks, properties)

    by_task_id = {view.task.id: view for view in result.items}
    assert by_task_id[task_redes.id].property_name == "Redes 11"
    assert by_task_id[task_redes.id].property_internal_code == "REDES11"
    assert by_task_id[task_goya.id].property_name == "Goya 3"
    assert by_task_id[task_goya.id].property_internal_code == "GOYA3"
    # One batched call over the page's distinct ids (R2.1), not one per row.
    assert len(properties.list_for_ids_calls) == 1
    called_tenant, called_ids = properties.list_for_ids_calls[0]
    assert called_tenant == TENANT
    assert called_ids == frozenset({redes.id, goya.id})


@pytest.mark.asyncio
async def test_an_unresolved_property_leaves_both_fields_null_without_raising() -> None:
    """R1.3 — fails open exactly like `blocker` already does via `states.get(...)`."""
    resolvable = _property("Redes 11", "REDES11")
    dangling_task = _task(_property("Ajena", "AJENA1"))  # its property is never registered
    resolvable_task = _task(resolvable)
    tasks = FakeCleaningTaskRepository([dangling_task, resolvable_task])
    # Only `resolvable` is known to the fake — the dangling task's property never resolves.
    properties = FakePropertyRepository([resolvable])

    result = await _execute(tasks, properties)

    by_task_id = {view.task.id: view for view in result.items}
    assert by_task_id[dangling_task.id].property_name is None
    assert by_task_id[dangling_task.id].property_internal_code is None
    assert by_task_id[resolvable_task.id].property_name == "Redes 11"
    assert by_task_id[resolvable_task.id].property_internal_code == "REDES11"
