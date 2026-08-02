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


# --- fakes for the user-administration use cases (user-management R1-R4, R6) --------
#
# `steering/testing.md`: "application/: unit tests con **fakes** en memoria de los puertos (no
# la DB real, no mocks de SQLAlchemy)". These implement the ports faithfully enough that the
# use cases cannot tell — including the parts that matter for the invariants: `apply_changes`
# writes only what it is given, and the tenant clause is honoured everywhere.


class FakeUserRepository:
    """In-memory `UserRepository`, keyed by (tenant_id, user_id)."""

    def __init__(self) -> None:
        self.users: dict[tuple, object] = {}
        self.locks_taken: list[uuid.UUID] = []
        self.applied: list[tuple] = []
        self.duplicate_emails: set[str] = set()

    # -- helpers for the tests, not part of the port --
    def seed(self, user) -> object:
        self.users[(user.tenant_id, user.id)] = user
        return user

    async def get(self, tenant_id, user_id):
        return self.users.get((tenant_id, user_id))

    async def get_active_by_id(self, tenant_id, user_id):
        from app.auth.domain.enums import UserStatus

        user = self.users.get((tenant_id, user_id))
        return user if user is not None and user.status is UserStatus.ACTIVE else None

    async def find_by_email_globally(self, email):
        from app.auth.domain.value_objects import normalize_email

        wanted = normalize_email(email)
        return next((u for u in self.users.values() if u.email == wanted), None)

    async def list(self, tenant_id, filters, *, page, per_page):
        from app.auth.domain.repositories import UserPage, offset_for

        rows = [u for (t, _), u in self.users.items() if t == tenant_id]
        if filters.role is not None:
            rows = [u for u in rows if u.role is filters.role]
        if filters.status is not None:
            rows = [u for u in rows if u.status is filters.status]
        rows.sort(key=lambda u: (u.name, str(u.id)))
        start = offset_for(page=page, per_page=per_page)
        return UserPage(items=tuple(rows[start : start + per_page]), total=len(rows))

    async def add(self, tenant_id, user):
        from app.auth.domain.exceptions import EmailAlreadyExistsError

        if user.email in self.duplicate_emails or any(
            u.email == user.email for u in self.users.values()
        ):
            raise EmailAlreadyExistsError("That email address is already in use")
        self.users[(tenant_id, user.id)] = user

    async def apply_changes(self, tenant_id, user_id, values):
        from app.auth.domain.exceptions import EmailAlreadyExistsError

        if (tenant_id, user_id) not in self.users:
            raise ValueError("Cannot update a user that does not belong to this tenant")
        if "email" in values and values["email"] in self.duplicate_emails:
            raise EmailAlreadyExistsError("That email address is already in use")
        self.applied.append((tenant_id, user_id, dict(values)))

    async def count_active_owners_excluding(self, tenant_id, user_id):
        from app.auth.domain.enums import UserRole, UserStatus

        return sum(
            1
            for (t, i), u in self.users.items()
            if t == tenant_id
            and i != user_id
            and u.role is UserRole.TENANT_OWNER
            and u.status is UserStatus.ACTIVE
        )

    async def lock_tenant_for_admin(self, tenant_id):
        self.locks_taken.append(tenant_id)

    async def touch_last_login(self, tenant_id, user_id, now):  # pragma: no cover
        raise AssertionError("administration must not touch last_login_at")


class FakeAuditLogRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list = []
        self.fail = fail

    async def add(self, tenant_id, entry):
        if self.fail:
            raise RuntimeError("audit write failed")
        self.entries.append((tenant_id, entry))


class FakeSessionRepository:
    """Only the two methods user administration uses; the rest would be dead weight."""

    def __init__(self) -> None:
        self.revocations: list[tuple] = []

    async def revoke_all_for_user(self, tenant_id, user_id, reason, now):
        self.revocations.append((tenant_id, user_id, reason))
        return 1

    async def revoke_family(self, tenant_id, family_id, reason, now):  # pragma: no cover
        raise AssertionError("administration revokes by user, not by family")


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class StubPasswordHasher:
    """Deterministic and cheap: bcrypt at real cost would dominate these unit tests."""

    def __init__(self) -> None:
        self.hashed: list[str] = []

    async def hash(self, password: str) -> str:
        self.hashed.append(password)
        return f"hashed::{password}"

    async def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed::{password}"

    async def burn(self, password: str) -> None:  # pragma: no cover
        return None
