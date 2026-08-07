"""R7.1, R7.5 — the adapters, and the isolation they are solely responsible for.

`cleaning_checklist_completions` has no `tenant_id` and is not covered by
`tenant_scoped_classes()` (`app/core/db.py:62`), so the `JOIN` its adapter performs is the
entire isolation mechanism. Those tests are not a formality: nothing else would catch a
regression there.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.cleaning.domain.entities import CleaningChecklistCompletion, CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    CleaningTaskNotFoundError,
    DuplicateLiveCleaningTaskError,
)
from app.cleaning.domain.repositories import CleaningTaskFilters
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistCompletionRepository,
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.core.tenancy import CrossTenantWriteError
from tests.cleaning.conftest import insert_task, insert_template

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _entity(tenant, prop, template, *, reservation=None, status=CleaningTaskStatus.CREATED):
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
        created_at=NOW,
        updated_at=NOW,
        reservation_id=reservation.id if reservation is not None else None,
        status=status,
    )


# --- tasks ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_get_round_trip(db_session, tenant_a, property_a, template_a):
    repo = SqlAlchemyCleaningTaskRepository(db_session)
    task = _entity(tenant_a, property_a, template_a)

    await repo.add(tenant_a.id, task)
    fetched = await repo.get(tenant_a.id, task.id)

    assert fetched is not None
    assert fetched.id == task.id
    assert fetched.status is CleaningTaskStatus.CREATED


@pytest.mark.asyncio
async def test_get_from_another_tenant_returns_none(
    db_session, tenant_a, tenant_b, property_a, template_a
):
    """R7.3 — the use case turns this `None` into the same 404 an unknown id gets."""
    repo = SqlAlchemyCleaningTaskRepository(db_session)
    task = _entity(tenant_a, property_a, template_a)
    await repo.add(tenant_a.id, task)

    assert await repo.get(tenant_b.id, task.id) is None


@pytest.mark.asyncio
async def test_add_refuses_an_entity_of_another_tenant(
    db_session, tenant_a, tenant_b, property_a, template_a
):
    repo = SqlAlchemyCleaningTaskRepository(db_session)

    with pytest.raises(CrossTenantWriteError):
        await repo.add(tenant_b.id, _entity(tenant_a, property_a, template_a))


@pytest.mark.asyncio
async def test_add_translates_the_partial_index_into_a_domain_error(
    db_session, tenant_a, property_a, template_a
):
    """R2.5, design D2 — the constraint is the authority, not a prior read."""
    from tests.cleaning.conftest import insert_reservation

    reservation = await insert_reservation(db_session, tenant_a, property_a)
    repo = SqlAlchemyCleaningTaskRepository(db_session)
    await repo.add(tenant_a.id, _entity(tenant_a, property_a, template_a, reservation=reservation))

    with pytest.raises(DuplicateLiveCleaningTaskError):
        await repo.add(
            tenant_a.id, _entity(tenant_a, property_a, template_a, reservation=reservation)
        )


@pytest.mark.asyncio
async def test_save_also_translates_the_partial_index(
    db_session, tenant_a, property_a, template_a
):
    """The `except IntegrityError` branch of `save` is reachable, not decoration.

    Moving a terminal task back into a live status while another one holds the reservation
    trips the same index as `add`. The QA panel of sections 2-3 found the branch untested and
    verified by probe that it fires — this is that probe, committed.
    """
    from tests.cleaning.conftest import insert_reservation

    reservation = await insert_reservation(db_session, tenant_a, property_a)
    repo = SqlAlchemyCleaningTaskRepository(db_session)

    rejected = _entity(
        tenant_a, property_a, template_a, reservation=reservation, status=CleaningTaskStatus.REJECTED
    )
    await repo.add(tenant_a.id, rejected)
    await repo.add(
        tenant_a.id, _entity(tenant_a, property_a, template_a, reservation=reservation)
    )

    rejected.status = CleaningTaskStatus.ASSIGNED
    with pytest.raises(DuplicateLiveCleaningTaskError):
        await repo.save(tenant_a.id, rejected)


@pytest.mark.asyncio
async def test_save_writes_the_mutable_columns_only(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    from app.auth.domain.enums import UserRole

    repo = SqlAlchemyCleaningTaskRepository(db_session)
    task = _entity(tenant_a, property_a, template_a)
    await repo.add(tenant_a.id, task)

    cleaner = users_by_role_a[UserRole.CLEANER]
    task.assign(cleaner.id, NOW)
    await repo.save(tenant_a.id, task)

    fetched = await repo.get(tenant_a.id, task.id)
    assert fetched.status is CleaningTaskStatus.ASSIGNED
    assert fetched.assigned_cleaner_id == cleaner.id


@pytest.mark.asyncio
async def test_save_refuses_an_entity_of_another_tenant(
    db_session, tenant_a, tenant_b, property_a, template_a
):
    repo = SqlAlchemyCleaningTaskRepository(db_session)
    task = _entity(tenant_a, property_a, template_a)
    await repo.add(tenant_a.id, task)

    with pytest.raises(CrossTenantWriteError):
        await repo.save(tenant_b.id, task)


@pytest.mark.asyncio
async def test_save_never_moves_a_task_to_another_tenant(
    db_session, tenant_a, tenant_b, property_a, template_a
):
    """`tenant_id` is not in `_MUTABLE_TASK_COLUMNS`, and that is rule 1's business."""
    repo = SqlAlchemyCleaningTaskRepository(db_session)
    task = _entity(tenant_a, property_a, template_a)
    await repo.add(tenant_a.id, task)

    task.tenant_id = tenant_b.id
    with pytest.raises(CrossTenantWriteError):
        await repo.save(tenant_a.id, task)

    assert await repo.get(tenant_a.id, task.id) is not None
    assert await repo.get(tenant_b.id, task.id) is None


