"""R7.1, R7.5 — the adapters, and the isolation they are solely responsible for.

`cleaning_checklist_completions` has no `tenant_id` and is not covered by
`tenant_scoped_classes()` (`app/core/db.py:62`), so the `JOIN` its adapter performs is the
entire isolation mechanism. Those tests are not a formality: nothing else would catch a
regression there.

**`cleaning_photos` is the second table in that position** (change `cleaning-photos-storage`,
R6.1/R6.2, design D12), and the tests at the bottom of this file are modelled on the
completion ones deliberately — same table shape, same missing net, same obligation to prove
the join rather than assume it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.cleaning.domain.entities import (
    CleaningChecklistCompletion,
    CleaningPhoto,
    CleaningTask,
    CleaningTaskMessage,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    CleaningTaskNotFoundError,
    DuplicateLiveCleaningTaskError,
)
from app.cleaning.domain.repositories import CleaningTaskFilters
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistCompletionRepository,
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningPhotoRepository,
    SqlAlchemyCleaningTaskMessageRepository,
    SqlAlchemyCleaningTaskRepository,
    SqlAlchemyUnscopedCleaningPhotoLocationQuery,
)
from app.core.db import bind_session_to_tenant
from app.core.tenancy import CrossTenantWriteError, TenantMarkedSessionError
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


# --- operational KPI counts (`dashboard-operational-kpis` R1) ---------------------


@pytest.mark.asyncio
async def test_count_live_for_day_counts_only_live_statuses_scheduled_today(
    db_session, tenant_a, property_a, template_a
):
    today = datetime.now(UTC).date()
    for status in (
        CleaningTaskStatus.CREATED,
        CleaningTaskStatus.ASSIGNED,
        CleaningTaskStatus.ACCEPTED,
        CleaningTaskStatus.IN_PROGRESS,
    ):
        await insert_task(
            db_session,
            tenant_a,
            property_a,
            template_a,
            status=status,
            scheduled_start=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
        )
    for status in (
        CleaningTaskStatus.COMPLETED,
        CleaningTaskStatus.CANCELLED,
        CleaningTaskStatus.REJECTED,
        CleaningTaskStatus.FAILED,
    ):
        await insert_task(
            db_session,
            tenant_a,
            property_a,
            template_a,
            status=status,
            scheduled_start=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
        )

    repo = SqlAlchemyCleaningTaskRepository(db_session)
    assert await repo.count_live_for_day(tenant_a.id, today) == 4


@pytest.mark.asyncio
async def test_count_live_for_day_excludes_other_days_and_returns_zero_when_none(
    db_session, tenant_a, property_a, template_a
):
    today = datetime.now(UTC).date()
    repo = SqlAlchemyCleaningTaskRepository(db_session)
    assert await repo.count_live_for_day(tenant_a.id, today) == 0

    await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        scheduled_start=datetime.combine(
            today - timedelta(days=1), datetime.min.time(), tzinfo=UTC
        ),
    )
    await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        scheduled_start=datetime.combine(
            today + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        ),
    )

    assert await repo.count_live_for_day(tenant_a.id, today) == 0


@pytest.mark.asyncio
async def test_count_live_for_day_never_counts_another_tenant(
    db_session, tenant_a, tenant_b, property_b, template_b
):
    today = datetime.now(UTC).date()
    await insert_task(
        db_session,
        tenant_b,
        property_b,
        template_b,
        scheduled_start=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
    )

    repo = SqlAlchemyCleaningTaskRepository(db_session)
    assert await repo.count_live_for_day(tenant_a.id, today) == 0


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


# --- photos: the second table with no net (R6.1, R6.2, design D12) -----------------
#
# Modelled on the completion tests above, because it is the same situation: no `tenant_id`
# column, so `tenant_scoped_classes()` (`app/core/db.py:62`) never hands it to
# `with_loader_criteria`, and the `JOIN cleaning_tasks` in every statement of
# `SqlAlchemyCleaningPhotoRepository` is the entire isolation mechanism. R6.1 says it
# outright: the isolation is derived from the join, not inherited from the global filter.


def _photo(task, uploader, *, photo_type="kitchen", created_at=NOW) -> CleaningPhoto:
    photo_id = uuid.uuid4()
    return CleaningPhoto(
        id=photo_id,
        cleaning_task_id=task.id,
        uploaded_by=uploader.id,
        photo_type=photo_type,
        # Shaped like `storage_key_for_photo` (design D3) without importing it: these tests
        # are about the repository, and section 1's key builder has its own.
        storage_key=f"tenants/{task.tenant_id}/cleaning-tasks/{task.id}/{photo_id}.jpg",
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_photo_add_and_read_back_round_trip(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    cleaner = users_by_role_a[UserRole.CLEANER]
    repo = SqlAlchemyCleaningPhotoRepository(db_session)
    photo = _photo(task, cleaner)

    await repo.add(tenant_a.id, photo)

    fetched = await repo.get(tenant_a.id, photo.id)
    assert fetched is not None
    assert fetched.storage_key == photo.storage_key
    assert fetched.uploaded_by == cleaner.id
    assert [found.id for found in await repo.list_for_task(tenant_a.id, task.id)] == [photo.id]
    assert await repo.uploaded_photo_types(tenant_a.id, task.id) == frozenset({"kitchen"})


@pytest.mark.asyncio
async def test_uploaded_photo_types_collapses_repeats_of_the_same_type(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """R2.6 admits several photos of one type; design D8 asks only whether one exists."""
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    cleaner = users_by_role_a[UserRole.CLEANER]
    repo = SqlAlchemyCleaningPhotoRepository(db_session)

    await repo.add(tenant_a.id, _photo(task, cleaner, photo_type="bathroom"))
    await repo.add(tenant_a.id, _photo(task, cleaner, photo_type="bathroom"))
    await repo.add(tenant_a.id, _photo(task, cleaner, photo_type="kitchen"))

    assert await repo.uploaded_photo_types(tenant_a.id, task.id) == frozenset(
        {"bathroom", "kitchen"}
    )
    assert len(await repo.list_for_task(tenant_a.id, task.id)) == 3


@pytest.mark.asyncio
async def test_add_writes_the_entitys_created_at_and_not_the_transaction_clock(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """The upload's instant, not `now()` — and nothing pinned this until it was lost.

    `cleaning_photos.created_at` has a `server_default`, so omitting the column from the
    insert still produces a row and every test here still passes; the difference only shows
    up as ordering. Postgres `now()` is the *transaction* timestamp, so photos inserted
    together would share one instant and `list_for_task`'s `created_at, id` ordering would
    fall through to a random `uuid4` — stable between reads, but not upload order.

    Written after a reviewer's `git checkout --` destroyed this adapter and the
    reconstruction silently dropped the column: eight isolation tests stayed green through
    a real behaviour change, which is exactly the gap this closes.
    """
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    repo = SqlAlchemyCleaningPhotoRepository(db_session)
    photo = _photo(task, users_by_role_a[UserRole.CLEANER])

    await repo.add(tenant_a.id, photo)

    stored = await repo.get(tenant_a.id, photo.id)
    assert stored is not None
    assert stored.created_at == photo.created_at


@pytest.mark.asyncio
async def test_add_does_not_write_the_ai_validation_result(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """`ai_validation_result` is out of scope: the column keeps waiting for `messaging-ai`.

    Same shape as `test_save_does_not_write_notes` above — a column this change deliberately
    does not open a write path to, pinned so that adding one is a decision and not a diff.
    """
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    repo = SqlAlchemyCleaningPhotoRepository(db_session)
    photo = _photo(task, users_by_role_a[UserRole.CLEANER])
    photo.ai_validation_result = {"verdict": "clean"}

    await repo.add(tenant_a.id, photo)

    assert (await repo.get(tenant_a.id, photo.id)).ai_validation_result is None


@pytest.mark.asyncio
async def test_a_photo_of_another_tenant_is_unreachable_by_get(
    db_session, tenant_a, tenant_b, property_b, template_b, users_by_role_b
):
    """R6.2 — knowing the UUID is not access, which is the only thing `get` can get wrong."""
    from app.auth.domain.enums import UserRole

    neighbour_task = await insert_task(db_session, tenant_b, property_b, template_b)
    repo = SqlAlchemyCleaningPhotoRepository(db_session)
    photo = _photo(neighbour_task, users_by_role_b[UserRole.CLEANER])
    await repo.add(tenant_b.id, photo)

    # The real identifier of a real row, handed straight to the neighbour's tenant.
    assert await repo.get(tenant_a.id, photo.id) is None
    # And it is still there for its owner — the test would also pass if nothing was written.
    assert await repo.get(tenant_b.id, photo.id) is not None


@pytest.mark.asyncio
async def test_photos_of_another_tenant_are_invisible_to_list_for_task(
    db_session, tenant_a, tenant_b, property_b, template_b, users_by_role_b
):
    """R6.2 — and again with the neighbour's real task id, not an invented one."""
    from app.auth.domain.enums import UserRole

    neighbour_task = await insert_task(db_session, tenant_b, property_b, template_b)
    repo = SqlAlchemyCleaningPhotoRepository(db_session)
    await repo.add(tenant_b.id, _photo(neighbour_task, users_by_role_b[UserRole.CLEANER]))

    assert await repo.list_for_task(tenant_a.id, neighbour_task.id) == []
    assert len(await repo.list_for_task(tenant_b.id, neighbour_task.id)) == 1


