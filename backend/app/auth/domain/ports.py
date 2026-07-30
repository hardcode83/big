"""Ports owned by the auth domain (R6.5, design D6/D16).

Every port speaks in domain entities, never ORM models, and every method that
touches a tenant-scoped entity takes `tenant_id` explicitly — with one deliberate
exception, `find_by_email_globally`, named so it is impossible to mistake for an
oversight (design D16).
"""

import uuid
from datetime import datetime, timedelta
from typing import Protocol

from app.auth.domain.entities import User, UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole
from app.auth.domain.value_objects import AccessTokenClaims, RefreshTokenClaims


class UserRepository(Protocol):
    async def get_active_by_id(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        """The user, only if both the user and its tenant are ACTIVE (R4.5, design D7)."""
        ...

    async def find_by_email_globally(self, email: str) -> User | None:
        """The only unscoped query behind this port (design D16).

        Login is anonymous: there is no tenant yet, so the address has to identify
        the user on its own. It can, because a normalised email is unique across the
        whole installation (design D16, ADR 0005) — hence at most one user, and no
        "which of these did you mean" case for the caller to handle.
        """
        ...

    async def touch_last_login(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> None:
        """Record a successful login, and nothing else (R1.2).

        Deliberately narrow instead of a general `save(user)`. Copying a whole entity
        back would write `status`, `role` and `password_hash` from values read earlier in
        the request, so a suspension, a demotion or a password change committed in
        between would be silently reverted — a login that un-suspends the account
        somebody just disabled. `tenant_id` is the ACTING tenant, from RequestContext.
        """
        ...


class TenantStatusReader(Protocol):
    async def is_active(self, tenant_id: uuid.UUID) -> bool: ...


class SessionRepository(Protocol):
    """No unconditional `save`, on purpose.

    A method that writes `used_at`/`revoked_at` without checking them is the footgun
    next to `consume()`: the next person needing to mark a session used would find it,
    use it, and reintroduce the read-then-write race of R2.1. Every mutation here is
    either conditional (`consume`) or set-based (`revoke_family`).
    """

    async def add(self, tenant_id: uuid.UUID, session: UserSession) -> None:
        """`tenant_id` is the acting tenant; creating a session for another one is refused."""
        ...

    async def get(self, tenant_id: uuid.UUID, session_id: uuid.UUID) -> UserSession | None: ...

    async def consume(self, tenant_id: uuid.UUID, session_id: uuid.UUID, now: datetime) -> bool:
        """Mark a session used only if it is still usable; True if we won (R2.1, R2.2).

        The check and the write must be ONE statement, and it must test every condition
        that makes a session unusable — used, revoked, expired. Splitting the check from
        the write lets two concurrent presentations of the same refresh token both
        succeed, and lets a concurrent revocation lose the tie.
        """
        ...

    async def revoke_family(
        self,
        tenant_id: uuid.UUID,
        family_id: uuid.UUID,
        reason: SessionRevokedReason,
        now: datetime,
    ) -> int:
        """Revoke every not-yet-revoked session of a lineage; returns how many (R2.2)."""
        ...


class PasswordHasher(Protocol):
    """Async on purpose, even though hashing is pure computation (design D21).

    bcrypt costs ~250 ms of CPU per call at the configured cost. Run on the event
    loop that stalls EVERY concurrent request for that long, so the adapter runs it
    in a worker thread — and a port whose methods are awaited is what forces every
    caller through that boundary. Declaring them sync would make the blocking
    version the easy one to write, which is how it got that way in the first place.
    """

    async def hash(self, password: str) -> str: ...

    async def verify(self, password: str, password_hash: str) -> bool: ...

    async def burn(self, password: str) -> None:
        """Do the same work as `verify` against a dummy hash, and discard the result.

        Exists so every failed login costs the same (R1.4). Without it the paths that
        never reach `verify` — unknown address, locked account — answer in
        milliseconds while a real one takes as long as bcrypt does, which turns the
        endpoint into a user-enumeration oracle by latency even though the response
        bodies are identical.
        """
        ...


class UnitOfWork(Protocol):
    async def commit(self) -> None:
        """The transactional boundary of a business operation (design D10).

        Declared as a port so `application/` never imports SQLAlchemy: the
        dependency rule points inwards.
        """
        ...


class TokenCodec(Protocol):
    @property
    def access_ttl_seconds(self) -> int: ...

    @property
    def refresh_ttl(self) -> timedelta: ...

    def issue_access(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role: UserRole,
        family_id: uuid.UUID,
        now: datetime,
    ) -> str: ...

    def issue_refresh(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role: UserRole,
        session_id: uuid.UUID,
        family_id: uuid.UUID,
        now: datetime,
    ) -> str: ...

    def decode_access(self, token: str) -> AccessTokenClaims: ...

    def decode_refresh(self, token: str) -> RefreshTokenClaims: ...


class LoginThrottle(Protocol):
    async def ip_attempt_allowed(self, client_ip: str) -> bool:
        """Count this attempt and report whether the IP is still under the limit (R5.1)."""
        ...

    async def is_account_locked(self, user_id: uuid.UUID) -> bool: ...

    async def record_failure(self, user_id: uuid.UUID) -> None:
        """Count a failed attempt, locking the account at the threshold (R5.2)."""
        ...

    async def reset_failures(self, user_id: uuid.UUID) -> None: ...