@pytest.mark.asyncio
async def test_save_does_not_write_notes(db_session, tenant_a, property_a, template_a):
    """Design D13 — `notes` is outside this change's writable surface (rule 11)."""
    repo = SqlAlchemyCleaningTaskRepository(db_session)
    task = _entity(tenant_a, property_a, template_a)
    await repo.add(tenant_a.id, task)

    task.notes = "código de la puerta 4821"
    await repo.save(tenant_a.id, task)

    assert (await repo.get(tenant_a.id, task.id)).notes is None


@pytest.mark.asyncio
async def test_list_live_for_reservation_ignores_terminal_tasks(
    db_session, tenant_a, property_a, template_a
):
    from tests.cleaning.conftest import insert_reservation

    reservation = await insert_reservation(db_session, tenant_a, property_a)
    await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        reservation=reservation,
        status=CleaningTaskStatus.REJECTED,
    )
    live = await insert_task(
        db_session, tenant_a, property_a, template_a, reservation=reservation
    )

    repo = SqlAlchemyCleaningTaskRepository(db_session)
    found = await repo.list_live_for_reservation(tenant_a.id, reservation.id)

    assert [task.id for task in found] == [live.id]


@pytest.mark.asyncio
async def test_list_rejecters_for_reservation(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """Design D3 — auto-assignment must not hand the replacement back to the rejecter."""
    from app.auth.domain.enums import UserRole
    from tests.cleaning.conftest import insert_reservation

    reservation = await insert_reservation(db_session, tenant_a, property_a)
    cleaner = users_by_role_a[UserRole.CLEANER]
    await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        reservation=reservation,
        status=CleaningTaskStatus.REJECTED,
        cleaner=cleaner,
    )

    repo = SqlAlchemyCleaningTaskRepository(db_session)
    assert list(await repo.list_rejecters_for_reservation(tenant_a.id, reservation.id)) == [
        cleaner.id
    ]


@pytest.mark.asyncio
async def test_list_is_scoped_paginated_and_filtered(
    db_session, tenant_a, tenant_b, property_a, property_b, template_a, template_b
):
    for _ in range(3):
        await insert_task(db_session, tenant_a, property_a, template_a)
    await insert_task(db_session, tenant_b, property_b, template_b)

    repo = SqlAlchemyCleaningTaskRepository(db_session)
    page = await repo.list(tenant_a.id, CleaningTaskFilters(), page=1, per_page=2)

    assert page.total == 3
    assert len(page.items) == 2
    assert all(task.tenant_id == tenant_a.id for task in page.items)


