"""`process_webhook_events` as it is actually wired (`reservations-webhooks` R5.1, 4.8).

The use cases have their own tests; what is left here is the part only the composition root
can get wrong — that the queue is read from a session the worker never marks, that each tenant
gets its own marked one, that the lock is taken, and that the report survives being turned into
a Celery return value.

The worker's session factory is swapped for the test one, exactly as `test_runner.py` does it:
`conftest.py` builds a `NullPool` engine on a throwaway database per test, while the worker's
own factory points at the development database.
"""

import asyncio
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.db import TENANT_ID_SESSION_KEY
from app.integrations.application.webhooks import (
    ProcessWebhookEventsUseCase,
    WebhookProcessingReport,
)
from app.integrations.infrastructure.models import WebhookEventModel
from app.properties.infrastructure.models import PropertyModel
from app.scheduler import runner, tasks
from app.scheduler.schedule import CADENCES
from app.tenants.infrastructure.models import TenantModel

WEBHOOK_TASK = "process_webhook_events"


@pytest.fixture
def worker_sessions(test_engine, monkeypatch):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(runner, "_session_factory", factory)
    return factory


@pytest_asyncio.fixture
async def free_lock():
    """The lock key is global to the Redis instance, so a leftover would silently turn every
    assertion below into "skipped"."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.delete(f"scheduler:lock:{WEBHOOK_TASK}")
    try:
        yield client
    finally:
        await client.delete(f"scheduler:lock:{WEBHOOK_TASK}")
        await client.aclose()


async def _tenant_with_a_notice(session, name: str) -> tuple[TenantModel, uuid.UUID]:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    session.add(tenant)
    await session.flush()
    session.add(
        PropertyModel(tenant_id=tenant.id, name=f"{name} flat", internal_code=f"{name}-1")
    )
    event = WebhookEventModel(
        tenant_id=tenant.id,
        provider="MOCK",
        event_type="booking.modified",
        payload={},
        received_at=datetime.now(UTC),
    )
    session.add(event)
    await session.flush()
    return tenant, event.id


def test_the_task_is_registered_with_its_own_cadence() -> None:
    from app.worker import celery_app

    assert WEBHOOK_TASK in celery_app.tasks
    assert CADENCES[WEBHOOK_TASK].total_seconds() == 60


@pytest.mark.asyncio
async def test_the_wired_job_drains_the_queue(db_session, worker_sessions, free_lock) -> None:
    """The whole composition, against real Postgres and the real mock adapter."""
    tenant, event_id = await _tenant_with_a_notice(db_session, "TenantA")
    await db_session.commit()

    report = await tasks._process_webhook_events()

    assert report.selected == 1
    assert report.tenants == 1
    assert report.processed == 1
    processed = await db_session.scalar(
        select(WebhookEventModel.processed).where(WebhookEventModel.id == event_id)
    )
    assert processed is True
    assert tenant.id is not None


@pytest.mark.asyncio
async def test_the_queue_is_read_from_a_session_the_worker_never_marks(
    db_session, worker_sessions, free_lock, monkeypatch
) -> None:
    """R5.5 at the composition root.

    The tenant's work runs on a session marked for it; the batch that FOUND that tenant did
    not. Asserted by capturing both, because this is precisely the pair a future refactor
    could collapse into one session without any test noticing — until a notice with a `NULL`
    tenant went permanently invisible.
    """
    await _tenant_with_a_notice(db_session, "TenantA")
    await db_session.commit()
    batch_sessions: list[object] = []
    tenant_sessions: list[object] = []

    real_execute = ProcessWebhookEventsUseCase.execute

    async def spy_execute(self, *, now):
        batch_sessions.append(self._queue._session.info.get(TENANT_ID_SESSION_KEY))
        return await real_execute(self, now=now)

    monkeypatch.setattr(ProcessWebhookEventsUseCase, "execute", spy_execute)

    real_use_case = tasks._webhook_tenant_use_case

    def spy_use_case(session, tenant_id):
        tenant_sessions.append(session.info.get(TENANT_ID_SESSION_KEY))
        return real_use_case(session, tenant_id)

    monkeypatch.setattr(tasks, "_webhook_tenant_use_case", spy_use_case)

    await tasks._process_webhook_events()

    assert batch_sessions == [None], "the queue was read from a MARKED session"
    assert tenant_sessions and all(marked is not None for marked in tenant_sessions)


@pytest.mark.asyncio
async def test_a_second_run_is_skipped_while_the_first_holds_the_lock(
    db_session, worker_sessions, free_lock
) -> None:
    """R4.2 of `celery-jobs`, inherited: contention is `skipped`, never a failure — and the
    notice stays pending rather than being processed twice."""
    _, event_id = await _tenant_with_a_notice(db_session, "TenantA")
    await db_session.commit()
    await free_lock.set(f"scheduler:lock:{WEBHOOK_TASK}", "somebody-else", px=5000)

    # The Celery task body, called the way Celery calls it. In its own thread because it ends
    # in `asyncio.run` (design D1 of `celery-jobs`: a fresh loop per execution), which refuses
    # to start inside the loop pytest-asyncio is already running. Safe here precisely because
    # the assertion is that it touches no database: it loses the lock and returns.
    result = await asyncio.to_thread(tasks.process_webhook_events)

    assert result == asdict(WebhookProcessingReport(skipped_locked=True))
    processed = await db_session.scalar(
        select(WebhookEventModel.processed).where(WebhookEventModel.id == event_id)
    )
    assert processed is False


def test_the_report_survives_being_a_celery_return_value() -> None:
    """Celery serialises what a task returns, so the report has to be a plain dict of plain
    values — a dataclass that grew an entity would fail in a worker, not in a test."""
    serialised = asdict(WebhookProcessingReport(selected=2, processed=1, failed=1))

    assert serialised == {
        "selected": 2,
        "processed": 1,
        "failed": 1,
        "unattributed": 0,
        "tenants": 0,
        "skipped_locked": False,
    }
