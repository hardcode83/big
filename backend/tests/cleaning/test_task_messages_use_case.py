"""R1, R3.2, R4 — `SendCleaningTaskMessageUseCase` and `ListCleaningTaskMessagesUseCase`,
against fakes of every port they hold.

No database: the scoping rule under test — `CleaningActor.restrict_to_cleaner_id`, applied by
the shared `_TaskTransitionMixin._load_task` — is a property of the use case, and the fakes
below reproduce the tenant/ownership boundary a real adapter enforces so the guard can be
proven without a session. The **real** query-level scoping of the new table is proven
separately, against Postgres, in `tests/cleaning/test_repositories.py`.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.repositories import UserFilters, UserPage
from app.cleaning.application.use_cases import (
    CleaningActor,
    ListCleaningTaskMessagesUseCase,
    SendCleaningTaskMessageUseCase,
)
from app.cleaning.domain.entities import CleaningTask, CleaningTaskMessage
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import CleaningTaskNotFoundError
from app.cleaning.domain.repositories import CleaningTaskMessagePage
from app.notifications.domain.enums import NotificationType

NOW = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
CLEANER = uuid.uuid4()
OTHER_CLEANER = uuid.uuid4()


# --- fakes ---------------------------------------------------------------------------


class FakeTaskRepository:
    """Keyed by `(tenant_id, task_id)`, exactly the pair a real adapter's `WHERE` names.

    A task registered only under `TENANT` is invisible under `OTHER_TENANT`, which is what
    lets the tenant-isolation test below stand on the same mechanism `_load_task` uses in
    production rather than on a shortcut this fake invents for itself.
    """

    def __init__(self, *tasks: tuple[uuid.UUID, CleaningTask]) -> None:
        self._tasks = {(tenant_id, task.id): task for tenant_id, task in tasks}

    async def get(self, tenant_id, task_id):
        return self._tasks.get((tenant_id, task_id))


class FakeMessageRepository:
    def __init__(self) -> None:
        self.added: list[tuple[uuid.UUID, CleaningTaskMessage]] = []

    async def add(self, tenant_id, message) -> None:
        self.added.append((tenant_id, message))

    async def list_for_task(
        self, tenant_id, task_id, *, page: int, per_page: int
    ) -> CleaningTaskMessagePage:
        matches = sorted(
            (m for t, m in self.added if t == tenant_id and m.task_id == task_id),
            key=lambda m: (m.created_at, m.id),
        )
        start = (page - 1) * per_page
        return CleaningTaskMessagePage(
            items=tuple(matches[start : start + per_page]), total=len(matches)
        )


class FakeUserRepository:
    def __init__(self, *users: User) -> None:
        self._users = list(users)

    async def list(self, tenant_id, filters: UserFilters, *, page: int, per_page: int) -> UserPage:
        matches = [
            u
            for u in self._users
            if u.tenant_id == tenant_id
            and (filters.role is None or u.role == filters.role)
            and (filters.status is None or u.status == filters.status)
        ]
        start = (page - 1) * per_page
        return UserPage(items=tuple(matches[start : start + per_page]), total=len(matches))

    async def get_active_by_id(self, tenant_id, user_id):
        for u in self._users:
            if u.tenant_id == tenant_id and u.id == user_id and u.status == UserStatus.ACTIVE:
                return u
        return None


class FakeConfigRepository:
    """Both channel flags off, so `resolve_channels` always answers `{IN_APP}` — the fan-out
    counts under test are about *recipients*, not about the channel resolver, which has its
    own suite."""

    async def get_or_create(self, tenant_id, now):
        class _Config:
            notification_email_enabled = False
            notification_whatsapp_enabled = False

        return _Config()


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.added: list[tuple[uuid.UUID, object]] = []

    async def add(self, tenant_id, log) -> None:
        self.added.append((tenant_id, log))


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


# --- builders --------------------------------------------------------------------------


def _user(tenant_id, role, *, status=UserStatus.ACTIVE, user_id=None) -> User:
    user_id = user_id or uuid.uuid4()
    return User(
        id=user_id,
        tenant_id=tenant_id,
        name=f"{role.value}-{str(user_id)[:8]}",
        email=f"{user_id}@example.com",
        password_hash="x" * 60,
        role=role,
        created_at=NOW,
        updated_at=NOW,
        status=status,
    )


def _task(
    *, tenant_id=TENANT, assigned_cleaner_id=CLEANER, status=CleaningTaskStatus.IN_PROGRESS
) -> CleaningTask:
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=uuid.uuid4(),
        checklist_template_id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        status=status,
        assigned_cleaner_id=assigned_cleaner_id,
    )


def _cleaner_actor(user_id=CLEANER) -> CleaningActor:
    return CleaningActor(user_id=user_id, role=UserRole.CLEANER)


def _manager_actor(user_id=None) -> CleaningActor:
    return CleaningActor(user_id=user_id or uuid.uuid4(), role=UserRole.PROPERTY_MANAGER)


def _send_use_case(*, task, users=(), tenant_id=TENANT):
    tasks = FakeTaskRepository((tenant_id, task))
    messages = FakeMessageRepository()
    notifications = FakeNotificationRepository()
    uow = FakeUnitOfWork()
    use_case = SendCleaningTaskMessageUseCase(
        tasks=tasks,
        messages=messages,
        users=FakeUserRepository(*users),
        configs=FakeConfigRepository(),
        notifications=notifications,
        uow=uow,
    )
    return use_case, messages, notifications, uow


# --- SendCleaningTaskMessageUseCase — R1.1, R1.3, R1.4 -------------------------------


@pytest.mark.asyncio
async def test_cleaner_sends_message_on_her_own_task_and_notifies_every_active_manager():
    task = _task(assigned_cleaner_id=CLEANER)
    manager_1 = _user(TENANT, UserRole.PROPERTY_MANAGER)
    manager_2 = _user(TENANT, UserRole.PROPERTY_MANAGER)
    inactive_manager = _user(TENANT, UserRole.PROPERTY_MANAGER, status=UserStatus.SUSPENDED)
    use_case, messages, notifications, uow = _send_use_case(
        task=task, users=[manager_1, manager_2, inactive_manager]
    )

    result = await use_case.execute(
        tenant_id=TENANT,
        task_id=task.id,
        actor=_cleaner_actor(),
        content="Falta detergente",
        now=NOW,
    )

    assert result.content == "Falta detergente"
    assert result.author_id == CLEANER
    assert result.author_role is UserRole.CLEANER
    assert [m.id for _, m in messages.added] == [result.id]

    notified = {log.recipient_user_id for _, log in notifications.added}
    assert notified == {manager_1.id, manager_2.id}
    for _, log in notifications.added:
        assert log.notification_type == NotificationType.CLEANING_TASK_MESSAGE.value
        # R3.3/design D8 — never the free text a person typed.
        assert "Falta detergente" not in (log.body or "")

    assert uow.commits == 1


@pytest.mark.asyncio
async def test_cleaner_on_someone_elses_task_raises_not_found_never_403():
    task = _task(assigned_cleaner_id=OTHER_CLEANER)
    use_case, messages, notifications, uow = _send_use_case(task=task)

    with pytest.raises(CleaningTaskNotFoundError):
        await use_case.execute(
            tenant_id=TENANT,
            task_id=task.id,
            actor=_cleaner_actor(CLEANER),
            content="hola",
            now=NOW,
        )

    assert messages.added == []
    assert notifications.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_manager_sends_message_on_any_task_and_notifies_the_assigned_cleaner():
    task = _task(assigned_cleaner_id=CLEANER)
    cleaner = _user(TENANT, UserRole.CLEANER, user_id=CLEANER)
    use_case, messages, notifications, uow = _send_use_case(task=task, users=[cleaner])

    result = await use_case.execute(
        tenant_id=TENANT,
        task_id=task.id,
        actor=_manager_actor(),
        content="¿Cómo va la limpieza?",
        now=NOW,
    )

    assert [m.id for _, m in messages.added] == [result.id]
    assert len(notifications.added) == 1
    _, log = notifications.added[0]
    assert log.recipient_user_id == CLEANER
    assert log.notification_type == NotificationType.CLEANING_TASK_MESSAGE.value
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_manager_message_on_an_unassigned_task_persists_and_notifies_nobody():
    task = _task(assigned_cleaner_id=None)
    use_case, messages, notifications, uow = _send_use_case(task=task)

    result = await use_case.execute(
        tenant_id=TENANT,
        task_id=task.id,
        actor=_manager_actor(),
        content="Nota para cuando se asigne",
        now=NOW,
    )

    assert [m.id for _, m in messages.added] == [result.id]
    assert notifications.added == []
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_manager_message_on_a_task_with_inactive_cleaner_persists_and_notifies_nobody():
    """R4.3 mirror — the assigned cleaner exists but is no longer active (suspended), so
    `get_active_by_id` returns `None`. The message must still persist and the transaction
    must still commit; only the notification is skipped."""
    inactive_cleaner = _user(TENANT, UserRole.CLEANER, status=UserStatus.SUSPENDED, user_id=CLEANER)
    task = _task(assigned_cleaner_id=CLEANER)
    use_case, messages, notifications, uow = _send_use_case(task=task, users=[inactive_cleaner])

    result = await use_case.execute(
        tenant_id=TENANT,
        task_id=task.id,
        actor=_manager_actor(),
        content="¿Sigues ahí?",
        now=NOW,
    )

    assert [m.id for _, m in messages.added] == [result.id]
    assert notifications.added == []
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_cleaner_message_with_no_active_manager_persists_and_notifies_nobody():
    task = _task(assigned_cleaner_id=CLEANER)
    use_case, messages, notifications, uow = _send_use_case(task=task, users=[])

    result = await use_case.execute(
        tenant_id=TENANT,
        task_id=task.id,
        actor=_cleaner_actor(),
        content="¿Hay alguien ahí?",
        now=NOW,
    )

    assert [m.id for _, m in messages.added] == [result.id]
    assert notifications.added == []
    assert uow.commits == 1


# --- ListCleaningTaskMessagesUseCase — R1.2 -------------------------------------------


def _list_use_case(*, tasks: FakeTaskRepository, messages: FakeMessageRepository):
    return ListCleaningTaskMessagesUseCase(tasks=tasks, messages=messages)


@pytest.mark.asyncio
async def test_list_returns_messages_in_chronological_order():
    task = _task(assigned_cleaner_id=CLEANER)
    messages = FakeMessageRepository()
    ordered_ids = []
    for i in (2, 0, 1):  # inserted out of order
        message = CleaningTaskMessage(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            task_id=task.id,
            author_id=CLEANER,
            author_role=UserRole.CLEANER,
            content=f"mensaje {i}",
            created_at=datetime(2026, 8, 8, 10, i, tzinfo=UTC),
        )
        await messages.add(TENANT, message)
        ordered_ids.append((i, message.id))
    expected_order = [mid for _, mid in sorted(ordered_ids)]

    use_case = _list_use_case(tasks=FakeTaskRepository((TENANT, task)), messages=messages)
    page = await use_case.execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner_actor(), page=1, per_page=10
    )

    assert [m.id for m in page.items] == expected_order
    assert page.total == 3


@pytest.mark.asyncio
async def test_list_paginates():
    task = _task(assigned_cleaner_id=CLEANER)
    messages = FakeMessageRepository()
    for i in range(3):
        await messages.add(
            TENANT,
            CleaningTaskMessage(
                id=uuid.uuid4(),
                tenant_id=TENANT,
                task_id=task.id,
                author_id=CLEANER,
                author_role=UserRole.CLEANER,
                content=f"mensaje {i}",
                created_at=datetime(2026, 8, 8, 10, i, tzinfo=UTC),
            ),
        )
    use_case = _list_use_case(tasks=FakeTaskRepository((TENANT, task)), messages=messages)

    first = await use_case.execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner_actor(), page=1, per_page=2
    )
    second = await use_case.execute(
        tenant_id=TENANT, task_id=task.id, actor=_cleaner_actor(), page=2, per_page=2
    )

    assert len(first.items) == 2
    assert len(second.items) == 1
    assert first.total == second.total == 3


@pytest.mark.asyncio
async def test_cleaner_cannot_list_a_task_that_is_not_hers():
    task = _task(assigned_cleaner_id=OTHER_CLEANER)
    use_case = _list_use_case(
        tasks=FakeTaskRepository((TENANT, task)), messages=FakeMessageRepository()
    )

    with pytest.raises(CleaningTaskNotFoundError):
        await use_case.execute(
            tenant_id=TENANT, task_id=task.id, actor=_cleaner_actor(CLEANER), page=1, per_page=10
        )


@pytest.mark.asyncio
async def test_manager_sees_the_full_thread_of_any_task():
    task = _task(assigned_cleaner_id=OTHER_CLEANER)
    messages = FakeMessageRepository()
    await messages.add(
        TENANT,
        CleaningTaskMessage(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            task_id=task.id,
            author_id=OTHER_CLEANER,
            author_role=UserRole.CLEANER,
            content="hola",
            created_at=NOW,
        ),
    )
    use_case = _list_use_case(tasks=FakeTaskRepository((TENANT, task)), messages=messages)

    page = await use_case.execute(
        tenant_id=TENANT, task_id=task.id, actor=_manager_actor(), page=1, per_page=10
    )

    assert page.total == 1


@pytest.mark.asyncio
async def test_a_task_of_another_tenant_is_invisible_to_this_tenants_actor():
    """R3.2, steering/security.md rule 1 — the tenant isolation test this new use case owes
    the module's DoD (`steering/testing.md` §28.18), distinct from any existing variant: no
    other test in this file crosses `TENANT`/`OTHER_TENANT`.

    Uses the same `_load_task` guard every other `cleaning` use case relies on: the task is
    registered only under `OTHER_TENANT`, so looking it up under `TENANT` must be
    indistinguishable from an id that never existed — never an empty page, which would tell
    an unauthorised caller that the id resolves to *something*.
    """
    neighbour_task = _task(tenant_id=OTHER_TENANT, assigned_cleaner_id=CLEANER)
    messages = FakeMessageRepository()
    await messages.add(
        OTHER_TENANT,
        CleaningTaskMessage(
            id=uuid.uuid4(),
            tenant_id=OTHER_TENANT,
            task_id=neighbour_task.id,
            author_id=CLEANER,
            author_role=UserRole.CLEANER,
            content="secreto del tenant vecino",
            created_at=NOW,
        ),
    )
    use_case = _list_use_case(
        tasks=FakeTaskRepository((OTHER_TENANT, neighbour_task)), messages=messages
    )

    with pytest.raises(CleaningTaskNotFoundError):
        await use_case.execute(
            tenant_id=TENANT,
            task_id=neighbour_task.id,
            actor=_manager_actor(),
            page=1,
            per_page=10,
        )