@pytest.mark.asyncio
async def test_list_filters_by_assigned_cleaner(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """R7.2 — the row-level restriction is expressed through this filter."""
    from app.auth.domain.enums import UserRole

    cleaner = users_by_role_a[UserRole.CLEANER]
    mine = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.ASSIGNED,
        cleaner=cleaner,
    )
    await insert_task(db_session, tenant_a, property_a, template_a)

    repo = SqlAlchemyCleaningTaskRepository(db_session)
    page = await repo.list(
        tenant_a.id,
        CleaningTaskFilters(assigned_cleaner_id=cleaner.id),
        page=1,
        per_page=20,
    )

    assert [task.id for task in page.items] == [mine.id]


# --- templates --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidates_include_both_levels_and_exclude_inactive(
    db_session, tenant_a, tenant_b, property_a, property_b
):
    own = await insert_template(db_session, tenant_a, property_id=property_a.id, name="own")
    default = await insert_template(db_session, tenant_a, name="default")
    await insert_template(
        db_session, tenant_a, property_id=property_a.id, active=False, name="off"
    )
    await insert_template(db_session, tenant_b, name="neighbour")

    repo = SqlAlchemyCleaningChecklistTemplateRepository(db_session)
    found = await repo.list_candidates_for_property(tenant_a.id, property_a.id)

    assert {template.id for template in found} == {own.id, default.id}


@pytest.mark.asyncio
async def test_candidates_exclude_another_propertys_template(
    db_session, tenant_a, property_a
):
    other = await insert_property_named(db_session, tenant_a)
    await insert_template(db_session, tenant_a, property_id=other.id, name="other")

    repo = SqlAlchemyCleaningChecklistTemplateRepository(db_session)
    assert await repo.list_candidates_for_property(tenant_a.id, property_a.id) == []


async def insert_property_named(session, tenant):
    from tests.cleaning.conftest import insert_property

    return await insert_property(session, tenant, code=f"X{uuid.uuid4().hex[:6]}")


@pytest.mark.asyncio
async def test_template_list_is_scoped(db_session, tenant_a, tenant_b, template_a, template_b):
    repo = SqlAlchemyCleaningChecklistTemplateRepository(db_session)
    page = await repo.list(tenant_a.id, page=1, per_page=20)

    assert [template.id for template in page.items] == [template_a.id]
    assert page.total == 1


# --- completions: the table with no net -------------------------------------------