@pytest.mark.asyncio
async def test_photo_types_of_another_tenant_are_invisible(
    db_session, tenant_a, tenant_b, property_b, template_b, users_by_role_b
):
    """R6.2 on the path that feeds PRD §11's third clause (design D8).

    A leak here would not read a photo, it would let one tenant's uploads satisfy another
    tenant's completion rule — so it needs its own probe rather than trusting `get`'s.
    """
    from app.auth.domain.enums import UserRole

    neighbour_task = await insert_task(db_session, tenant_b, property_b, template_b)
    repo = SqlAlchemyCleaningPhotoRepository(db_session)
    await repo.add(tenant_b.id, _photo(neighbour_task, users_by_role_b[UserRole.CLEANER]))

    assert await repo.uploaded_photo_types(tenant_a.id, neighbour_task.id) == frozenset()
    assert await repo.uploaded_photo_types(tenant_b.id, neighbour_task.id) == frozenset(
        {"kitchen"}
    )


@pytest.mark.asyncio
async def test_a_photo_cannot_be_added_to_another_tenants_task(
    db_session, tenant_a, tenant_b, property_b, template_b, users_by_role_b
):
    """R6.3 — the write path answers what an unknown task answers, and writes nothing."""
    from app.auth.domain.enums import UserRole

    neighbour_task = await insert_task(db_session, tenant_b, property_b, template_b)
    repo = SqlAlchemyCleaningPhotoRepository(db_session)

    with pytest.raises(CleaningTaskNotFoundError):
        await repo.add(tenant_a.id, _photo(neighbour_task, users_by_role_b[UserRole.CLEANER]))

    assert await repo.list_for_task(tenant_b.id, neighbour_task.id) == []


