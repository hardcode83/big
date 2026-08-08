"""The `dispatch_notifications` beat task (`access-notifications` R4, design D3).

Thin by construction — the task takes the lock, wires the use case and returns the report —
so what is worth testing here is exactly the two things the wiring can get wrong: losing the
lock must **skip without sending**, and the task must be registered under the name the
calendar refers to.
"""

import asyncio
from datetime import timedelta

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import settings
from app.scheduler.locks import task_lock
from app.scheduler.schedule import CADENCES, beat_schedule
from app.scheduler.tasks import dispatch_notifications


@pytest_asyncio.fixture
async def redis():
    """Own client per test, same reasoning as `test_locks.py`."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


def test_the_task_is_registered_under_the_name_the_calendar_uses() -> None:
    from app.worker import celery_app

    assert "dispatch_notifications" in CADENCES
    assert "dispatch_notifications" in celery_app.tasks
    assert any(
        entry["task"] == "dispatch_notifications" for entry in beat_schedule().values()
    )


def test_a_run_that_loses_the_lock_skips_without_touching_a_single_row(redis) -> None:
    """R4.2's shape, inherited from `celery-jobs`: a losing run is `skipped`, not a failure.

    It matters more here than for the clock jobs: two overlapping dispatchers would each
    burn their own attempt on the same row, which is exactly the duplicate bound design D4
    relies on the lock to hold.
    """

    async def hold_and_run() -> dict:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            async with task_lock(client, "dispatch_notifications", timedelta(seconds=10)):
                return await asyncio.to_thread(dispatch_notifications)
        finally:
            await client.aclose()

    report = asyncio.run(hold_and_run())

    assert report["skipped_locked"] is True
    assert report["task"] == "dispatch_notifications"


@pytest.mark.asyncio
async def test_an_unlocked_run_reports_per_tenant_instead_of_skipping(redis) -> None:
    """The other side of the same switch: with the lock free the task actually runs.

    It asserts the report shape, not a delivery — what gets delivered is
    `tests/notifications/test_dispatch.py`'s job, and this one only proves the wiring reaches
    the use case for every tenant.
    """
    report = await asyncio.to_thread(dispatch_notifications)

    assert report["skipped_locked"] is False
    assert report["task"] == "dispatch_notifications"
