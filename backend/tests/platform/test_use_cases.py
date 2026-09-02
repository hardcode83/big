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
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.platform.application.use_cases import (
    CreateTenantCommand,
    CreateTenantUseCase,
)
from app.platform.domain.exceptions import TenantAlreadyExistsError
from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from app.tenants.infrastructure.repositories import (
    SqlAlchemyTenantConfigRepository,
    SqlAlchemyTenantRepository,
)


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
    """Records the (tenant, config) pair `add` was called with, or raises a configured error."""

    raise_on_add: Exception | None = None
    add_called: int = 0
    add_called_with: tuple[Tenant, TenantConfig] | None = None

    async def add(self, tenant: Tenant, config: TenantConfig) -> None:
        self.add_called += 1
        self.add_called_with = (tenant, config)
        if self.raise_on_add is not None:
            raise self.raise_on_add


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