@pytest.mark.asyncio
async def test_adding_a_photo_to_an_unknown_task_raises_the_same_error(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """R6.3 — indistinguishable from the cross-tenant case, one level below the status code."""
    from app.auth.domain.enums import UserRole

    stand_in = await insert_task(db_session, tenant_a, property_a, template_a)
    photo = _photo(stand_in, users_by_role_a[UserRole.CLEANER])
    photo.cleaning_task_id = uuid.uuid4()

    with pytest.raises(CleaningTaskNotFoundError):
        await SqlAlchemyCleaningPhotoRepository(db_session).add(tenant_a.id, photo)


@pytest.mark.asyncio
async def test_the_unscoped_photo_location_resolves_the_tenant_out_of_the_row(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """The anonymous serving route's read: no tenant in, the tenant comes out (design D7b)."""
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    photo = _photo(task, users_by_role_a[UserRole.CLEANER])
    await SqlAlchemyCleaningPhotoRepository(db_session).add(tenant_a.id, photo)
    await db_session.flush()

    located = await SqlAlchemyUnscopedCleaningPhotoLocationQuery(
        db_session
    ).locate_without_tenant_scoping(photo.id)

    assert located is not None
    assert located.tenant_id == tenant_a.id
    assert located.storage_key == photo.storage_key


@pytest.mark.asyncio
async def test_the_unscoped_photo_location_refuses_a_marked_session(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """R6.2/R6.3: the session contract of this query, executable.

    Asserting the raise and not the absence of a row is the whole point here. On a marked
    session the listener scopes the `JOIN cleaning_tasks`, so the query would come back empty
    for every photo of every other tenant — and an empty result is what an unknown photo id
    returns, so a silent failure would be reported as a broken signature instead of as the
    wiring mistake it is.
    """
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    photo = _photo(task, users_by_role_a[UserRole.CLEANER])
    await SqlAlchemyCleaningPhotoRepository(db_session).add(tenant_a.id, photo)
    await db_session.flush()
    bind_session_to_tenant(db_session, tenant_a.id)

    with pytest.raises(TenantMarkedSessionError, match="locate_without_tenant_scoping"):
        await SqlAlchemyUnscopedCleaningPhotoLocationQuery(
            db_session
        ).locate_without_tenant_scoping(photo.id)


# --- `cleaning_task_messages` -------------------------------------------------------
#
# `staff-messaging` R1, R3.2, design D1. Unlike `cleaning_photos`/`cleaning_checklist_
# completions` above, this table carries its own `tenant_id` and is a member of
# `tenant_scoped_classes()`, so `SqlAlchemyCleaningTaskMessageRepository` filters it
# directly instead of joining `cleaning_tasks` — the `SqlAlchemyIncidentPhotoRepository`
# shape. `add` still guards explicitly (limit 3 of `app/core/db.py`: the global filter
# never covers INSERTs), which is what these tests exercise.


def _message(task, author, *, content="Falta detergente en el 3ºB", created_at=NOW):
    return CleaningTaskMessage(
        id=uuid.uuid4(),
        tenant_id=task.tenant_id,
        task_id=task.id,
        author_id=author.id,
        author_role=author.role,
        content=content,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_message_add_and_list_round_trip(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    cleaner = users_by_role_a[UserRole.CLEANER]
    repo = SqlAlchemyCleaningTaskMessageRepository(db_session)
    message = _message(task, cleaner)

    await repo.add(tenant_a.id, message)

    page = await repo.list_for_task(tenant_a.id, task.id, page=1, per_page=20)
    assert page.total == 1
    assert page.items[0].id == message.id
    assert page.items[0].content == message.content
    assert page.items[0].author_id == cleaner.id
    assert page.items[0].author_role is UserRole.CLEANER


@pytest.mark.asyncio
async def test_message_list_is_chronological_and_paginated(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    cleaner = users_by_role_a[UserRole.CLEANER]
    repo = SqlAlchemyCleaningTaskMessageRepository(db_session)
    messages = [
        _message(task, cleaner, content=f"mensaje {i}", created_at=NOW + timedelta(minutes=i))
        for i in range(3)
    ]
    # Inserted out of order, so a bug that trusted insertion order rather than `created_at`
    # would be caught.
    for message in (messages[2], messages[0], messages[1]):
        await repo.add(tenant_a.id, message)

    first_page = await repo.list_for_task(tenant_a.id, task.id, page=1, per_page=2)
    assert [m.id for m in first_page.items] == [messages[0].id, messages[1].id]
    assert first_page.total == 3

    second_page = await repo.list_for_task(tenant_a.id, task.id, page=2, per_page=2)
    assert [m.id for m in second_page.items] == [messages[2].id]


@pytest.mark.asyncio
async def test_message_order_ties_break_on_id_not_insertion_order(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """`ORDER BY created_at, id` (design D1) needs its own test: two messages sharing a
    `created_at` (a burst written within the same clock tick) must still come back in a
    stable order — by `id`, not by whichever happened to be inserted first."""
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    cleaner = users_by_role_a[UserRole.CLEANER]
    repo = SqlAlchemyCleaningTaskMessageRepository(db_session)
    messages = sorted(
        (_message(task, cleaner, content=f"mensaje {i}") for i in range(3)),
        key=lambda m: m.id,
    )
    # Inserted in the reverse of id order, so a bug that fell back to insertion order for
    # the tie would be caught.
    for message in reversed(messages):
        await repo.add(tenant_a.id, message)

    page = await repo.list_for_task(tenant_a.id, task.id, page=1, per_page=20)

    assert [m.id for m in page.items] == [m.id for m in messages]


@pytest.mark.asyncio
async def test_message_add_refuses_an_entity_of_another_tenant(
    db_session, tenant_a, tenant_b, property_a, template_a, users_by_role_a
):
    """R3.2 — the write-side guard: limit 3 of `app/core/db.py` says INSERTs are not covered
    by the session's global filter, so this explicit check is the only thing standing between
    a wiring mistake and a row of another tenant."""
    task = await insert_task(db_session, tenant_a, property_a, template_a)
    from app.auth.domain.enums import UserRole

    message = _message(task, users_by_role_a[UserRole.CLEANER])
    repo = SqlAlchemyCleaningTaskMessageRepository(db_session)

    with pytest.raises(CrossTenantWriteError):
        await repo.add(tenant_b.id, message)


@pytest.mark.asyncio
async def test_messages_of_another_tenant_are_invisible_to_list_for_task(
    db_session, tenant_a, tenant_b, property_b, template_b, users_by_role_b
):
    """R3.2/steering-security rule 1 — a tenant cannot read another tenant's thread, even
    when it names the neighbour's real task id.

    This is the isolation test the module's DoD (`steering/testing.md` §28.18) requires: a
    new one, not a variant of an existing table's, because `cleaning_task_messages` is scoped
    by its own `tenant_id` column rather than by a join, and nothing above exercises that.
    """
    from app.auth.domain.enums import UserRole

    neighbour_task = await insert_task(db_session, tenant_b, property_b, template_b)
    repo = SqlAlchemyCleaningTaskMessageRepository(db_session)
    await repo.add(tenant_b.id, _message(neighbour_task, users_by_role_b[UserRole.CLEANER]))

    leaked = await repo.list_for_task(tenant_a.id, neighbour_task.id, page=1, per_page=20)
    assert leaked.items == ()
    assert leaked.total == 0

    # And it is still there for its owner — the test would also pass if nothing was written.
    owned = await repo.list_for_task(tenant_b.id, neighbour_task.id, page=1, per_page=20)
    assert owned.total == 1


@pytest.mark.asyncio
async def test_message_created_at_is_written_and_not_left_to_the_transaction_clock(
    db_session, tenant_a, property_a, template_a, users_by_role_a
):
    """`cleaning_task_messages.created_at` has no `server_default` (design D1): a burst of
    messages inserted together would otherwise share one Postgres `now()` and collapse the
    chronological order the thread is read in."""
    from app.auth.domain.enums import UserRole

    task = await insert_task(db_session, tenant_a, property_a, template_a)
    repo = SqlAlchemyCleaningTaskMessageRepository(db_session)
    sent_at = NOW - timedelta(days=1)
    message = _message(task, users_by_role_a[UserRole.CLEANER], created_at=sent_at)

    await repo.add(tenant_a.id, message)

    page = await repo.list_for_task(tenant_a.id, task.id, page=1, per_page=10)
    assert page.items[0].created_at == sent_at
