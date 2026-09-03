"""R2, R3.2, R4 — `SendIncidentMessageUseCase` and `ListIncidentMessagesUseCase`, against
fakes of every port they hold.

The mirror of `tests/cleaning/test_task_messages_use_case.py`. No database: the scoping rule
under test — `IncidentActor.restrict_to_technician_id`, applied by the shared module-level
`_load_incident_in_scope` — is a property of the use case, and the fakes below reproduce the
tenant/ownership boundary a real adapter enforces so the guard can be proven without a
session. The **real** query-level scoping of the new table is proven separately, against
Postgres, in `tests/maintenance/test_repositories.py`.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.repositories import UserFilters, UserPage
from app.maintenance.application.use_cases import (
    IncidentActor,
    ListIncidentMessagesUseCase,
    SendIncidentMessageUseCase,
)
from app.maintenance.domain.entities import Incident, IncidentMessage
from app.maintenance.domain.enums import IncidentSource, IncidentStatus
from app.maintenance.domain.exceptions import IncidentNotFoundError
from app.maintenance.domain.repositories import IncidentMessagePage
from app.notifications.domain.enums import NotificationType

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
TECHNICIAN = uuid.uuid4()
OTHER_TECHNICIAN = uuid.uuid4()


# --- fakes ---------------------------------------------------------------------------


class FakeIncidentRepository:
    """Keyed by `(tenant_id, incident_id)`, exactly the pair a real adapter's `WHERE` names.

    An incident registered only under `TENANT` is invisible under `OTHER_TENANT`, which is
    what lets the tenant-isolation test below stand on the same mechanism
    `_load_incident_in_scope` uses in production rather than on a shortcut this fake invents
    for itself.
    """

    def __init__(self, *incidents: tuple[uuid.UUID, Incident]) -> None:
        self._incidents = {
            (tenant_id, incident.id): incident for tenant_id, incident in incidents
        }

    async def get(self, tenant_id, incident_id):
        return self._incidents.get((tenant_id, incident_id))


class FakeMessageRepository:
    def __init__(self) -> None:
        self.added: list[tuple[uuid.UUID, IncidentMessage]] = []

    async def add(self, tenant_id, message) -> None:
        self.added.append((tenant_id, message))

    async def list_for_incident(
        self, tenant_id, incident_id, *, page: int, per_page: int
    ) -> IncidentMessagePage:
        matches = sorted(
            (m for t, m in self.added if t == tenant_id and m.incident_id == incident_id),
            key=lambda m: (m.created_at, m.id),
        )
        start = (page - 1) * per_page
        return IncidentMessagePage(
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


def _incident(
    *, tenant_id=TENANT, assigned_technician_id=TECHNICIAN, status=IncidentStatus.IN_PROGRESS
) -> Incident:
    return Incident(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=uuid.uuid4(),
        source=IncidentSource.CLEANER,
        title="Broken AC",
        description="The AC unit is not cooling.",
        created_at=NOW,
        updated_at=NOW,
        status=status,
        assigned_technician_id=assigned_technician_id,
    )


def _technician_actor(user_id=TECHNICIAN) -> IncidentActor:
    return IncidentActor(user_id=user_id, role=UserRole.TECHNICIAN)


def _manager_actor(user_id=None) -> IncidentActor:
    return IncidentActor(user_id=user_id or uuid.uuid4(), role=UserRole.PROPERTY_MANAGER)


def _send_use_case(*, incident, users=(), tenant_id=TENANT):
    incidents = FakeIncidentRepository((tenant_id, incident))
    messages = FakeMessageRepository()
    notifications = FakeNotificationRepository()
    uow = FakeUnitOfWork()
    use_case = SendIncidentMessageUseCase(
        incidents=incidents,
        messages=messages,
        users=FakeUserRepository(*users),
        configs=FakeConfigRepository(),
        notifications=notifications,
        uow=uow,
    )
    return use_case, messages, notifications, uow


# --- SendIncidentMessageUseCase — R2.1, R2.3, R2.4 ------------------------------------


@pytest.mark.asyncio
async def test_technician_sends_message_on_her_own_incident_and_notifies_every_active_manager():
    incident = _incident(assigned_technician_id=TECHNICIAN)
    manager_1 = _user(TENANT, UserRole.PROPERTY_MANAGER)
    manager_2 = _user(TENANT, UserRole.PROPERTY_MANAGER)
    inactive_manager = _user(TENANT, UserRole.PROPERTY_MANAGER, status=UserStatus.SUSPENDED)
    use_case, messages, notifications, uow = _send_use_case(
        incident=incident, users=[manager_1, manager_2, inactive_manager]
    )

    result = await use_case.execute(
        tenant_id=TENANT,
        incident_id=incident.id,
        actor=_technician_actor(),
        content="Falta la pieza de recambio",
        now=NOW,
    )

    assert result.content == "Falta la pieza de recambio"
    assert result.author_id == TECHNICIAN
    assert result.author_role is UserRole.TECHNICIAN
    assert [m.id for _, m in messages.added] == [result.id]

    notified = {log.recipient_user_id for _, log in notifications.added}
    assert notified == {manager_1.id, manager_2.id}
    for _, log in notifications.added:
        assert log.notification_type == NotificationType.INCIDENT_MESSAGE.value
        # R3.3/design D8 — never the free text a person typed.
        assert "Falta la pieza de recambio" not in (log.body or "")

    assert uow.commits == 1


@pytest.mark.asyncio
async def test_technician_on_someone_elses_incident_raises_not_found_never_403():
    incident = _incident(assigned_technician_id=OTHER_TECHNICIAN)
    use_case, messages, notifications, uow = _send_use_case(incident=incident)

    with pytest.raises(IncidentNotFoundError):
        await use_case.execute(
            tenant_id=TENANT,
            incident_id=incident.id,
            actor=_technician_actor(TECHNICIAN),
            content="hola",
            now=NOW,
        )

    assert messages.added == []
    assert notifications.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_manager_sends_message_on_any_incident_and_notifies_the_assigned_technician():
    incident = _incident(assigned_technician_id=TECHNICIAN)
    technician = _user(TENANT, UserRole.TECHNICIAN, user_id=TECHNICIAN)
    use_case, messages, notifications, uow = _send_use_case(
        incident=incident, users=[technician]
    )

    result = await use_case.execute(
        tenant_id=TENANT,
        incident_id=incident.id,
        actor=_manager_actor(),
        content="¿Cómo va la reparación?",
        now=NOW,
    )

    assert [m.id for _, m in messages.added] == [result.id]
    assert len(notifications.added) == 1
    _, log = notifications.added[0]
    assert log.recipient_user_id == TECHNICIAN
    assert log.notification_type == NotificationType.INCIDENT_MESSAGE.value
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_manager_message_on_an_unassigned_incident_persists_and_notifies_nobody():
    incident = _incident(assigned_technician_id=None)
    use_case, messages, notifications, uow = _send_use_case(incident=incident)

    result = await use_case.execute(
        tenant_id=TENANT,
        incident_id=incident.id,
        actor=_manager_actor(),
        content="Nota para cuando se asigne",
        now=NOW,
    )

    assert [m.id for _, m in messages.added] == [result.id]
    assert notifications.added == []
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_manager_message_on_an_incident_with_inactive_technician_persists_and_notifies_nobody():
    """R4.3 mirror — the assigned technician exists but is no longer active (suspended), so
    `get_active_by_id` returns `None`. The message must still persist and the transaction
    must still commit; only the notification is skipped."""
    inactive_technician = _user(
        TENANT, UserRole.TECHNICIAN, status=UserStatus.SUSPENDED, user_id=TECHNICIAN
    )
    incident = _incident(assigned_technician_id=TECHNICIAN)
    use_case, messages, notifications, uow = _send_use_case(
        incident=incident, users=[inactive_technician]
    )

    result = await use_case.execute(
        tenant_id=TENANT,
        incident_id=incident.id,
        actor=_manager_actor(),
        content="¿Sigues ahí?",
        now=NOW,
    )

    assert [m.id for _, m in messages.added] == [result.id]
    assert notifications.added == []
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_technician_message_with_no_active_manager_persists_and_notifies_nobody():
    incident = _incident(assigned_technician_id=TECHNICIAN)
    use_case, messages, notifications, uow = _send_use_case(incident=incident, users=[])

    result = await use_case.execute(
        tenant_id=TENANT,
        incident_id=incident.id,
        actor=_technician_actor(),
        content="¿Hay alguien ahí?",
        now=NOW,
    )

    assert [m.id for _, m in messages.added] == [result.id]
    assert notifications.added == []
    assert uow.commits == 1


# --- ListIncidentMessagesUseCase — R2.2 ------------------------------------------------


def _list_use_case(*, incidents: FakeIncidentRepository, messages: FakeMessageRepository):
    return ListIncidentMessagesUseCase(incidents=incidents, messages=messages)


@pytest.mark.asyncio
async def test_list_returns_messages_in_chronological_order():
    incident = _incident(assigned_technician_id=TECHNICIAN)
    messages = FakeMessageRepository()
    ordered_ids = []
    for i in (2, 0, 1):  # inserted out of order
        message = IncidentMessage(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            incident_id=incident.id,
            author_id=TECHNICIAN,
            author_role=UserRole.TECHNICIAN,
            content=f"mensaje {i}",
            created_at=datetime(2026, 9, 2, 10, i, tzinfo=UTC),
        )
        await messages.add(TENANT, message)
        ordered_ids.append((i, message.id))
    expected_order = [mid for _, mid in sorted(ordered_ids)]

    use_case = _list_use_case(
        incidents=FakeIncidentRepository((TENANT, incident)), messages=messages
    )
    page = await use_case.execute(
        tenant_id=TENANT, incident_id=incident.id, actor=_technician_actor(), page=1, per_page=10
    )

    assert [m.id for m in page.items] == expected_order
    assert page.total == 3


@pytest.mark.asyncio
async def test_list_paginates():
    incident = _incident(assigned_technician_id=TECHNICIAN)
    messages = FakeMessageRepository()
    for i in range(3):
        await messages.add(
            TENANT,
            IncidentMessage(
                id=uuid.uuid4(),
                tenant_id=TENANT,
                incident_id=incident.id,
                author_id=TECHNICIAN,
                author_role=UserRole.TECHNICIAN,
                content=f"mensaje {i}",
                created_at=datetime(2026, 9, 2, 10, i, tzinfo=UTC),
            ),
        )
    use_case = _list_use_case(
        incidents=FakeIncidentRepository((TENANT, incident)), messages=messages
    )

    first = await use_case.execute(
        tenant_id=TENANT, incident_id=incident.id, actor=_technician_actor(), page=1, per_page=2
    )
    second = await use_case.execute(
        tenant_id=TENANT, incident_id=incident.id, actor=_technician_actor(), page=2, per_page=2
    )

    assert len(first.items) == 2
    assert len(second.items) == 1
    assert first.total == second.total == 3


@pytest.mark.asyncio
async def test_technician_cannot_list_an_incident_that_is_not_hers():
    incident = _incident(assigned_technician_id=OTHER_TECHNICIAN)
    use_case = _list_use_case(
        incidents=FakeIncidentRepository((TENANT, incident)), messages=FakeMessageRepository()
    )

    with pytest.raises(IncidentNotFoundError):
        await use_case.execute(
            tenant_id=TENANT,
            incident_id=incident.id,
            actor=_technician_actor(TECHNICIAN),
            page=1,
            per_page=10,
        )


@pytest.mark.asyncio
async def test_manager_sees_the_full_thread_of_any_incident():
    incident = _incident(assigned_technician_id=OTHER_TECHNICIAN)
    messages = FakeMessageRepository()
    await messages.add(
        TENANT,
        IncidentMessage(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            incident_id=incident.id,
            author_id=OTHER_TECHNICIAN,
            author_role=UserRole.TECHNICIAN,
            content="hola",
            created_at=NOW,
        ),
    )
    use_case = _list_use_case(
        incidents=FakeIncidentRepository((TENANT, incident)), messages=messages
    )

    page = await use_case.execute(
        tenant_id=TENANT, incident_id=incident.id, actor=_manager_actor(), page=1, per_page=10
    )

    assert page.total == 1


@pytest.mark.asyncio
async def test_an_incident_of_another_tenant_is_invisible_to_this_tenants_actor():
    """R3.2, steering/security.md rule 1 — the tenant isolation test this new use case owes
    the module's DoD (`steering/testing.md` §28.18), distinct from any existing variant: no
    other test in this file crosses `TENANT`/`OTHER_TENANT`.

    Uses the same `_load_incident_in_scope` guard every other `maintenance` use case relies
    on: the incident is registered only under `OTHER_TENANT`, so looking it up under `TENANT`
    must be indistinguishable from an id that never existed — never an empty page, which would
    tell an unauthorised caller that the id resolves to *something*.
    """
    neighbour_incident = _incident(tenant_id=OTHER_TENANT, assigned_technician_id=TECHNICIAN)
    messages = FakeMessageRepository()
    await messages.add(
        OTHER_TENANT,
        IncidentMessage(
            id=uuid.uuid4(),
            tenant_id=OTHER_TENANT,
            incident_id=neighbour_incident.id,
            author_id=TECHNICIAN,
            author_role=UserRole.TECHNICIAN,
            content="secreto del tenant vecino",
            created_at=NOW,
        ),
    )
    use_case = _list_use_case(
        incidents=FakeIncidentRepository((OTHER_TENANT, neighbour_incident)), messages=messages
    )

    with pytest.raises(IncidentNotFoundError):
        await use_case.execute(
            tenant_id=TENANT,
            incident_id=neighbour_incident.id,
            actor=_manager_actor(),
            page=1,
            per_page=10,
        )
