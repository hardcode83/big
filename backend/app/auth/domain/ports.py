"""Ports owned by the auth domain (R6.5, design D6/D16).

Every port speaks in domain entities, never ORM models, and every method that
touches a tenant-scoped entity takes `tenant_id` explicitly — with deliberate
exceptions that serve anonymous endpoints, where there is no tenant yet. Two of them
live on this port: `find_by_email_globally` (design D16 of `auth-tenancy`) and
`consume_globally` (design D3 of `auth-account-recovery`).

**Their enumeration is not here, and it is no longer prose anywhere.** The reads that resolve
a tenant out of the row they read call `require_unmarked_session` (`app/core/db.py`), so the
set of its callers is the audited census of that class — not of every query in the system that
runs without a tenant, a distinction `tests/test_unscoped_reads.py` states and pins. This paragraph used to say "two
deliberate exceptions… both named `*_globally` so a grep for that suffix enumerates every
cross-tenant read": `guest-portal-api` added a third that lives on another port and is
**not** named that way, so neither the count nor the suffix-grep held. It then pointed at
one docstring as the single copy to trust, and that copy went stale too. Counting here was one
of the copies that had to be corrected everywhere — the failure mode rule 11 of
`steering/security.md` documents about itself, and it recurred inside the change that removed
the count: its own review had to correct the number twice more before the census replaced it.
So no number is restated here; `tests/test_unscoped_reads.py` is the only place it exists.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Protocol

from app.auth.domain.entities import PasswordResetToken, User, UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole
from app.auth.domain.repositories import UserFilters, UserPage
from app.auth.domain.value_objects import AccessTokenClaims, RefreshTokenClaims


class UserRepository(Protocol):
    async def get_active_by_id(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        """The user, only if both the user and its tenant are ACTIVE (R4.5, design D7)."""
        ...

    async def find_by_email_globally(self, email: str) -> User | None:
        """The only unscoped query behind THIS port (design D16).

        There are others elsewhere, and **their enumeration is not prose**: the reads that
        resolve a tenant out of the row they read call `require_unmarked_session`
        (`app/core/db.py`), so the set of its callers is the audited census of that class, and
        `tests/test_unscoped_reads.py` asserts it — along with the reads it does not cover. This sentence used to say
        "two in total; both named `*_globally`" — `guest-portal-api` added a third that carries
        neither this port nor that suffix, so counting here was one of six copies of a fact
        that then had to be corrected in six places. It then deferred to one docstring as the
        single copy to trust, and that copy went stale too.

        Login is anonymous: there is no tenant yet, so the address has to identify
        the user on its own. It can, because a normalised email is unique across the
        whole installation (design D16, ADR 0005) — hence at most one user, and no
        "which of these did you mean" case for the caller to handle.
        """
        ...

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        """One user of this tenant, whatever its status (user-management R2.6).

        Distinct from `get_active_by_id`, which is the authentication lookup and resolves
        only ACTIVE users of ACTIVE tenants. Administration has to see a suspended account
        to be able to reactivate it.

        Returns `None` for a user of another tenant just as for one that does not exist —
        that is what lets the use case answer `404` without ever asking "does this exist
        somewhere else?" (R7.1).
        """
        ...

    async def list(
        self, tenant_id: uuid.UUID, filters: "UserFilters", *, page: int, per_page: int
    ) -> "UserPage":
        """Filtered, ordered and paginated (R2.1). The order must be stable (design D17)."""
        ...

    async def add(self, tenant_id: uuid.UUID, user: User) -> None:
        """Persist a new user; refuses an entity of another tenant.

        Raises `EmailAlreadyExistsError` when the normalised address already exists ANYWHERE
        in the installation — the `uq_users_lower_email` index decides, not a prior read
        (design D11): two concurrent creates with the same address both pass a check and only
        one can pass the constraint.
        """
        ...

    async def apply_changes(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, values: "Mapping[str, object]"
    ) -> None:
        """Write ONLY the named columns of one user (user-management design D21).

        Deliberately not a `save(user)`. `auth-tenancy` deleted `UserRepository.save` (its
        design D5) because copying the whole row back can revert a suspension, a demotion or
        a password change committed between the read and the write, and
        `tests/auth/test_repositories.py::test_no_unconditional_write_primitive_came_back`
        guards the name against coming back. A partial write cannot revert a column it does
        not name, which is strictly stronger than an allow-list of "mutable" columns —
        `role` and `status` would be in such a list.

        Identity columns are never writable through here: `tenant_id` (a repository able to
        move a row between tenants defeats the isolation rule), `id`, and `last_login_at`
        (owned by `touch_last_login`).
        """
        ...

    async def count_active_owners_excluding(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        """How many OTHER users are ACTIVE `TENANT_OWNER`s (R3.6, design D6).

        Excludes `user_id` so the target cannot count itself as the owner that survives its
        own demotion. Only trustworthy under the lock below.
        """
        ...

    async def lock_tenant_for_admin(self, tenant_id: uuid.UUID) -> None:
        """Serialise administrative writes on this tenant (R3.6, design D6).

        `SELECT ... FROM tenants WHERE id = :t FOR UPDATE`. Needed because the last-owner
        rule counts OTHER rows: the single-statement idiom of `SessionRepository.consume`
        does not help, since Postgres only re-evaluates the WHERE for the row being written.
        Two concurrent demotions of two different owners would each see the other as active
        and both succeed, leaving the tenant with none.
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

    async def revoke_all_for_user(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: SessionRevokedReason,
        now: datetime,
    ) -> int:
        """Revoke EVERY family of one user; returns how many rows (user-management R3.7, R4.2).

        Distinct from `revoke_family` on purpose, and not expressible with it: an
        administrator deactivating an account or resetting its password acts on somebody
        else, whose families they do not know — the caller has a `user_id`, never a
        `family_id`. Iterating families in the use case would need a list query that
        exists only to feed this, and would stop being atomic.

        Idempotent: a session already revoked keeps its original reason and timestamp, so
        a second call returns 0 rather than rewriting history.
        """
        ...


