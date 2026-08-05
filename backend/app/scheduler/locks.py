"""Mutual exclusion for scheduled tasks (`celery-jobs` R4.2, R4.3, R1.5, design D9).

One mechanism covers both shapes of the problem: a run that outlives its own cadence, and
two `beat` processes alive at once during a redeploy. A task that cannot take its lock
reports `skipped` — not a failure, because the previous run is doing the work.

Deliberately not a library. `SET NX PX` plus a compare-and-delete is ten lines, and the
release has to be conditional or a slow run would delete the lock its successor already
took — the classic bug that makes a lock worse than no lock.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "scheduler:lock:"

#: Delete the key only if it still holds our token. A plain `DEL` would let a run that
#: overshot its TTL delete the lock a *different* run is now holding.
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def lock_ttl_for(cadence: timedelta) -> timedelta:
    """Three times the cadence (design D9).

    Long enough that a slow run keeps its lock, short enough that a worker killed mid-task
    frees it within a few ticks instead of wedging the job for ever (R4.3).
    """
    return cadence * 3


@asynccontextmanager
async def task_lock(redis: Redis, name: str, ttl: timedelta):
    """Yield `True` when this run owns the lock for `name`, `False` when someone else does.

    Never raises on contention — the caller reports `skipped` and ends normally, because a
    concurrent run is the system working as designed, not an error (R4.2).
    """
    key = f"{_KEY_PREFIX}{name}"
    token = str(uuid.uuid4())
    acquired = bool(
        await redis.set(key, token, nx=True, px=int(ttl.total_seconds() * 1000))
    )
    try:
        yield acquired
    finally:
        if acquired:
            try:
                await redis.eval(_RELEASE, 1, key, token)
            except Exception:
                # The TTL is the backstop: failing to release is a delay, never a wedge, so
                # it must not turn a successful run into a failed one.
                logger.warning("scheduler.lock_release_failed", extra={"task": name})
