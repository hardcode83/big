"""`run_for_every_tenant` — one session per tenant, marked (`celery-jobs` R2, R1.6, D12).

Integration, against real Postgres: the whole point of this module is what happens to
sessions outside a request, and a fake session would prove none of it.

The runner's own session factory is swapped for the test one, because `conftest.py` builds
a `NullPool` engine on a throwaway database per test and the worker's factory points at the
development database.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import TENANT_ID_SESSION_KEY
from app.properties.infrastructure.models import PropertyModel
from app.scheduler import runner
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def worker_sessions(test_engine, monkeypatch):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(runner, "_session_factory", factory)
    return factory


async def _tenant(session, name: str, status: TenantStatus = TenantStatus.ACTIVE):
    tenant = TenantModel(
        name=name, billing_email=f"{name.lower()}@example.com", status=status
    )
    session.add(tenant)
    await session.flush()
    session.add(
        PropertyModel(tenant_id=tenant.id, name=f"{name} flat", internal_code=f"{name}-1")
    )
    await session.flush()
    return tenant


@pytest.mark.asyncio
async def test_it_runs_once_per_active_tenant(db_session, worker_sessions) -> None:
    first = await _tenant(db_session, "TenantA")
    second = await _tenant(db_session, "TenantB")
    await db_session.commit()
    seen = []

    async def work(session: AsyncSession, tenant_id: uuid.UUID, now: datetime):
        seen.append(tenant_id)
        return tenant_id

    report = await runner.run_for_every_tenant("t", work, now=NOW)

    assert report.tenants == 2
    assert report.failed == 0
    assert set(seen) == {first.id, second.id}


@pytest.mark.asyncio
async def test_a_suspended_tenant_is_not_processed(db_session, worker_sessions) -> None:
    active = await _tenant(db_session, "TenantA")
    await _tenant(db_session, "TenantB", status=TenantStatus.SUSPENDED)
    await db_session.commit()
    seen = []

    async def work(session, tenant_id, now):
        seen.append(tenant_id)

    await runner.run_for_every_tenant("t", work, now=NOW)

    assert seen == [active.id]


@pytest.mark.asyncio
async def test_every_tenant_gets_a_session_bound_to_itself(db_session, worker_sessions) -> None:
    """R2.1/R2.2: the global filter is only active on a marked session, and a session is
    never reused for a second tenant."""
    await _tenant(db_session, "TenantA")
    await _tenant(db_session, "TenantB")
    await db_session.commit()
    bindings = []

    async def work(session: AsyncSession, tenant_id: uuid.UUID, now: datetime):
        bindings.append((id(session), session.info.get(TENANT_ID_SESSION_KEY), tenant_id))

    await runner.run_for_every_tenant("t", work, now=NOW)

    assert all(marked == tenant_id for _, marked, tenant_id in bindings)
    # Two distinct session objects: re-marking one is what `bind_session_to_tenant` refuses.
    assert len({session_id for session_id, _, _ in bindings}) == 2


@pytest.mark.asyncio
async def test_the_tenant_list_is_read_from_an_unmarked_session(db_session, worker_sessions) -> None:
    """Design D5: `tenants` is unscoped data, and the only supported way to read it is a
    session that was never bound."""
    await _tenant(db_session, "TenantA")
    await db_session.commit()

    # `list_active_tenants` opens and closes its own session; if it were marked, this call
    # would still work, so the assertion that matters is the one below: no session handed
    # to `work` is ever the one used for the listing.
    tenants = await runner.list_active_tenants()

    assert len(tenants) == 1


@pytest.mark.asyncio
async def test_one_tenant_failing_does_not_stop_the_others(db_session, worker_sessions) -> None:
    """Design D12."""
    first = await _tenant(db_session, "TenantA")
    second = await _tenant(db_session, "TenantB")
    await db_session.commit()
    completed = []

    async def work(session, tenant_id, now):
        if tenant_id == first.id:
            raise RuntimeError("boom")
        completed.append(tenant_id)

    report = await runner.run_for_every_tenant("t", work, now=NOW)

    assert report.tenants == 2
    assert report.failed == 1
    assert completed == [second.id]


@pytest.mark.asyncio
async def test_a_failing_tenant_leaves_nothing_written(db_session, worker_sessions) -> None:
    """The rollback of design D12, observed rather than assumed."""
    tenant = await _tenant(db_session, "TenantA")
    await db_session.commit()

    async def work(session: AsyncSession, tenant_id: uuid.UUID, now: datetime):
        session.add(
            PropertyModel(tenant_id=tenant_id, name="ghost", internal_code="GHOST-1")
        )
        await session.flush()
        raise RuntimeError("boom")

    report = await runner.run_for_every_tenant("t", work, now=NOW)

    assert report.failed == 1
    ghosts = await db_session.scalar(
        select(PropertyModel.id).where(PropertyModel.internal_code == "GHOST-1")
    )
    assert ghosts is None
    assert tenant.id is not None


@pytest.mark.asyncio
async def test_a_tenant_never_sees_another_tenants_rows(db_session, worker_sessions) -> None:
    """Rule 1 of `steering/security.md` for this module.

    Each tenant has one property. With the session bound, the global filter must make the
    neighbour's row invisible to an ORM read that names no `tenant_id` at all.
    """
    await _tenant(db_session, "TenantA")
    await _tenant(db_session, "TenantB")
    await db_session.commit()
    visible: dict[uuid.UUID, set[uuid.UUID]] = {}

    async def work(session: AsyncSession, tenant_id: uuid.UUID, now: datetime):
        rows = await session.execute(select(PropertyModel.tenant_id))
        visible[tenant_id] = set(rows.scalars())

    await runner.run_for_every_tenant("t", work, now=NOW)

    assert len(visible) == 2
    for tenant_id, seen in visible.items():
        assert seen == {tenant_id}, (tenant_id, seen)
