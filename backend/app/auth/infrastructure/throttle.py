"""Redis adapter for the LoginThrottle port (R5.1-R5.4, design D13).

Redis is the only store shared by the `backend` and `worker` processes, which is
what makes the limit hold with more than one uvicorn worker (R5.4).

ASSUMPTION (window): fixed window, not sliding. At the boundary between two minutes
an IP can make up to twice the limit in quick succession. PRD §22 asks for "10
intentos/min" without further precision, and the per-account lockout of R5.2 covers
exactly that burst, so a sliding counter is not worth its complexity.

ASSUMPTION (lockout release): PRD §22 requires blocking after 10 consecutive failed
attempts without saying how the block is lifted. A temporary, configurable lock
(default 15 minutes) is used instead of a permanent one, so no manual intervention
and no unlock endpoint — neither of which exists yet — is required.
"""

import uuid

from redis.asyncio import Redis

IP_WINDOW_SECONDS = 60


class RedisLoginThrottle:
    def __init__(
        self, redis: Redis, *, attempts_per_minute: int, max_failures: int, lockout_minutes: int
    ) -> None:
        self._redis = redis
        self._attempts_per_minute = attempts_per_minute
        self._max_failures = max_failures
        self._lockout_seconds = lockout_minutes * 60

    async def ip_attempt_allowed(self, client_ip: str) -> bool:
        key = f"login:ip:{client_ip}"
        # The TTL is (re)asserted on EVERY attempt, not only when INCR returns 1.
        # INCR and EXPIRE are two round trips: if the second one never runs — process
        # death, timeout, a Redis failover in between — the key stays without a TTL,
        # the counter never lapses and that IP is refused forever instead of for a
        # minute. With no trusted client-IP header today (design D12) every request
        # arrives with the same IP, so one lost EXPIRE would take login down for the
        # whole deployment. `NX` keeps the window from sliding forward on each hit.
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, IP_WINDOW_SECONDS, nx=True)
            attempts, _ = await pipe.execute()
        return attempts <= self._attempts_per_minute

    async def is_account_locked(self, user_id: uuid.UUID) -> bool:
        return await self._redis.exists(f"login:lock:{user_id}") == 1

    async def record_failure(self, user_id: uuid.UUID) -> None:
        key = f"login:fail:{user_id}"
        # Same atomicity requirement as the IP window (design D20): without an
        # expiry, a handful of typos spread over weeks would eventually lock an
        # account nobody is attacking, and a lost EXPIRE is enough to cause it.
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self._lockout_seconds, nx=True)
            failures, _ = await pipe.execute()
        if failures >= self._max_failures:
            await self._redis.set(f"login:lock:{user_id}", "1", ex=self._lockout_seconds)
            await self._redis.delete(key)

    async def reset_failures(self, user_id: uuid.UUID) -> None:
        await self._redis.delete(f"login:fail:{user_id}")

    async def clear_account_lock(self, user_id: uuid.UUID) -> None:
        """Drop the counter AND the lock (`auth-account-recovery` R3.5c, design D8).

        `reset_failures` deletes only `login:fail:<uid>`, which is all the login path needs.
        A completed recovery needs both: ten failures are what usually precede "I've lost my
        password", so leaving `login:lock:<uid>` alive would have the recovered user rejected
        by the very next login with the same generic `401` for the rest of the lockout window.

        One `DELETE` for both keys, so there is no window where the counter is gone and the
        lock is not.
        """
        await self._redis.delete(f"login:fail:{user_id}", f"login:lock:{user_id}")
