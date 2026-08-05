"""A worker process runs many tasks; each one gets a fresh event loop (`celery-jobs` R1.6).

**This file exists because the suite did not have it and production broke.** Every other
test runs exactly one execution per process, so nothing exercised the thing that actually
matters about `asyncio.run` per task: the *second* run inherits whatever the first one left
behind, and anything bound to the first loop is now bound to a closed one.

Measured on the dev stack before the fix: `check_sla_breaches` alternated success and
`RuntimeError: Event loop is closed` on every other tick, because `app/core/redis.py`'s
process-wide client was created inside the first task's loop. The database side had already
been solved by design D1 (`NullPool`, worker-owned engine); Redis had not, and the symptom
had even appeared in `tests/scheduler/test_locks.py`, where it was worked around in a fixture
instead of being read as the production shape it was.

So these tests run things **twice in one process**, which is the only shape that catches it.
"""

import asyncio

from app.scheduler.runner import run_sync, worker_redis


def test_a_redis_client_from_one_run_is_not_reused_by_the_next() -> None:
    """The regression itself, at its smallest.

    Two `asyncio.run` cycles, each opening and closing its own client. If `worker_redis`
    ever goes back to caching one client per process, the second cycle raises
    `RuntimeError: Event loop is closed` here rather than in production at 03:00.
    """

    async def ping() -> bool:
        async with worker_redis() as redis:
            return bool(await redis.ping())

    assert run_sync(ping()) is True
    assert run_sync(ping()) is True
    assert run_sync(ping()) is True


def test_each_run_leaves_its_loop_closed() -> None:
    """Pins the premise the test above depends on, so it cannot pass for the wrong reason.

    Compares the loop *objects*, both kept alive here — an earlier version compared `id()`
    and was worthless, because the first loop is collected and the second can land on the
    same address.
    """
    loops = [run_sync(_current_loop()) for _ in range(2)]

    assert loops[0] is not loops[1]
    assert all(loop.is_closed() for loop in loops)


async def _current_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


def test_a_fresh_client_is_built_per_execution() -> None:
    """The contract that fixes the bug, stated directly: not cached.

    Deliberately NOT asserting that the old client raises afterwards — `aclose()` releases
    the pool but `redis.asyncio` reconnects transparently on the next command, so that
    assertion looked strict and proved nothing. What matters is that no client crosses a
    run boundary.
    """

    async def capture():
        async with worker_redis() as redis:
            await redis.ping()
            return redis

    first, second = run_sync(capture()), run_sync(capture())

    assert first is not second
