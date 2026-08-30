"""R2 — the cleaning loop closes in both directions (`notification-writers-gap`).

Driven through the API with the real wiring, like `test_assignment_notifications.py`, because
what R2 is about is which row reaches **which person**: a builder test cannot tell the
manager from the cleaner, and getting that backwards is the defect R2.2 exists to prevent.
"""

import logging
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.api.dependencies import get_complete_cleaning_task_use_case
from app.cleaning.application.use_cases import CleaningActor, ValidateCleaningTaskUseCase
from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.cleaning.infrastructure.repositories import SqlAlchemyCleaningTaskRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.infrastructure.repositories import (
    SqlAlchemyNotificationLogRepository,
)
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from app.notifications.domain.enums import NotificationStatus, NotificationType
from app.notifications.infrastructure.models import NotificationLogModel
from app.properties.domain.enums import PropertyOperationalState
from tests.cleaning.conftest import auth_header, insert_task
from tests.cleaning.test_tasks_api import _upload_photo

TASKS = "/api/v1/cleaning-tasks"
NOW = datetime.now(UTC)


async def _cleaner(session, tenant, *, status=UserStatus.ACTIVE):
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Limpiadora",
        email=f"cleaner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.CLEANER,
        status=status,
    )
    session.add(user)
    await session.flush()
    return user


async def _rows(db_session, tenant_id, notification_type: str) -> list:
    rows = await db_session.execute(
        select(NotificationLogModel).where(
            NotificationLogModel.tenant_id == tenant_id,
            NotificationLogModel.notification_type == notification_type,
        )
    )
    return list(rows.scalars())


@pytest_asyncio.fixture
async def completed_task(db_session, tenant_a, property_a, template_a):
    """A task already `COMPLETED`, so a validation can be recorded on it."""
    property_a.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    db_session.add(property_a)
    cleaner = await _cleaner(db_session, tenant_a)
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.COMPLETED,
        cleaner=cleaner,
    )
    await db_session.flush()
    return task, cleaner


# --- R2.2/R2.3/R2.4: the validation verdict ------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_validation_tells_the_cleaner_not_the_manager(
    api, db_session, tenant_a, users_by_role_a, completed_task
) -> None:
    """R2.2 — the whole point of the requirement, and the easy thing to get backwards.

    The manager is the one who just issued the verdict; telling them what they themselves
    decided is noise. `CLEANER` already holds `READ_OWN_NOTIFICATIONS`, so the role can read
    it.
    """
    task, cleaner = completed_task
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    response = await api.post(
        f"{TASKS}/{task.id}/validate",
        json={"validation_status": "FAILED"},
        headers=auth_header(api, manager),
    )
    assert response.status_code == 200

    rows = await _rows(db_session, tenant_a.id, NotificationType.CLEANING_FAILED.value)
    assert [row.recipient_user_id for row in rows] == [cleaner.id]
    assert rows[0].recipient_user_id != manager.id
    assert rows[0].related_id == task.id
    assert rows[0].status is NotificationStatus.PENDING
    assert rows[0].sla_deadline_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["PASSED", "WAIVED"])
