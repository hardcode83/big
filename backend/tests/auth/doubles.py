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

    async def clear_account_lock(self, user_id: uuid.UUID) -> None:
        """Both the counter and the lock (`auth-account-recovery` R3.5c, design D8).

        Faithful to `RedisLoginThrottle.clear_account_lock`, which is what makes the
        difference from `reset_failures` observable in a use-case test: a double that only
        dropped the counter would let a broken implementation pass.
        """
        self.failures.pop(user_id, None)
        self.locked.discard(user_id)


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

    **`hash` is deliberately NOT counted**, so this double measures the cost of REFUSAL
    paths only — `verify` and `burn` are the two calls a rejection can reach. Do not reach
    for it to bound the total bcrypt cost of a successful operation: a successful password
    change spends a `verify` AND a `hash`, and only the first would show up here. Named by
    the security panel of `auth-account-recovery` section 4, which used this double to prove
    a locked account pays zero bcrypt and needed the limit of the claim to be explicit.
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


class FakePasswordResetTokenRepository:
    """In-memory `PasswordResetTokenRepository` (`auth-account-recovery` R2, R3).

    `consume_globally` is deliberately faithful about the one property that matters: it is
    **atomic** — the usability check and the write are one indivisible step here too, so a use
    case that presented the same token twice gets one success and one None, exactly as the
    single conditional UPDATE of design D1 behaves. A double that checked and then wrote would
    hide the race the real adapter is built to close.
    """

    def __init__(self) -> None:
        self.tokens: dict[uuid.UUID, object] = {}

    def seed(self, token) -> object:
        self.tokens[token.id] = token
        return token

    async def add(self, tenant_id, token) -> None:
        if token.tenant_id != tenant_id:
            raise ValueError("Cannot store a reset token for another tenant")
        self.tokens[token.id] = token

    async def consume_globally(self, token_hash, now):
        for token in self.tokens.values():
            if token.token_hash == token_hash and token.is_usable(now):
                token.used_at = now
                return token
        return None

    async def count_live(self, tenant_id, user_id, now) -> int:
        return sum(
            1
            for t in self.tokens.values()
            if t.tenant_id == tenant_id and t.user_id == user_id and t.is_usable(now)
        )

    async def revoke_oldest_beyond(
        self, tenant_id, user_id, keep_newest, now, older_than
    ) -> int:
        """Same ordering as the adapter — newest first, `id` as tiebreaker — so a use-case
        test cannot pass against a double that keeps a different token than production would.
        """
        live = [
            t
            for t in self.tokens.values()
            if t.tenant_id == tenant_id and t.user_id == user_id and t.is_usable(now)
        ]
        live.sort(key=lambda t: (t.created_at, t.id), reverse=True)
        revoked = 0
        for token in live[max(keep_newest, 0) :]:
            # Same grace boundary as the adapter: a link newer than `older_than` is never
            # retired, so a use-case test cannot pass against a double that ignores it.
            if token.created_at > older_than:
                continue
            token.revoked_at = now
            revoked += 1
        return revoked

    async def revoke_other_live(self, tenant_id, user_id, keep_id, now) -> int:
        revoked = 0
        for token in self.tokens.values():
            if (
                token.tenant_id == tenant_id
                and token.user_id == user_id
                and token.id != keep_id
                and token.is_usable(now)
            ):
                token.revoked_at = now
                revoked += 1
        return revoked


class CapturingEmailAdapter:
    """A `NotificationAdapter` that keeps what it was asked to send.

    The only way to assert design D2's central property: the SENT text carries the link and
    the STORED row does not. The real `ConsoleEmailAdapter` cannot serve here — it is
    forbidden from logging content or recipient, which is exactly why the flow cannot be
    exercised by hand in dev.
    """

    def __init__(self, *, delivered: bool = True) -> None:
        self.sent: list[dict] = []
        self._delivered = delivered

    async def send(self, *, recipient_contact, subject, body, channel):
        from app.notifications.domain.results import (
            NotificationErrorCode,
            NotificationResult,
        )

        self.sent.append(
            {
                "recipient_contact": recipient_contact,
                "subject": subject,
                "body": body,
                "channel": channel,
            }
        )
        return (
            NotificationResult.ok()
            if self._delivered
            else NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR)
        )


class FakeNotificationLogRepository:
    def __init__(self) -> None:
        self.rows: list[tuple] = []

    async def add(self, tenant_id, log) -> None:
        if log.tenant_id != tenant_id:
            raise ValueError("Cannot store a notification for another tenant")
        self.rows.append((tenant_id, log))


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
