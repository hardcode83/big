"""`list_live_for_properties` (`dashboard-api` R1, R2, task 4.1).

The batch counterpart of `list_live_for_reservation`, added so the dashboard collection can
resolve N properties without N queries.
"""

import pytest

from app.cleaning.domain.entities import LIVE_STATUSES
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.value_objects import CleaningTaskSummary
from app.cleaning.infrastructure.repositories import SqlAlchemyCleaningTaskRepository
from tests.cleaning.conftest import insert_property, insert_task
from tests.sql_counter import count_statements


def _reader(db_session) -> SqlAlchemyCleaningTaskRepository:
    return SqlAlchemyCleaningTaskRepository(db_session)


@pytest.mark.asyncio
async def test_an_empty_batch_returns_nothing_without_querying(
    db_session, test_engine, tenant_a
) -> None:
    """The name promises "without querying", so the test counts rather than trusting.

    `== []` alone would also pass for an implementation that emitted `IN ()` and got zero
    rows back — the QA panel of section 4 caught exactly that gap.
    """
    with count_statements(test_engine) as log:
        found = await _reader(db_session).list_live_for_properties(tenant_a.id, [])

    assert found == []
    assert log.matching("cleaning_tasks") == []


@pytest.mark.asyncio
async def test_it_returns_the_live_tasks_of_every_property_in_the_batch(
    db_session, tenant_a, property_a, template_a
) -> None:
    other = await insert_property(db_session, tenant_a, code="PAJARITOS8")
    quiet = await insert_property(db_session, tenant_a, code="SILENCIO1")
    mine = await insert_task(db_session, tenant_a, property_a, template_a)
    theirs = await insert_task(db_session, tenant_a, other, template_a)

    found = await _reader(db_session).list_live_for_properties(
        tenant_a.id, [property_a.id, other.id, quiet.id]
    )

    assert {task.id for task in found} == {mine.id, theirs.id}
    assert {task.property_id for task in found} == {property_a.id, other.id}


@pytest.mark.asyncio
async def test_a_property_outside_the_batch_is_not_returned(
    db_session, tenant_a, property_a, template_a
) -> None:
    other = await insert_property(db_session, tenant_a, code="PAJARITOS8")
    mine = await insert_task(db_session, tenant_a, property_a, template_a)
    await insert_task(db_session, tenant_a, other, template_a)

    found = await _reader(db_session).list_live_for_properties(tenant_a.id, [property_a.id])

    assert [task.id for task in found] == [mine.id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", sorted(set(CleaningTaskStatus) - LIVE_STATUSES, key=lambda s: s.value)
)
async def test_a_task_in_a_terminal_status_is_not_live(
    db_session, tenant_a, property_a, template_a, status: CleaningTaskStatus
) -> None:
    """The same `LIVE_STATUSES` criterion as the per-reservation reader, and derived from
    the constant rather than restated — a status changing sides must move this test too."""
    await insert_task(db_session, tenant_a, property_a, template_a, status=status)

    found = await _reader(db_session).list_live_for_properties(tenant_a.id, [property_a.id])

    assert found == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(LIVE_STATUSES, key=lambda s: s.value))
async def test_every_live_status_is_returned(
    db_session, tenant_a, property_a, template_a, status: CleaningTaskStatus
) -> None:
    task = await insert_task(db_session, tenant_a, property_a, template_a, status=status)

    found = await _reader(db_session).list_live_for_properties(tenant_a.id, [property_a.id])

    assert [item.id for item in found] == [task.id]


@pytest.mark.asyncio
async def test_it_never_returns_another_tenants_task(
    db_session, tenant_a, tenant_b, property_a, property_b, template_a, template_b
) -> None:
    """DoD §28.18 — and the neighbour's property id is passed in explicitly, so the tenant
    argument is what excludes it rather than the caller happening not to ask."""
    mine = await insert_task(db_session, tenant_a, property_a, template_a)
    await insert_task(db_session, tenant_b, property_b, template_b)

    found = await _reader(db_session).list_live_for_properties(
        tenant_a.id, [property_a.id, property_b.id]
    )

    assert [task.id for task in found] == [mine.id]


@pytest.mark.asyncio
async def test_it_returns_the_narrow_projection_and_not_the_entity(
    db_session, tenant_a, property_a, template_a
) -> None:
    """The security panel of section 4: `CleaningTask` carries `notes` (a rule-11 free-text
    sink), `assigned_cleaner_id` and `validated_by_user_id`, and a dashboard needs none."""
    import dataclasses

    task = await insert_task(db_session, tenant_a, property_a, template_a)

    found = await _reader(db_session).list_live_for_properties(tenant_a.id, [property_a.id])

    assert isinstance(found[0], CleaningTaskSummary)
    assert (found[0].id, found[0].property_id) == (task.id, property_a.id)
    assert found[0].status is CleaningTaskStatus.CREATED
    assert {field.name for field in dataclasses.fields(CleaningTaskSummary)} == {
        "id",
        "property_id",
        "status",
    }


@pytest.mark.asyncio
async def test_it_never_selects_the_sensitive_columns(
    db_session, test_engine, tenant_a, property_a, template_a
) -> None:
    """Asserting on the SQL, not the result: a reader that fetched the whole row and
    narrowed in Python afterwards would pass any assertion made on the return value."""
    await insert_task(db_session, tenant_a, property_a, template_a)

    with count_statements(test_engine) as log:
        found = await _reader(db_session).list_live_for_properties(
            tenant_a.id, [property_a.id]
        )

    assert len(found) == 1
    statements = log.matching("from cleaning_tasks")
    assert len(statements) == 1
    selected = statements[0].lower()
    for column in ("notes", "assigned_cleaner_id", "validated_by_user_id", "validation_status"):
        assert column not in selected, f"the query still reads {column}"
