"""Unit and integration tests for `CreateTenantUseCase` (`platform-admin-api` R1.1, R1.2, R2.1, R2.3, R-2).

The unit tests use fakes of the four ports (`TenantRepository`, `TenantConfigRepository`,
`AuditLogRepository`, `UnitOfWork`) so the test verifies only the use case's orchestration.
The integration tests exercise the real SQLAlchemy adapters against the test database so
the `TenantAlreadyExistsError` mapping is observed at the seam (R-2).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.audit.domain.entities import AuditLog
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.application.user_admin import (
    CreateUserCommand,
    CreateUserUseCase,
    CreatedUser,
)
from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.ports import PasswordHasher, UnitOfWork, UserRepository
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.platform.application.use_cases import (
    CreateTenantCommand,
    CreateTenantUseCase,
    CreateUserInTenantUseCase,
)
from app.platform.domain.exceptions import TenantAlreadyExistsError, TenantNotActiveError
from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from app.tenants.infrastructure.repositories import (
    SqlAlchemyTenantConfigRepository,
    SqlAlchemyTenantRepository,
)

# `tests/conftest.py` already configures `TEST_BCRYPT_ROUNDS = 4` for cheap hashing; the
# section-1 integration test imports the same value for its actor seed, and the section-3
# integration tests reuse it so the suite runtime stays bounded.
from tests.conftest import TEST_BCRYPT_ROUNDS  # noqa: E402


def utc_now() -> datetime:
    return datetime.now(UTC)


# --- fakes for the unit tests -----------------------------------------------------------
#
# The unit tests do not need a database: they assert the use case calls its ports in the
# right order, with the right arguments, and that `commit()` only happens on the happy path.
# The fakes are intentionally minimal — they record what they were called with and the
# unit tests inspect those recordings.


@dataclass
class _FakeTenantRepository:
    """Records the (tenant, config) pair `add` was called with, or raises a configured error.

    The `get` method is added here too because section 3's wrapper needs to read the tenant
    before delegating to `CreateUserUseCase`; the section-2 fakes only needed `add`. The
    default is `None` so a future test that forgets to seed it sees `TenantNotActiveError`
    rather than a confusing `AttributeError`.
    """

    raise_on_add: Exception | None = None
    add_called: int = 0
    add_called_with: tuple[Tenant, TenantConfig] | None = None
    get_return: Tenant | None = None
    get_calls: list[uuid.UUID] = field(default_factory=list)

    async def add(self, tenant: Tenant, config: TenantConfig) -> None:
        self.add_called += 1
        self.add_called_with = (tenant, config)
        if self.raise_on_add is not None:
            raise self.raise_on_add

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        self.get_calls.append(tenant_id)
        return self.get_return


@dataclass
class _FakeTenantConfigRepository:
    """Holds the unused port for the future reader; the create flow does not call it."""

    config: TenantConfig | None = None

    async def get_or_create(self, tenant_id: uuid.UUID, now: datetime) -> TenantConfig:
        raise AssertionError("get_or_create must not be called by CreateTenantUseCase.execute")


@dataclass
class _FakeAuditLogRepository:
    """Records every entry appended, keyed by `entry.id`."""

    entries: list[AuditLog] = field(default_factory=list)

    async def add(self, tenant_id: uuid.UUID, entry: AuditLog) -> None:
        self.entries.append(entry)


@dataclass
class _FakeUnitOfWork:
    """Records every commit/rollback call; raises on demand."""

    raise_on_commit: Exception | None = None
    commits: int = 0
    rollbacks: int = 0

    async def commit(self) -> None:
        self.commit_calls_before_audit = self.commits
        self.commits += 1
        if self.raise_on_commit is not None:
            raise self.raise_on_commit

    async def rollback(self) -> None:
        self.rollbacks += 1


def _build_use_case(
    *,
    tenant_repo: _FakeTenantRepository | None = None,
    config_repo: _FakeTenantConfigRepository | None = None,
    audit_repo: _FakeAuditLogRepository | None = None,
    uow: _FakeUnitOfWork | None = None,
) -> tuple[
    CreateTenantUseCase,
    _FakeTenantRepository,
    _FakeTenantConfigRepository,
    _FakeAuditLogRepository,
    _FakeUnitOfWork,
]:
    tenant_repo = tenant_repo or _FakeTenantRepository()
    config_repo = config_repo or _FakeTenantConfigRepository()
    audit_repo = audit_repo or _FakeAuditLogRepository()
    uow = uow or _FakeUnitOfWork()
    use_case = CreateTenantUseCase(
        tenants=tenant_repo,
        configs=config_repo,
        audit=audit_repo,
        uow=uow,
    )
    return use_case, tenant_repo, config_repo, audit_repo, uow


def _command(name: str = "Acme") -> CreateTenantCommand:
    return CreateTenantCommand(
        name=name,
        billing_email="ops@acme.example",
        country="ES",
        timezone="Europe/Madrid",
        default_language="es",
    )


# --- 2.3 unit test ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_use_case_writes_tenant_config_audit_and_commits_in_order() -> None:
    """The happy path: each port is called with the right shape, and exactly once.

    The four assertions the task lists are checked one by one:

    (a) `Tenant.create` is called with the five command fields plus `now`.
    (b) `tenants.add` is called with `(tenant, config)`.
    (c) `audit.add` is called with an `AuditLog` whose `tenant_id` / `entity_id` come from
        the newly created tenant — not `None`, not the actor (D5).
    (d) `uow.commit()` is called once and only once.
    """
    now = utc_now()
    command = _command()
    actor_user_id = uuid.uuid4()
    actor_ip = "127.0.0.1"

    use_case, tenant_repo, _config_repo, audit_repo, uow = _build_use_case()

    settings = await use_case.execute(
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        command=command,
        now=now,
    )

    # (a) The created tenant's fields are the command's five fields plus `now`.
    tenant = settings.tenant
    assert isinstance(tenant, Tenant)
    assert tenant.name == command.name
    assert tenant.billing_email == command.billing_email
    assert tenant.country == command.country
    assert tenant.timezone == command.timezone
    assert tenant.default_language == command.default_language
    assert tenant.status is TenantStatus.ACTIVE
    assert tenant.created_at == now
    assert tenant.updated_at == now

    # (b) `tenants.add` received the tenant AND its default config.
    assert tenant_repo.add_called == 1
    assert tenant_repo.add_called_with == (tenant, settings.config)
    assert settings.config.tenant_id == tenant.id

    # (c) The audit entry points at the NEW tenant on every axis.
    assert len(audit_repo.entries) == 1
    entry = audit_repo.entries[0]
    assert entry.tenant_id == tenant.id
    assert entry.entity_id == tenant.id
    assert entry.entity_type == "TENANT"
    assert entry.action == "TENANT_CREATED"
    assert entry.actor_user_id == actor_user_id
    assert entry.actor_ip == actor_ip
    # The five body fields are in `changes`, in `diff(old=None, new=value)` form. The
    # `ChangeSet.as_dict()` produced by `AuditLogFactory.build` carries the same five keys,
    # each with `{"old": None, "new": ...}`.
    assert entry.changes is not None
    assert set(entry.changes) == {
        "name",
        "billing_email",
        "country",
        "timezone",
        "default_language",
    }
    assert entry.changes["name"] == {"old": None, "new": command.name}
    assert entry.changes["billing_email"] == {
        "old": None,
        "new": command.billing_email,
    }
    assert entry.changes["country"] == {"old": None, "new": command.country}
    assert entry.changes["timezone"] == {"old": None, "new": command.timezone}
    assert entry.changes["default_language"] == {
        "old": None,
        "new": command.default_language,
    }

    # (d) Exactly one `commit()`, no `rollback()`.
    assert uow.commits == 1
    assert uow.rollbacks == 0


# --- 2.4 unit test ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_use_case_does_not_commit_when_tenant_already_exists() -> None:
    """R-2 / R2.3: the duplicate path is an unwind, not a partial commit.

    `tenants.add` translates the unique-constraint violation into `TenantAlreadyExistsError`;
    the use case must not call `commit()` afterwards, and the exception must propagate
    unwrapped so section 4's handler can map it to 409.
    """
    now = utc_now()
    command = _command(name="Magno")
    tenant_repo = _FakeTenantRepository(raise_on_add=TenantAlreadyExistsError("Magno"))
    uow = _FakeUnitOfWork()
    use_case, tenant_repo, _config_repo, audit_repo, uow = _build_use_case(
        tenant_repo=tenant_repo,
        uow=uow,
    )

    with pytest.raises(TenantAlreadyExistsError):
        await use_case.execute(
            actor_user_id=uuid.uuid4(),
            actor_ip="127.0.0.1",
            command=command,
            now=now,
        )

    assert uow.commits == 0
    assert uow.rollbacks == 0
    # The audit row is written after `add`, so on the duplicate path nothing reached it.
    assert audit_repo.entries == []


# --- 2.5 integration test ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_use_case_persists_tenant_config_and_audit_row(db_session) -> None:
    """End-to-end: the use case commits the tenant, its config, and the audit row.

    Runs against the real SQLAlchemy adapters and the `db_session` fixture so the assertions
    check actual rows in `tenants`, `tenant_configs` and `audit_logs`.
    """
    now = utc_now()
    command = CreateTenantCommand(
        name="Real-Acme",
        billing_email="ops@real-acme.example",
        country="ES",
        timezone="Europe/Madrid",
        default_language="es",
    )
    actor_user_id = uuid.uuid4()
    actor_ip = "127.0.0.1"
    # A `SUPER_ADMIN` has no tenant (`ck_users_super_admin_tenant_id_null`); insert the row
    # without a tenant so the foreign key from `audit_logs.actor_user_id` is satisfied.
    from app.auth.domain.value_objects import normalize_email
    from app.auth.infrastructure.models import UserModel

    actor = UserModel(
        id=actor_user_id,
        tenant_id=None,
        name="Root Admin",
        email=normalize_email("root@example.com"),
        password_hash="not-used",
        role="SUPER_ADMIN",
        status="ACTIVE",
    )
    db_session.add(actor)
    await db_session.flush()

    use_case = CreateTenantUseCase(
        tenants=SqlAlchemyTenantRepository(db_session),
        configs=SqlAlchemyTenantConfigRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )

    settings = await use_case.execute(
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        command=command,
        now=now,
    )
    # The use case does not commit itself: `SqlAlchemyUnitOfWork.commit()` is called inside
    # `execute()` (the last step), so the rows are visible after `await`.
    tenant_id = settings.tenant.id

    # (a) One row in `tenants`, ACTIVE.
    tenant_row = (
        await db_session.execute(select(TenantModel).where(TenantModel.id == tenant_id))
    ).scalar_one()
    assert tenant_row.name == "Real-Acme"
    assert tenant_row.status is TenantStatus.ACTIVE

    # (b) One row in `tenant_configs` for that tenant.
    config_row = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_id)
        )
    ).scalar_one()
    assert config_row.id == settings.config.id

    # (c) One row in `audit_logs`, with every required field.
    audit_row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.entity_id == tenant_id)
        )
    ).scalar_one()
    assert audit_row.action == "TENANT_CREATED"
    assert audit_row.entity_type == "TENANT"
    assert audit_row.entity_id == tenant_id
    assert audit_row.tenant_id == tenant_id  # D5: entity's, not actor's
    assert audit_row.actor_user_id == actor_user_id
    assert audit_row.actor_ip == actor_ip
    assert audit_row.changes is not None
    assert set(audit_row.changes) == {
        "name",
        "billing_email",
        "country",
        "timezone",
        "default_language",
    }


# --- 2.6 integration test ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_use_case_with_duplicate_name_raises_and_writes_nothing(
    db_session,
) -> None:
    """R-2 / R1.2: a second create with the same name fails cleanly at flush time.

    The unique constraint added by section 1's migration makes the second `add` raise
    `TenantAlreadyExistsError`. The assertion is the observable shape of that failure:
    no second `tenants` row, no second `audit_logs` row with `action=TENANT_CREATED` for
    the contested name.
    """
    from app.auth.domain.value_objects import normalize_email
    from app.auth.infrastructure.models import UserModel

    now = utc_now()
    actor_user_id = uuid.uuid4()
    actor = UserModel(
        id=actor_user_id,
        tenant_id=None,
        name="Root Admin",
        email=normalize_email("root-duplicate@example.com"),
        password_hash="not-used",
        role="SUPER_ADMIN",
        status="ACTIVE",
    )
    db_session.add(actor)
    await db_session.flush()

    use_case = CreateTenantUseCase(
        tenants=SqlAlchemyTenantRepository(db_session),
        configs=SqlAlchemyTenantConfigRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )

    # First call succeeds.
    first = await use_case.execute(
        actor_user_id=actor_user_id,
        actor_ip="127.0.0.1",
        command=CreateTenantCommand(name="T", billing_email="first@t.example"),
        now=now,
    )
    first_tenant_id = first.tenant.id

    # Second call with the same name must fail.
    with pytest.raises(TenantAlreadyExistsError):
        await use_case.execute(
            actor_user_id=actor_user_id,
            actor_ip="127.0.0.1",
            command=CreateTenantCommand(name="T", billing_email="second@t.example"),
            now=now,
        )
    # Same commit/rollback dance the section-1 `test_add_translates_a_duplicate_name_*`
    # uses: the `IntegrityError` aborts the session's transaction, and any further read
    # raises `PendingRollbackError` until we roll back by hand.
    await db_session.rollback()

    # Exactly one `tenants` row with `name="T"`.
    rows = (
        await db_session.execute(select(TenantModel).where(TenantModel.name == "T"))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == first_tenant_id

    # Exactly one `audit_logs` row with `action=TENANT_CREATED` for that tenant.
    audit_rows = (
        await db_session.execute(
            select(AuditLogModel).where(
                AuditLogModel.action == "TENANT_CREATED",
                AuditLogModel.entity_id == first_tenant_id,
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1


# ========================================================================================
# Section 3 — `CreateUserInTenantUseCase` (R3.1, R3.3, R4.1, R4.3, design D3, D5)
# ========================================================================================
#
# The wrapper has two responsibilities: validate the tenant (404 on missing or non-ACTIVE)
# and delegate to `CreateUserUseCase.execute` (which writes the user, the audit row and
# the commit). The unit tests use a fake `TenantRepository` and a fake `CreateUserUseCase`
# so the wrapper's own orchestration is the only thing under test; the integration tests
# run the real SQLAlchemy adapters to verify the end-to-end shape of the audit row and
# the idempotence of the suspended-tenant branch.


@dataclass
class _FakeCreateUserUseCase:
    """Records the exact kwargs the wrapper passed through; returns a fixed `CreatedUser`.

    The point of these unit tests is to assert that the wrapper forwards every kwarg
    verbatim and returns the `CreatedUser` it received unchanged — so the fake returns a
    recognisable sentinel and the test checks identity, not just equality.
    """

    return_value: CreatedUser
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        command: CreateUserCommand,
        now: datetime,
    ) -> CreatedUser:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "actor_ip": actor_ip,
                "command": command,
                "now": now,
            }
        )
        return self.return_value


def _active_tenant(status: TenantStatus = TenantStatus.ACTIVE) -> Tenant:
    """A real `Tenant` domain object the fake repository can hand back."""
    now = utc_now()
    return Tenant(
        id=uuid.uuid4(),
        name="tenant-x",
        billing_email="ops@x.example",
        created_at=now,
        updated_at=now,
        status=status,
    )


def _user_command() -> CreateUserCommand:
    return CreateUserCommand(
        name="New Manager",
        email="new.manager@example.com",
        role=UserRole.PROPERTY_MANAGER,
    )


def _build_wrapper(
    *,
    tenant_repo: _FakeTenantRepository | None = None,
    create_user: _FakeCreateUserUseCase | None = None,
) -> tuple[CreateUserInTenantUseCase, _FakeTenantRepository, _FakeCreateUserUseCase]:
    """Wire the wrapper with fakes. Defaults seed an ACTIVE tenant and a sentinel return."""
    tenant_repo = tenant_repo or _FakeTenantRepository(get_return=_active_tenant())
    if create_user is None:
        sentinel_user = User(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            name="New Manager",
            email="new.manager@example.com",
            password_hash="hash",
            role=UserRole.PROPERTY_MANAGER,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        create_user = _FakeCreateUserUseCase(
            return_value=CreatedUser(user=sentinel_user, temporary_password="TempPass1!")
        )
    use_case = CreateUserInTenantUseCase(
        tenants=tenant_repo,
        create_user=create_user,  # type: ignore[arg-type] - fake mirrors the real signature
    )
    return use_case, tenant_repo, create_user


# --- 3.3 unit test ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_in_tenant_raises_when_tenant_is_missing() -> None:
    """R3.3: a non-existent tenant surfaces as `TenantNotActiveError`, no delegation.

    The fake `TenantRepository.get` returns `None`, the wrapper raises, and the wrapped
    `CreateUserUseCase.execute` is never reached — so neither a `users` row nor an
    `audit_logs` row could have been written. The `calls` list is the proof.
    """
    now = utc_now()
    tenant_id = uuid.uuid4()
    tenant_repo = _FakeTenantRepository(get_return=None)
    use_case, tenant_repo, create_user = _build_wrapper(tenant_repo=tenant_repo)

    with pytest.raises(TenantNotActiveError):
        await use_case.execute(
            tenant_id=tenant_id,
            actor_user_id=uuid.uuid4(),
            actor_ip="127.0.0.1",
            command=_user_command(),
            now=now,
        )

    # The wrapper DID look up the tenant (otherwise the missing case would never be detected
    # in the first place), but the delegation was skipped.
    assert tenant_repo.get_calls == [tenant_id]
    assert create_user.calls == []


# --- 3.4 unit test ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_in_tenant_raises_when_tenant_is_suspended() -> None:
    """R3.3: a SUSPENDED tenant surfaces as `TenantNotActiveError`, no delegation.

    The 404 response is indistinguishable from the missing case on purpose (R3.3), so the
    wrapper's branch is the same. Asserting that `create_user.execute` is not called is
    what keeps the audit row out of `audit_logs` on the rejected path.
    """
    now = utc_now()
    tenant_id = uuid.uuid4()
    tenant_repo = _FakeTenantRepository(
        get_return=_active_tenant(status=TenantStatus.SUSPENDED)
    )
    use_case, tenant_repo, create_user = _build_wrapper(tenant_repo=tenant_repo)

    with pytest.raises(TenantNotActiveError):
        await use_case.execute(
            tenant_id=tenant_id,
            actor_user_id=uuid.uuid4(),
            actor_ip="127.0.0.1",
            command=_user_command(),
            now=now,
        )

    assert tenant_repo.get_calls == [tenant_id]
    assert create_user.calls == []


# --- 3.5 unit test ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_in_tenant_delegates_to_create_user_use_case() -> None:
    """R3.1 / R4.3: an ACTIVE tenant goes through to `CreateUserUseCase.execute` unchanged.

    Five sub-assertions, one per forwarded kwarg; the wrapper's only job on the happy path
    is to pass them all through and return whatever the wrapped call returned. The
    `temporary_password` round-trip is the part that proves the wrapper does not silently
    drop the one-time secret on the floor.
    """
    now = utc_now()
    tenant_id = uuid.uuid4()
    actor_user_id = uuid.uuid4()
    actor_ip = "203.0.113.7"
    command = _user_command()

    use_case, tenant_repo, create_user = _build_wrapper(
        tenant_repo=_FakeTenantRepository(get_return=_active_tenant()),
    )

    result = await use_case.execute(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        command=command,
        now=now,
    )

    # `tenant_repo.get` was called with the path's id.
    assert tenant_repo.get_calls == [tenant_id]

    # `create_user.execute` was called exactly once, with all five kwargs forwarded verbatim.
    assert len(create_user.calls) == 1
    forwarded = create_user.calls[0]
    assert forwarded["tenant_id"] == tenant_id
    assert forwarded["actor_user_id"] == actor_user_id
    assert forwarded["actor_ip"] == actor_ip
    assert forwarded["command"] is command  # identity, not equality — no copy
    assert forwarded["now"] == now

    # The wrapper returns the wrapped use case's value AS-IS, including the one-time secret.
    assert result is create_user.return_value
    assert result.temporary_password == "TempPass1!"


# --- 3.6 integration test ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_in_tenant_persists_user_and_audit_row(db_session) -> None:
    """R3.1 / R4.1 / R4.3 / D5: the wrapper writes a user and a USER_CREATED audit row.

    The actor is a `SUPER_ADMIN` (no tenant); the audit row's `tenant_id` MUST be the path
    parameter, not the actor's. That is design D5, and it is the property the integration
    test verifies by reading the row directly from the database.

    Seeded by `tests/auth/conftest.py::insert_tenant` (status ACTIVE) plus an inline
    `SUPER_ADMIN` (no `super_admin` fixture exists yet — section 5 adds one, and these
    tests will then drop their inline seeds the same way the 2.5 integration test can).
    """
    from app.auth.domain.value_objects import normalize_email
    from app.auth.infrastructure.models import UserModel

    now = utc_now()
    actor_user_id = uuid.uuid4()
    actor_ip = "198.51.100.42"

    # Seed the SUPER_ADMIN actor: no tenant (R1.1, R1.2).
    actor = UserModel(
        id=actor_user_id,
        tenant_id=None,
        name="Root Admin",
        email=normalize_email("root-section3@example.com"),
        password_hash="not-used",
        role="SUPER_ADMIN",
        status="ACTIVE",
    )
    db_session.add(actor)
    await db_session.flush()

    # Seed the target tenant as ACTIVE.
    target_tenant = TenantModel(
        id=uuid.uuid4(),
        name="tenant-section3",
        billing_email="ops@tenant-section3.example",
        status=TenantStatus.ACTIVE,
    )
    db_session.add(target_tenant)
    await db_session.flush()
    db_session.add(
        TenantConfigModel(
            tenant_id=target_tenant.id,
            notification_email_enabled=False,
            notification_whatsapp_enabled=False,
        )
    )
    await db_session.flush()

    hasher = BcryptPasswordHasher(rounds=TEST_BCRYPT_ROUNDS)
    session = db_session
    inner = CreateUserUseCase(
        users=SqlAlchemyUserRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        hasher=hasher,
        uow=SqlAlchemyUnitOfWork(session),
    )
    use_case = CreateUserInTenantUseCase(
        tenants=SqlAlchemyTenantRepository(session),
        create_user=inner,
    )

    command = CreateUserCommand(
        name="Platform Manager",
        email="manager@tenant-section3.example",
        role=UserRole.PROPERTY_MANAGER,
        phone="+34000000000",
        preferred_language="es",
    )
    created = await use_case.execute(
        tenant_id=target_tenant.id,
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        command=command,
        now=now,
    )

    # (a) One row in `users` with the path's tenant_id, the requested role, ACTIVE, and
    # `must_change_password=True` (the latter is what `CreateUserUseCase` always sets).
    user_row = (
        await db_session.execute(
            select(UserModel).where(UserModel.email == normalize_email(command.email))
        )
    ).scalar_one()
    assert user_row.id == created.user.id
    assert user_row.tenant_id == target_tenant.id
    assert user_row.role is UserRole.PROPERTY_MANAGER
    assert user_row.status is UserStatus.ACTIVE
    assert user_row.must_change_password is True

    # (b) One row in `audit_logs` with `action=USER_CREATED`, the new user's id, and
    # `tenant_id` from the PATH (not from the actor's session — the actor has no tenant).
    audit_row = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.entity_id == user_row.id)
        )
    ).scalar_one()
    assert audit_row.action == "USER_CREATED"
    assert audit_row.entity_type == "USER"
    assert audit_row.entity_id == user_row.id
    assert audit_row.tenant_id == target_tenant.id  # D5: path's, NOT actor's
    assert audit_row.actor_user_id == actor_user_id
    assert audit_row.actor_ip == actor_ip

    # `changes` carries `email`, `role`, and a redacted `password` — the change list
    # `CreateUserUseCase` produces, NOT a hand-rolled one.
    assert audit_row.changes is not None
    assert set(audit_row.changes) == {"email", "role", "password"}
    assert audit_row.changes["email"] == {"old": None, "new": user_row.email}
    assert audit_row.changes["role"] == {"old": None, "new": "PROPERTY_MANAGER"}
    assert audit_row.changes["password"] == {"changed": True}

    # The wrapper returned the inner use case's `CreatedUser` as-is; `created.user.id` and
    # the temporary password that was actually issued round-trip cleanly.
    assert created.user.id == user_row.id
    assert created.temporary_password  # non-empty; the exact value is opaque here.


# --- 3.7 integration test ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_in_tenant_with_suspended_tenant_writes_nothing(
    db_session,
) -> None:
    """R3.3 / R4.2: a SUSPENDED tenant produces `TenantNotActiveError` and leaves no trace.

    The wrapper must abort before delegating, so neither the `users` row nor the
    `audit_logs` row exists. This is the same contract `CreateTenantUseCase`'s duplicate
    branch enforces (R-2, test 2.6) — a failed precondition must be an unwind, not a
    partial commit.
    """
    from app.auth.domain.value_objects import normalize_email
    from app.auth.infrastructure.models import UserModel

    now = utc_now()
    actor_user_id = uuid.uuid4()
    actor = UserModel(
        id=actor_user_id,
        tenant_id=None,
        name="Root Admin",
        email=normalize_email("root-section3-suspended@example.com"),
        password_hash="not-used",
        role="SUPER_ADMIN",
        status="ACTIVE",
    )
    db_session.add(actor)
    await db_session.flush()

    suspended_tenant = TenantModel(
        id=uuid.uuid4(),
        name="tenant-suspended",
        billing_email="ops@suspended.example",
        status=TenantStatus.SUSPENDED,
    )
    db_session.add(suspended_tenant)
    await db_session.flush()

    hasher = BcryptPasswordHasher(rounds=TEST_BCRYPT_ROUNDS)
    inner = CreateUserUseCase(
        users=SqlAlchemyUserRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        hasher=hasher,
        uow=SqlAlchemyUnitOfWork(db_session),
    )
    use_case = CreateUserInTenantUseCase(
        tenants=SqlAlchemyTenantRepository(db_session),
        create_user=inner,
    )

    command = CreateUserCommand(
        name="Should Not Be Created",
        email="not.created@example.com",
        role=UserRole.PROPERTY_MANAGER,
    )

    with pytest.raises(TenantNotActiveError):
        await use_case.execute(
            tenant_id=suspended_tenant.id,
            actor_user_id=actor_user_id,
            actor_ip="127.0.0.1",
            command=command,
            now=now,
        )

    # No `users` row was inserted.
    user_rows = (
        await db_session.execute(
            select(UserModel).where(UserModel.email == normalize_email(command.email))
        )
    ).scalars().all()
    assert user_rows == []

    # No `USER_CREATED` audit row was inserted.
    audit_rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "USER_CREATED")
        )
    ).scalars().all()
    assert audit_rows == []