async def test_a_passing_verdict_announces_nothing(
    api, db_session, tenant_a, users_by_role_a, completed_task, verdict
) -> None:
    """R2.4 — `complete()` already leaves `validation_status = PASSED` by itself, and R2.1
    already announced the completion. A second row would be noise about the same fact."""
    task, _ = completed_task

    response = await api.post(
        f"{TASKS}/{task.id}/validate",
        json={"validation_status": verdict},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assert response.status_code == 200

    assert await _rows(db_session, tenant_a.id, NotificationType.CLEANING_FAILED.value) == []


@pytest.mark.asyncio
async def test_a_failed_validation_on_an_unassigned_task_writes_nothing_and_still_succeeds(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a
) -> None:
    """R2.3 — no cleaner to address, so no row, and the validation is not failed over it."""
    property_a.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    db_session.add(property_a)
    task = await insert_task(
        db_session, tenant_a, property_a, template_a, status=CleaningTaskStatus.COMPLETED
    )
    await db_session.flush()

    response = await api.post(
        f"{TASKS}/{task.id}/validate",
        json={"validation_status": "FAILED"},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 200
    assert await _rows(db_session, tenant_a.id, NotificationType.CLEANING_FAILED.value) == []


@pytest.mark.asyncio
async def test_a_failed_validation_for_a_deactivated_cleaner_writes_nothing_and_still_succeeds(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a
) -> None:
    """Design D6 — resolved with `get_active_by_id`, not `get`.

    A cleaner who has been deactivated is not a recipient, and the case is treated exactly
    like R2.3's unassigned one: for the manager the effect is identical, because nobody is
    going to read it either way.
    """
    property_a.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    db_session.add(property_a)
    gone = await _cleaner(db_session, tenant_a, status=UserStatus.INACTIVE)
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.COMPLETED,
        cleaner=gone,
    )
    await db_session.flush()

    response = await api.post(
        f"{TASKS}/{task.id}/validate",
        json={"validation_status": "FAILED"},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 200
    assert await _rows(db_session, tenant_a.id, NotificationType.CLEANING_FAILED.value) == []


def _validate_use_case(session) -> ValidateCleaningTaskUseCase:
    """`ValidateCleaningTaskUseCase` on the raw session, deliberately **unmarked**.

    Driving this through the API would bind the session to the tenant, and the global
    listener of `app/core/db.py` would then attach `with_loader_criteria(UserModel, ...)` to
    every ORM select for the rest of the request — including the one under test. A
    regression that deleted `get_active_by_id`'s own tenant clause would be silently
    corrected by that net and the test would still pass. Building the use case here keeps the
    explicit clause as the only thing standing between the two tenants, which is what rule 1
    of `steering/security.md` actually asks a test to demonstrate.
    """
    return ValidateCleaningTaskUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        users=SqlAlchemyUserRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


@pytest.mark.asyncio
async def test_a_cleaner_of_another_tenant_is_never_told_about_this_tenants_validation(
    db_session, tenant_a, tenant_b, property_a, template_a, users_by_role_a
) -> None:
    """Rule 1 of `steering/security.md`, on the one recipient this change resolves from a row.

    `cleaning_tasks.assigned_cleaner_id` is a bare UUID with **no composite foreign key to
    `tenant_id`**, so a cross-tenant id is representable in the column — which makes
    `get_active_by_id`'s tenant clause the single thing preventing a `CLEANING_FAILED` row
    addressed to a neighbour's cleaner, whose `READ_OWN_NOTIFICATIONS` would then show them
    this tenant's task and property ids.

    **An earlier version of this test proved nothing.** It seeded a tenant-B cleaner that the
    task never referenced, so the assertion held regardless of how the recipient was
    resolved; the section-5 security and tenancy panels both caught it. This one writes the
    neighbour's id into the column, which is the collision the column shape allows.
    """
    theirs = await _cleaner(db_session, tenant_b)
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.COMPLETED,
        cleaner=theirs,
    )
    await db_session.flush()
    assert task.assigned_cleaner_id == theirs.id

    await _validate_use_case(db_session).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        status=CleaningValidationStatus.FAILED,
        actor=CleaningActor(
            user_id=users_by_role_a[UserRole.PROPERTY_MANAGER].id,
            role=UserRole.PROPERTY_MANAGER,
        ),
        now=NOW,
    )

    # Nobody is told, in either tenant: the neighbour's cleaner is not a recipient of this
    # tenant, and the row is never written under theirs either.
    assert await _rows(db_session, tenant_a.id, NotificationType.CLEANING_FAILED.value) == []
    assert await _rows(db_session, tenant_b.id, NotificationType.CLEANING_FAILED.value) == []


# --- R2.1: the completion tells the manager ------------------------------------------


