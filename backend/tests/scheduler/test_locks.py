"""`task_lock` against the real Redis (`celery-jobs` R4.2, R4.3, R1.5, design D9)."""

import asyncio
from datetime import timedelta

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import settings
from app.scheduler.locks import lock_ttl_for, task_lock


@pytest_asyncio.fixture
async def redis():
    """A client per test, not the shared `get_redis()` singleton.

    That singleton caches one client for the process, and a `redis.asyncio` connection is
    bound to the loop that opened it — pytest-asyncio gives each test its own loop, so the
    second test to touch it dies with "Event loop is closed" at teardown. The production
    path is unaffected: a worker process runs one loop per task via `asyncio.run` and
    `task_lock` takes the client as a parameter precisely so it can be given a fresh one.
    """
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def name(request):
    """A key per test, so a failed run cannot poison the next one."""
    return f"test-{request.node.name}"


@pytest.mark.asyncio
async def test_the_first_holder_gets_the_lock(redis, name) -> None:
    async with task_lock(redis, name, timedelta(seconds=5)) as acquired:
        assert acquired is True


@pytest.mark.asyncio
async def test_a_second_run_is_refused_while_the_first_holds_it(redis, name) -> None:
    async with task_lock(redis, name, timedelta(seconds=5)) as first:
        assert first is True
        async with task_lock(redis, name, timedelta(seconds=5)) as second:
            # R4.2: the second run reports skipped rather than raising or duplicating work.
            assert second is False


@pytest.mark.asyncio
async def test_the_lock_is_released_when_the_run_ends(redis, name) -> None:
    async with task_lock(redis, name, timedelta(seconds=5)):
        pass

    async with task_lock(redis, name, timedelta(seconds=5)) as acquired:
        assert acquired is True


@pytest.mark.asyncio
async def test_a_refused_run_does_not_release_the_holders_lock(redis, name) -> None:
    """The bug a plain `DEL` would introduce: the loser freeing the winner's lock."""
    async with task_lock(redis, name, timedelta(seconds=5)):
        async with task_lock(redis, name, timedelta(seconds=5)) as second:
            assert second is False
        # The refused run has exited its own context; the holder must still hold it.
        async with task_lock(redis, name, timedelta(seconds=5)) as third:
            assert third is False


@pytest.mark.asyncio
async def test_a_lock_whose_owner_vanished_expires(redis, name) -> None:
    """R4.3: a worker killed mid-task must not wedge the job for ever."""
    key = f"scheduler:lock:{name}"
    await redis.set(key, "someone-elses-token", px=150)

    async with task_lock(redis, name, timedelta(seconds=5)) as immediately:
        assert immediately is False

    await asyncio.sleep(0.25)

    async with task_lock(redis, name, timedelta(seconds=5)) as after_ttl:
        assert after_ttl is True


@pytest.mark.asyncio
async def test_the_ttl_outlives_three_cadences(redis, name) -> None:
    """Design D9: long enough for a slow run, short enough to self-heal."""
    assert lock_ttl_for(timedelta(minutes=1)) == timedelta(minutes=3)
    assert lock_ttl_for(timedelta(minutes=5)) == timedelta(minutes=15)


@pytest.mark.asyncio
async def test_the_lock_actually_expires_on_its_own_ttl(redis, name) -> None:
    async with task_lock(redis, name, timedelta(milliseconds=120)) as acquired:
        assert acquired is True
        await asyncio.sleep(0.25)
        # Its TTL passed while it was still "running": the next run may proceed, which is
        # exactly the trade design D9 accepts to avoid a permanent wedge.
        async with task_lock(redis, name, timedelta(seconds=5)) as successor:
            assert successor is True