@pytest.mark.asyncio
async def test_upsert_and_list_round_trip(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    repo = SqlAlchemyCleaningChecklistCompletionRepository(db_session)

    await repo.upsert(
        tenant_a.id,
        CleaningChecklistCompletion(
            id=uuid.uuid4(),
            cleaning_task_id=task.id,
            item_id="kitchen",
            completed=True,
            completed_at=NOW,
            completed_by=users_by_role_a[UserRole.CLEANER].id,
        ),
    )

    found = await repo.list_for_task(tenant_a.id, task.id)
    assert [completion.item_id for completion in found] == ["kitchen"]
    assert found[0].completed is True


@pytest.mark.asyncio
async def test_upsert_is_idempotent(db_session, tenant_a, property_a, template_a):
    """R4.4 — the second write updates rather than violating the unique constraint."""
    task = await insert_task(db_session, tenant_a, property_a, template_a)
    repo = SqlAlchemyCleaningChecklistCompletionRepository(db_session)

    for _ in range(2):
        await repo.upsert(
            tenant_a.id,
            CleaningChecklistCompletion(
                id=uuid.uuid4(), cleaning_task_id=task.id, item_id="kitchen", completed=True
            ),
        )

    assert len(await repo.list_for_task(tenant_a.id, task.id)) == 1


@pytest.mark.asyncio
async def test_upsert_survives_the_losing_side_of_a_race(
    db_session, test_engine, tenant_a, property_a, template_a, users_by_role_a
):
    """R4.4 under concurrency, not just in sequence — the gap `/sdd:review` found.

    The first version read for an existing row and only then inserted. Two concurrent taps of
    the same item both read "no row" and both inserted, and the loser violated
    `uq_cleaning_checklist_completions_cleaning_task_id_item_id` with a bare `IntegrityError`
    — not a `CleaningDomainError`, so an unhandled 500 where R4.4 promises an idempotent 204.
    Both the architecture and the QA reviewer found it independently.

    **Genuinely concurrent, and the first version of this test was not.** It committed the
    winner before opening the loser's session, so the two were strictly sequential — and under
    the old code the loser's `SELECT` would then have *found* the committed row and taken the
    `UPDATE` branch, never reaching the `INSERT` that used to raise. In other words it would
    have passed against the bug it claimed to reproduce. The architecture reviewer of
    `/sdd:review` caught the overclaim on the re-review.

    Here both transactions are open and neither has committed when both attempt their write,
    which is the only arrangement in which the race exists at all: the loser blocks on the
    winner's row lock and then resolves the conflict, instead of duplicating the key.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    # Real users: `completed_by` is an FK to `users`, so random UUIDs would fail the
    # foreign key before ever reaching the conflict this test is about.
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    await db_session.commit()

    async def tick(writer_id):
        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            await SqlAlchemyCleaningChecklistCompletionRepository(session).upsert(
                tenant_a.id,
                CleaningChecklistCompletion(
                    id=uuid.uuid4(),
                    cleaning_task_id=task.id,
                    item_id="kitchen",
                    completed=True,
                    completed_at=NOW,
                    completed_by=writer_id,
                ),
            )
            await session.commit()

    first = users_by_role_a[UserRole.CLEANER].id
    second = users_by_role_a[UserRole.TECHNICIAN].id
    # Both in flight at once. Against the old check-then-act both would read "no row", both
    # would insert, and the loser would violate the unique constraint with a bare
    # `IntegrityError` — an unmapped 500 where R4.4 promises an idempotent 204.
    await asyncio.gather(tick(first), tick(second))

    async with AsyncSession(test_engine, expire_on_commit=False) as reader:
        rows = await SqlAlchemyCleaningChecklistCompletionRepository(reader).list_for_task(
            tenant_a.id, task.id
        )
    assert len(rows) == 1
    # Whichever won the lock, exactly one row exists and it names one of the two writers.
    assert rows[0].completed_by in {first, second}
    assert rows[0].completed is True


@pytest.mark.asyncio
async def test_completions_of_another_tenant_are_invisible(
    db_session, tenant_a, tenant_b, property_b, template_b
):
    """R7.5 — the only thing standing between these two tenants is the `JOIN`."""
    neighbour_task = await insert_task(db_session, tenant_b, property_b, template_b)
    repo = SqlAlchemyCleaningChecklistCompletionRepository(db_session)
    await repo.upsert(
        tenant_b.id,
        CleaningChecklistCompletion(
            id=uuid.uuid4(), cleaning_task_id=neighbour_task.id, item_id="kitchen", completed=True
        ),
    )

    assert await repo.list_for_task(tenant_a.id, neighbour_task.id) == []


@pytest.mark.asyncio
async def test_completions_of_another_tenant_are_unwritable(
    db_session, tenant_a, tenant_b, property_b, template_b
):
    """R7.5 — and the write path answers the same 404 an unknown task gets (R7.3)."""
    neighbour_task = await insert_task(db_session, tenant_b, property_b, template_b)
    repo = SqlAlchemyCleaningChecklistCompletionRepository(db_session)

    with pytest.raises(CleaningTaskNotFoundError):
        await repo.upsert(
            tenant_a.id,
            CleaningChecklistCompletion(
                id=uuid.uuid4(),
                cleaning_task_id=neighbour_task.id,
                item_id="kitchen",
                completed=True,
            ),
        )

    assert await repo.list_for_task(tenant_b.id, neighbour_task.id) == []


@pytest.mark.asyncio
async def test_upsert_against_an_unknown_task_raises_the_same_error(db_session, tenant_a):
    repo = SqlAlchemyCleaningChecklistCompletionRepository(db_session)

    with pytest.raises(CleaningTaskNotFoundError):
        await repo.upsert(
            tenant_a.id,
            CleaningChecklistCompletion(
                id=uuid.uuid4(), cleaning_task_id=uuid.uuid4(), item_id="kitchen"
            ),
        )