async def _drive_to_completion(
    api, db_session, tenant, prop, template, manager, *, complete=True
) -> tuple:
    """Take a task through the real endpoints, optionally stopping just before the close.

    Deliberately the whole flow rather than a task inserted as `COMPLETED`: R2.1 fires from
    `CompleteCleaningTaskUseCase`, and inserting the end state would skip the code under test.

    `complete=False` stops one step short and hands back the cleaner's auth header, so a test
    can change the roster — deactivate the manager, say — **between** the work and the close.
    That ordering matters: the assignment flow needs an active actor to drive it, so a test
    that deactivated the manager up front would fail on the assignment rather than reaching
    the branch it means to exercise.
    """
    prop.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    db_session.add(prop)
    cleaner = await _cleaner(db_session, tenant)
    task = await insert_task(db_session, tenant, prop, template)
    await db_session.flush()

    await api.patch(
        f"{TASKS}/{task.id}",
        json={"assigned_cleaner_id": str(cleaner.id)},
        headers=auth_header(api, manager),
    )
    header = auth_header(api, cleaner)
    await api.post(f"{TASKS}/{task.id}/accept", headers=header)
    await api.post(f"{TASKS}/{task.id}/start", headers=header)
    for item in ("kitchen", "bathroom"):
        await api.post(f"{TASKS}/{task.id}/checklist/{item}/complete", headers=header)
    await _upload_photo(api, task.id, header)
    if not complete:
        return task, cleaner, header
    done = await api.post(f"{TASKS}/{task.id}/complete", headers=header)
    assert done.status_code == 200, done.text
    return task, cleaner


@pytest.mark.asyncio
async def test_completing_a_cleaning_tells_the_manager(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a
) -> None:
    """R2.1 — the half of PRD §11's loop that depended on somebody opening the list."""
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    task, cleaner = await _drive_to_completion(
        api, db_session, tenant_a, property_a, template_a, manager
    )

    rows = await _rows(db_session, tenant_a.id, NotificationType.CLEANING_COMPLETED.value)
    assert [row.recipient_user_id for row in rows] == [manager.id]
    assert rows[0].related_id == task.id
    assert rows[0].status is NotificationStatus.PENDING
    assert rows[0].sla_deadline_at is None
    # It goes to the manager, not back to the cleaner who just finished it.
    assert rows[0].recipient_user_id != cleaner.id


@pytest.mark.asyncio
async def test_every_active_manager_is_told_of_a_completion(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a
) -> None:
    """R5.1's plural, pinned here for the same reason section 4 pinned it for incidents:
    a regression that notified only `recipients.users[0]` would otherwise stay green."""
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    second = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="Second Manager",
        email=f"mgr-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.PROPERTY_MANAGER,
        status=UserStatus.ACTIVE,
    )
    db_session.add(second)
    await db_session.flush()

    await _drive_to_completion(
        api, db_session, tenant_a, property_a, template_a, manager
    )

    rows = await _rows(db_session, tenant_a.id, NotificationType.CLEANING_COMPLETED.value)
    assert {row.recipient_user_id for row in rows} == {manager.id, second.id}


@pytest.mark.asyncio
async def test_a_completion_falls_back_to_the_owner_when_no_manager_is_active(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a
) -> None:
    """R5.1's fallback, which task 5.6 named ("con caída al owner") and nothing pinned.

    Found by the section-5 QA panel: the implementation was correct — it goes through the
    shared `RoleRecipients.managers_or_owners` — but a regression that queried only
    `PROPERTY_MANAGER` would have passed the whole committed suite.

    The manager is deactivated **after** the task reaches `COMPLETED`, because the assignment
    flow needs an active actor to drive it; what is under test is who the completion is
    announced to, not who could perform it.
    """
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    owner = users_by_role_a[UserRole.TENANT_OWNER]
    task, _, header = await _drive_to_completion(
        api, db_session, tenant_a, property_a, template_a, manager, complete=False
    )

    await db_session.execute(
        update(UserModel)
        .where(UserModel.id == manager.id)
        .values(status=UserStatus.INACTIVE)
    )
    await db_session.flush()
    done = await api.post(f"{TASKS}/{task.id}/complete", headers=header)
    assert done.status_code == 200, done.text

    rows = await _rows(db_session, tenant_a.id, NotificationType.CLEANING_COMPLETED.value)
    assert [row.recipient_user_id for row in rows] == [owner.id]


