"""Running a use case once per tenant, outside any request (`celery-jobs` R1, R2).

Three things live here that nothing else in the codebase had to solve before, because
until now every use case ran inside a request that had already resolved its tenant.

**The engine** (design D1). Celery's worker is synchronous, so each task runs its coroutine
with `asyncio.run`, which means a fresh event loop per execution. The module-level engine of
`app/core/db.py` uses a pooled connection, and an asyncpg connection outlives the loop that
opened it — reusing it from the next loop is the "attached to a different loop" failure that
`tests/conftest.py:75-96` already documents and defends against the same way. So the worker
builds its own engine with `NullPool`.

**The sessions** (design D5). The tenant list comes from a session that is NEVER marked —
`tenants` has no `tenant_id`, and `app/core/db.py:132-155` is explicit that the only
supported way to read unscoped data is a session that was never bound. Each tenant then gets
its own session, bound with `bind_session_to_tenant`, which is what turns the global filter
on for that tenant's work.

**The failure boundary** (design D12). One tenant failing rolls back its own session and the
loop continues; the task still succeeds and reports the failures. Only a failure *before* the
loop — Redis, or listing the tenants — fails the task.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

# Imported for its side effect, exactly as `app/main.py` and `pms_sync.py` do it: a worker
# has its own import graph, and SQLAlchemy cannot resolve cross-table foreign keys for
# models it has never seen.
import app.core.models_registry  # noqa: F401
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import bind_session_to_tenant
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantModel

logger = logging.getLogger(__name__)

T = TypeVar("T")

_session_factory: async_sessionmaker[AsyncSession] | None = None


def worker_session_factory() -> async_sessionmaker[AsyncSession]:
    """The worker process's own session factory, on a `NullPool` engine (design D1).

    Built lazily and cached per process: importing this module must not open a connection,
    and the engine must not be the one `app/core/db.py` created at import time for the API.
    """
    global _session_factory
    if _session_factory is None:
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def worker_redis() -> AsyncIterator[Redis]:
    """A Redis client for one task execution, closed when it ends.

    **Not `app/core/redis.py`'s `get_redis()`**, and this is the same problem D1 solves for
    the database engine, one layer over. That helper caches one client for the whole
    process; a `redis.asyncio` connection belongs to the loop that opened it; and
    `asyncio.run` closes its loop when the task finishes. So the *second* task to run in a
    given worker process inherits a client pointing at a dead loop and dies with
    `RuntimeError: Event loop is closed`.

    Not hypothetical — measured on the dev stack before this existed: `check_sla_breaches`
    failed on roughly every other tick, alternating success and `Event loop is closed`,
    while every test passed because each test runs exactly one execution per process. The
    symptom had even shown up in `tests/scheduler/test_locks.py`, where it was worked around
    with a per-test fixture instead of being recognised as the production shape it was.

    Per-execution rather than per-loop-cached for the same reason `NullPool` beat a
    persistent loop: one connection setup per run, against a job whose cadence is a minute,
    is not worth a lifecycle nobody can see.
    """
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@dataclass
class TenantRunReport:
    """Per-tenant outcomes of one task run, plus whatever the use case returned."""

    task: str
    tenants: int = 0
    failed: int = 0
    skipped_locked: bool = False
    results: list[Any] = field(default_factory=list)


async def list_active_tenants() -> list[uuid.UUID]:
    """Every ACTIVE tenant, read from a session that is never marked.

    `tenants` carries no `tenant_id` so the global filter would not touch it anyway; the
    separate, short-lived session exists so that it cannot start to. It is closed before any
    tenant work begins — nothing of a tenant's domain data is ever read through it.
    """
    async with worker_session_factory()() as session:
        rows = await session.execute(
            select(TenantModel.id).where(TenantModel.status == TenantStatus.ACTIVE)
        )
        return list(rows.scalars())


async def run_for_every_tenant(
    task: str,
    work: Callable[[AsyncSession, uuid.UUID, datetime], Awaitable[T]],
    *,
    now: datetime | None = None,
) -> TenantRunReport:
    """Run `work` once per active tenant, each in its own marked session and transaction."""
    at = now or datetime.now(UTC)
    report = TenantRunReport(task=task)
    tenant_ids = await list_active_tenants()

    for tenant_id in tenant_ids:
        report.tenants += 1
        async with worker_session_factory()() as session:
            # One-way, one tenant per session: `bind_session_to_tenant` refuses to re-mark,
            # and a session that was marked must never be reused for a different tenant.
            bind_session_to_tenant(session, tenant_id)
            try:
                report.results.append(await work(session, tenant_id, at))
            except Exception:
                await session.rollback()
                report.failed += 1
                # The tenant id is the point: the operator needs to know *whose* run broke,
                # and the traceback goes to the log rather than up, so the other tenants
                # still get their turn (design D12).
                logger.exception(
                    "scheduler.tenant_run_failed",
                    extra={"task": task, "tenant_id": str(tenant_id)},
                )
    return report


def run_sync(coroutine: Awaitable[T]) -> T:
    """`asyncio.run` for a Celery task body (design D1).

    A function so the reason is written once: every task needs it, and `asyncio.run` in four
    task bodies invites someone to reach for a shared loop instead.
    """
    return asyncio.run(coroutine)  # type: ignore[arg-type]
