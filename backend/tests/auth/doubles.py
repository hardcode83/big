"""In-memory doubles so the suite never requires a live Redis.

`steering/testing.md`: "Mockear solo en la frontera de adapters". These sit exactly
there — they replace the Redis adapter, never a repository or a domain service.
"""

import uuid


class InMemoryLoginThrottle:
    """Same contract as RedisLoginThrottle, with a clock the test controls."""

    def __init__(self, *, attempts_per_minute: int = 10, max_failures: int = 10) -> None:
        self._attempts_per_minute = attempts_per_minute
        self._max_failures = max_failures
        self.ip_attempts: dict[str, int] = {}
        self.failures: dict[uuid.UUID, int] = {}
        self.locked: set[uuid.UUID] = set()

    async def ip_attempt_allowed(self, client_ip: str) -> bool:
        self.ip_attempts[client_ip] = self.ip_attempts.get(client_ip, 0) + 1
        return self.ip_attempts[client_ip] <= self._attempts_per_minute

    async def is_account_locked(self, user_id: uuid.UUID) -> bool:
        return user_id in self.locked

    async def record_failure(self, user_id: uuid.UUID) -> None:
        self.failures[user_id] = self.failures.get(user_id, 0) + 1
        if self.failures[user_id] >= self._max_failures:
            self.locked.add(user_id)
            del self.failures[user_id]

    async def reset_failures(self, user_id: uuid.UUID) -> None:
        self.failures.pop(user_id, None)


class UnlimitedLoginThrottle(InMemoryLoginThrottle):
    """For tests about something other than throttling."""

    def __init__(self) -> None:
        super().__init__(attempts_per_minute=10**9, max_failures=10**9)


class CountingPasswordHasher:
    """Wraps a real hasher and counts the expensive operations.

    Used to prove every failed login path spends the same work (R1.4). Measuring wall
    time would be flaky in CI; counting the bcrypt calls asserts the same property
    deterministically.

    Counting `burn` as one unit is only honest because the dummy hash is prewarmed —
    otherwise the first burn of a process costs two bcrypt operations and this double
    would assert a property the implementation does not have. That prewarming is
    pinned separately in `test_password_hasher.py`.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.expensive_calls = 0

    async def hash(self, password: str) -> str:
        return await self._inner.hash(password)

    async def verify(self, password: str, password_hash: str) -> bool:
        self.expensive_calls += 1
        return await self._inner.verify(password, password_hash)

    async def burn(self, password: str) -> None:
        self.expensive_calls += 1
        await self._inner.burn(password)