@pytest.mark.asyncio
async def test_a_completion_with_nobody_active_still_succeeds_and_is_logged(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a, caplog
) -> None:
    """R5.2 for the completion writer: no rows, logged, and the close is not failed over it.

    A tenant in this state has finished cleanings nobody will ever validate, which is worth
    an operator's attention — and is exactly the silence the log exists to break.
    """
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    task, _, header = await _drive_to_completion(
        api, db_session, tenant_a, property_a, template_a, manager, complete=False
    )

    await db_session.execute(
        update(UserModel)
        .where(
            UserModel.tenant_id == tenant_a.id,
            UserModel.role.in_([UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER]),
        )
        .values(status=UserStatus.INACTIVE)
    )
    await db_session.flush()

    with caplog.at_level(logging.ERROR):
        done = await api.post(f"{TASKS}/{task.id}/complete", headers=header)

    assert done.status_code == 200, done.text
    assert await _rows(db_session, tenant_a.id, NotificationType.CLEANING_COMPLETED.value) == []
    assert any(
        record.message == "cleaning.completion_without_recipient"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_the_completion_row_and_the_close_reach_the_same_commit(
    db_session, tenant_a, property_a, template_a, users_by_role_a
) -> None:
    """R2.5, observed on the transaction rather than on the outcome.

    Section 4 pinned the equivalent property for the severity alert; the section-5 QA panel
    found this one unpinned. Every other R2.1 test only sees the row *after* a successful
    response, which is equally consistent with a second transaction that always happens to
    succeed — nothing in the suite injected a failure in between. This wraps the unit of work
    and asks, at `commit()`, whether the row is already there.
    """
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    cleaner = await _cleaner(db_session, tenant_a)
    property_a.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    db_session.add(property_a)
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.COMPLETED,
        cleaner=cleaner,
    )
    await db_session.flush()

    use_case = _validate_use_case(db_session)
    real_uow = use_case._uow
    seen: list[bool] = []

    class _WatchesTheCommit:
        async def commit(self) -> None:
            rows = await db_session.execute(
                select(func.count())
                .select_from(NotificationLogModel)
                .where(
                    NotificationLogModel.tenant_id == tenant_a.id,
                    NotificationLogModel.related_id == task.id,
                    NotificationLogModel.notification_type
                    == NotificationType.CLEANING_FAILED.value,
                )
            )
            seen.append(rows.scalar_one() == 1)
            await real_uow.commit()

        async def rollback(self) -> None:  # pragma: no cover - not reached here
            await real_uow.rollback()

    use_case._uow = _WatchesTheCommit()
    await use_case.execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        status=CleaningValidationStatus.FAILED,
        actor=CleaningActor(user_id=manager.id, role=UserRole.PROPERTY_MANAGER),
        now=NOW,
    )

    assert seen == [True]


@pytest.mark.asyncio
async def test_the_completion_row_and_the_completed_task_reach_the_same_commit(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a
) -> None:
    """R2.5 for the **completion** write, not just the validation one.

    The section-5 QA panel judged the validation-path spy adequate by symmetry — the two
    `execute` methods have the same shape and share one `_uow` through `_TaskLifecycleBase` —
    but R2.5 says "ambas filas", and an inference is not a test. This removes the last step:
    the spy is installed on the real `CompleteCleaningTaskUseCase` the route builds, so it
    observes the transaction the production wiring actually uses.
    """
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    task, _, header = await _drive_to_completion(
        api, db_session, tenant_a, property_a, template_a, manager, complete=False
    )

    use_case = get_complete_cleaning_task_use_case(db_session)
    real_uow = use_case._uow
    seen: list[bool] = []

    class _WatchesTheCommit:
        async def commit(self) -> None:
            rows = await db_session.execute(
                select(func.count())
                .select_from(NotificationLogModel)
                .where(
                    NotificationLogModel.tenant_id == tenant_a.id,
                    NotificationLogModel.related_id == task.id,
                    NotificationLogModel.notification_type
                    == NotificationType.CLEANING_COMPLETED.value,
                )
            )
            seen.append(rows.scalar_one() == 1)
            await real_uow.commit()

        async def rollback(self) -> None:  # pragma: no cover - not reached here
            await real_uow.rollback()

    use_case._uow = _WatchesTheCommit()
    cleaner_id = task.assigned_cleaner_id
    await use_case.execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=CleaningActor(user_id=cleaner_id, role=UserRole.CLEANER),
        now=NOW,
    )

    assert seen == [True]