class PasswordResetTokenRepository(Protocol):
    """Recovery links (`auth-account-recovery` R3, design D1/D3/D7).

    No unconditional `save`, for the same reason `SessionRepository` refuses one: the only
    mutation that decides anything is `consume_globally`, and it is conditional.
    """

    async def add(self, tenant_id: uuid.UUID, token: "PasswordResetToken") -> None:
        """`tenant_id` is the acting tenant; a token for another one is refused."""
        ...

    async def consume_globally(
        self, token_hash: str, now: datetime
    ) -> "PasswordResetToken | None":
        """Spend a token if it is still spendable; return the row, or None (R3.2, design D1).

        **One of the system's unscoped queries** — specifically one of those that resolve a
        tenant out of the row they read, whose census is the set of callers of
        `require_unmarked_session` (`app/core/db.py`), asserted by
        `tests/test_unscoped_reads.py` together with the reads that fall outside it. This said "THE SECOND … so a grep for the two
        `*_globally` methods still enumerates every cross-tenant read that exists";
        `guest-portal-api` added a third that is not named that way, so neither the count nor
        the grep held, and the docstring this then deferred to went stale in its turn.
        Unscoped because the endpoint is anonymous:
        there is no tenant yet, and the token IS the credential. Its unique index identifies it
        across the whole installation, so the `tenant_id` comes OUT of the row found, never in
        from the request — which is why the request schema has no field for one. Embedding the
        tenant in the token was rejected in design D3 precisely because the scope would then be
        supplied by the attacker.

        The check and the write must be ONE statement testing every condition that makes a
        token unspendable — used, revoked, expired. Splitting them lets two concurrent
        presentations of the same link both reset the password, which is the whole point of
        R3.2. Returning the row rather than a bool is what lets the caller learn the
        `user_id`/`tenant_id` it could not know beforehand.
        """
        ...

    async def count_live(self, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> int:
        """How many unspent, unrevoked, unexpired tokens this account already has (R2.5, D7).

        Scoped by tenant, unlike `consume_globally`: by the time this runs the account has
        been resolved, so the tenant is known and there is no reason to go without it.
        """
        ...

    async def revoke_oldest_beyond(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        keep_newest: int,
        now: datetime,
        older_than: datetime,
    ) -> int:
        """Revoke this account's live tokens except the `keep_newest` most recent; count them.

        What makes the per-account cap of R2.5 a bound rather than a suppression tool
        (design D7, amended). Discarding a request once the cap was reached let anyone who
        knew an address silence the real owner's recovery for the token lifetime, with no
        signal to them. Revoking the oldest instead means a legitimate request always wins
        while the number of coexisting valid links stays capped.

        Takes `keep_newest` rather than revoking exactly one, so lowering
        `PASSWORD_RESET_MAX_LIVE_TOKENS` in configuration also converges instead of leaving
        an account permanently over its new cap.

        `older_than` is the grace boundary: a token created after it is NEVER retired, so a
        freshly issued link survives the window in which its owner clicks it. Returning 0 is
        therefore meaningful — it says every live token is inside the grace and the caller
        should drop the request rather than emit, which is what keeps per-account mail bounded
        across IPs (R2.5, design D7's grace amendment).
        """
        ...

    async def revoke_other_live(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, keep_id: uuid.UUID, now: datetime
    ) -> int:
        """Revoke every live token of this account except `keep_id`; returns how many (R3.5b).

        `keep_id` is the token just consumed. Excluding it keeps the row honest: it is
        `used`, not `revoked`, and relabelling it would lose the distinction between a link
        somebody spent and a link this reset invalidated.
        """
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

    async def clear_account_lock(self, user_id: uuid.UUID) -> None:
        """Drop BOTH the failure counter and the lock (`auth-account-recovery` R3.5c, D8).

        Distinct from `reset_failures`, which only deletes the counter. That is enough for the
        login path — a successful login implies the account was not locked — but not here:
        ten failed attempts are exactly what precedes "I've lost my password", so a completed
        recovery that left `login:lock:<uid>` standing would have the user rejected by the
        very next login with the same generic `401`, for up to fifteen minutes. Recovering
        without this recovers nothing.
        """
        ...
