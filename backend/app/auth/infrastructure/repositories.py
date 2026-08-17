"""SQLAlchemy adapters for the auth ports (R4.2, R6.5, design D6/D10).

Every method takes `tenant_id` and filters on it — except two deliberate exceptions,
`find_by_email_globally` (design D16 of `auth-tenancy`) and `consume_globally` (design
D3 of `auth-account-recovery`). Every other cross-tenant need goes through one of them
rather than hand-rolling another.

**The system-wide count of unscoped queries is asserted in exactly one place**, the
docstring of `find_by_email_globally` below, and everything else cites it. It used to be
stated here too, as "the only unscoped queries in the system... both named `*_globally`,
so a grep for that suffix enumerates every cross-tenant read that exists" — and both
halves of that are now false: `guest-portal-api` added a third,
`SqlAlchemyGuestAccessTokenRepository.find_live_by_token_hash`, which is not in this
module and does not carry the suffix. Three copies of the count lived in this one file
and the merge that created the third only corrected one of them; the architecture panel
found the other two. That enumeration is the audit control for rule 1 of
`steering/security.md`, so it gets the treatment rule 11 of the same document prescribes
for its own contract: one formulation, everyone else cites it.

No method commits: the transactional boundary is the use case (design D10).
"""

import uuid
from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.entities import PasswordResetToken, User, UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import EmailAlreadyExistsError
from app.auth.domain.repositories import UserFilters, UserPage, offset_for
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.models import (
    PasswordResetTokenModel,
    UserModel,
    UserSessionModel,
)
from app.core.tenancy import CrossTenantWriteError
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantModel

# The functional unique index of ADR 0005. Named here so the translation to `409` matches THIS
# constraint and re-raises anything else (design D11).
LOWER_EMAIL_CONSTRAINT = "uq_users_lower_email"

# Columns `apply_changes` may write. `email` is included — it is the login identity and can be
# corrected — with the duplicate translation that implies.
WRITABLE_COLUMNS = frozenset(
    {
        "name",
        "email",
        "phone",
        "preferred_language",
        "role",
        "status",
        "password_hash",
        # Written alongside `password_hash` and only ever by whoever writes it
        # (`auth-account-recovery` design D5).
        "must_change_password",
    }
)

# Named separately from "unknown" so the error says WHY, not just "no".
FORBIDDEN_UPDATE_COLUMNS = frozenset({"tenant_id", "id", "last_login_at", "created_at"})

# Written together or not at all (`auth-account-recovery` design D5). The flag describes the
# hash beside it, so a write that names one and not the other leaves it describing a password
# that is no longer there.
COUPLED_PASSWORD_COLUMNS = frozenset({"password_hash", "must_change_password"})


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_by_id(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        """One joined query per authenticated request (design D7).

        Both the user and its tenant must be ACTIVE, so suspending either takes
        effect immediately instead of waiting for the access token to expire.
        """
        result = await self._session.execute(
            select(UserModel)
            .join(TenantModel, TenantModel.id == UserModel.tenant_id)
            .where(
                UserModel.tenant_id == tenant_id,
                UserModel.id == user_id,
                UserModel.status == UserStatus.ACTIVE,
                TenantModel.status == TenantStatus.ACTIVE,
            )
        )
        model = result.scalar_one_or_none()
        return _to_user(model) if model is not None else None

    async def find_by_email_globally(self, email: str) -> User | None:
        """ONE OF THE THREE unscoped queries in the system (design D16).

        **Its callers are whatever `grep -rn find_by_email_globally backend/app` returns**,
        and that sentence is deliberately not a list. Every caller goes through here rather
        than writing its own unscoped select, which is what makes the grep exhaustive — so
        an enumeration adds nothing a reader cannot get in one command, and subtracts the
        one thing they need, which is being right. It used to name two ("the anonymous
        login and the bootstrap conflict check") while there were five; `seed-data-demo`'s
        security panel found it stale rather than incomplete, having already gone stale
        twice for the count below. A list nobody can be made to update is worse than no
        list.

        **One condition binds every caller:** this lookup must run on a session that is NOT
        marked with a tenant. "Unscoped" is a property of the STATEMENT, not of this method
        — mark the session and the `do_orm_execute` listener of `app/core/db.py` adds the
        tenant clause here like anywhere else, this returns `None` for a neighbour's
        address, and the caller learns about the conflict from `uq_users_lower_email`
        instead of from its own message.

        **The condition is on the SEQUENCE, and deliberately not on the kind of caller.**
        The tempting shortcut is to derive it from the entry point — "`get_authenticated_
        request` is the only thing that marks a session in a request, so an anonymous route
        never has one" — and that shortcut is false: `SessionTenantBinder.bind`
        (`app/guests/infrastructure/portal_repositories.py`) marks the request's session on
        the guest-portal routes, which are anonymous. Believing it would license a caller
        placed anywhere after that bind, whose statement is then silently tenant-scoped and
        which therefore reports no conflict at all — the failure this method exists to
        avoid. So the rule is the unglamorous one: **this lookup must run before anything
        binds that session, whoever binds it.** `app/cli/seed_demo.py` both reads and binds,
        and reads first, which is the shape any caller that binds has to copy.

        The other two, both added for the same structural reason — an anonymous caller
        presents a credential and the row is what resolves the tenant, so there is nothing
        to filter by when the query runs:

        * `SqlAlchemyPasswordResetTokenRepository.consume_globally`
          (`auth-account-recovery`), named the same way on purpose;
        * `SqlAlchemyGuestAccessTokenRepository.find_live_by_token_hash`
          (`app/guests/infrastructure/portal_repositories.py`, `guest-portal-api`).

        **The count is the audit control for rule 1 of `steering/security.md`, and it has
        now gone stale twice.** This sentence said "THE ONLY" until the section 3 security
        panel of `guest-portal-api` found the portal lookup missing from it — and then said
        "THE TWO" twice over, because that change and `auth-account-recovery` each added a
        third case and each updated this line to two, in parallel branches. The merge is
        where that surfaced. A reviewer trusting the number would have audited two of three
        either way, so: whoever adds an unscoped query updates the number **and** adds a
        bullet, exactly as `app/core/db.py`'s second limit names its own cases.

        Login is anonymous, so there is no tenant yet — the address alone has to
        identify the user, and it does: `uq_users_lower_email` makes a normalised
        email unique across the whole installation, not per tenant (design D16,
        ADR 0005). Matching is case-insensitive because an email is not
        case-sensitive to the person typing it, and the index is built on
        `lower(email)` so the guarantee is expressed in the same terms as the lookup.

        `scalar_one_or_none` therefore raises rather than picking a winner if two rows
        ever match. That is deliberate: it can only happen if the unique index is
        gone, and in that state authenticating whichever row sorted first is worse
        than a 500 — it would be a silent cross-tenant account takeover. Fails closed.

        The comparison is a plain equality against the Python-normalised address —
        never `lower()` inside the query — see `normalize_email` and design D19.
        """
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == normalize_email(email))
        )
        model = result.scalar_one_or_none()
        return _to_user(model) if model is not None else None

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        """One user of this tenant, whatever its status (user-management R2.6).

        No status clause on purpose, unlike `get_active_by_id`: administration must be able
        to see a suspended account in order to reactivate it. The tenant clause is what makes
        a user of another tenant indistinguishable from one that does not exist (R7.1).
        """
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.tenant_id == tenant_id, UserModel.id == user_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_user(model) if model is not None else None

    async def list(
        self, tenant_id: uuid.UUID, filters: UserFilters, *, page: int, per_page: int
    ) -> UserPage:
        """A page of the tenant's roster (R2.1, R2.3, R2.4, design D17).

        Ordered by `name` with `id` as the tiebreaker. The tiebreaker is not cosmetic: two
        users called "Ana" would otherwise come back in whatever order Postgres felt like per
        query, so paginating could show one row twice and skip another.
        """
        conditions = [UserModel.tenant_id == tenant_id]
        if filters.role is not None:
            conditions.append(UserModel.role == filters.role)
        if filters.status is not None:
            conditions.append(UserModel.status == filters.status)

        total = await self._session.scalar(
            select(func.count()).select_from(UserModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(UserModel)
            .where(*conditions)
            .order_by(UserModel.name.asc(), UserModel.id.asc())
            .limit(per_page)
            .offset(offset_for(page=page, per_page=per_page))
        )
        return UserPage(
            items=tuple(_to_user(model) for model in rows.scalars().all()),
            total=int(total or 0),
        )

    async def add(self, tenant_id: uuid.UUID, user: User) -> None:
        """Insert a new user, letting the index decide about duplicates (R1.4, design D11)."""
        if user.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="user",
                entity_tenant_id=user.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            UserModel(
                id=user.id,
                tenant_id=user.tenant_id,
                name=user.name,
                email=user.email,
                password_hash=user.password_hash,
                role=user.role,
                phone=user.phone,
                status=user.status,
                preferred_language=user.preferred_language,
                must_change_password=user.must_change_password,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            # The constraint is the authority, not a prior read: two concurrent creates with
            # the same address both pass a lookup and only one can pass this (design D11).
            #
            # Matched by NAME rather than catching every IntegrityError: a foreign-key
            # violation is not a duplicate address, and answering `409` for it would be a
            # lie the caller cannot act on.
            if LOWER_EMAIL_CONSTRAINT in str(error.orig):
                raise EmailAlreadyExistsError(
                    "That email address is already in use"
                ) from error
            raise

    async def apply_changes(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, values: Mapping[str, object]
    ) -> None:
        """Write only the named columns (user-management design D21).

        NOT a `save(user)`: `auth-tenancy` deleted that primitive because copying the whole
        row back reverts whatever was committed in between, and a partial write cannot revert
        a column it does not name.

        The duplicate-address translation is here too, because `email` is one of the columns
        this may write.
        """
        if not values:
            return
        forbidden = set(values) & FORBIDDEN_UPDATE_COLUMNS
        if forbidden:
            raise ValueError(
                f"Columns {sorted(forbidden)} are not writable through apply_changes: "
                "tenant_id and id are identity, last_login_at belongs to touch_last_login"
            )
        unknown = set(values) - WRITABLE_COLUMNS
        if unknown:
            raise ValueError(f"Unknown user columns: {sorted(unknown)}")
        # `auth-account-recovery` design D5: the two columns are written together or not at
        # all. The entity guarantees it — `set_password_hash` is the sole owner of both — but
        # this is the second write path, and it takes a `Mapping`, so without this check a
        # future caller could name one and not the other. D5's own argument for merging the
        # two entity methods is exactly that "dos métodos que deben llamarse juntos son dos
        # que alguien llamará por separado"; leaving the pairing to caller discipline here
        # would reintroduce at the repository what the entity closed.
        if len(COUPLED_PASSWORD_COLUMNS & set(values)) == 1:
            raise ValueError(
                f"{sorted(COUPLED_PASSWORD_COLUMNS)} must be written together: a password "
                "replaced without deciding whether it is temporary leaves the flag "
                "describing the wrong hash (auth-account-recovery design D5)"
            )

        try:
            result = await self._session.execute(
                update(UserModel)
                .where(UserModel.tenant_id == tenant_id, UserModel.id == user_id)
                .values(**values)
            )
        except IntegrityError as error:
            if LOWER_EMAIL_CONSTRAINT in str(error.orig):
                raise EmailAlreadyExistsError(
                    "That email address is already in use"
                ) from error
            raise
        if result.rowcount != 1:
            raise ValueError("Cannot update a user that does not belong to this tenant")

    async def count_active_owners_excluding(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        """OTHER active owners of this tenant (R3.6, design D6).

        Excluding the target is what makes the count usable: including it, the target would
        count itself as the owner surviving its own demotion and the rule would never fire.
        """
        total = await self._session.scalar(
            select(func.count())
            .select_from(UserModel)
            .where(
                UserModel.tenant_id == tenant_id,
                UserModel.id != user_id,
                UserModel.role == UserRole.TENANT_OWNER,
                UserModel.status == UserStatus.ACTIVE,
            )
        )
        return int(total or 0)

    async def lock_tenant_for_admin(self, tenant_id: uuid.UUID) -> None:
        """Take a row lock on the tenant so the count above is trustworthy (design D6).

        `SELECT ... FOR UPDATE` on `tenants`, not on the user rows: the invariant is about the
        POPULATION of owners, and rows that do not exist yet (or that another transaction is
        about to change) cannot be locked by selecting the ones that do. Locking the tenant
        serialises every administrative write of that tenant, which at this volume costs
        nothing.

        A conditional single statement is NOT an alternative here, even though that is the
        idiom `SessionRepository.consume` uses: Postgres re-evaluates a WHERE only for the row
        it is writing, so an `EXISTS (another active owner)` clause is evaluated against the
        transaction's snapshot and two concurrent demotions of two different owners both pass.
        """
        await self._session.execute(
            select(TenantModel.id).where(TenantModel.id == tenant_id).with_for_update()
        )

    async def touch_last_login(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> None:
        """One column, one statement (R1.2).

        Not a full-entity `save`: copying eight fields back from an entity read earlier
        in the request would revert a `status`, `role` or `password_hash` change
        committed in between — a lost update where a login silently un-suspends an
        account. No writer of `users` exists yet besides the bootstrap, but
        `user-management` introduces exactly those writers.
        """
        result = await self._session.execute(
            update(UserModel)
            .where(UserModel.tenant_id == tenant_id, UserModel.id == user_id)
            .values(last_login_at=now)
        )
        if result.rowcount != 1:
            raise ValueError("Cannot update a user that does not belong to this tenant")


class SqlAlchemyTenantStatusReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_active(self, tenant_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(TenantModel.id).where(
                TenantModel.id == tenant_id, TenantModel.status == TenantStatus.ACTIVE
            )
        )
        return result.scalar_one_or_none() is not None


class SqlAlchemySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, user_session: UserSession) -> None:
        if user_session.tenant_id != tenant_id:
            raise ValueError("Cannot create a session for another tenant")
        self._session.add(
            UserSessionModel(
                id=user_session.id,
                tenant_id=user_session.tenant_id,
                user_id=user_session.user_id,
                family_id=user_session.family_id,
                parent_id=user_session.parent_id,
                expires_at=user_session.expires_at,
                used_at=user_session.used_at,
                revoked_at=user_session.revoked_at,
                revoked_reason=user_session.revoked_reason,
            )
        )

    async def get(self, tenant_id: uuid.UUID, session_id: uuid.UUID) -> UserSession | None:
        result = await self._session.execute(
            select(UserSessionModel).where(
                UserSessionModel.tenant_id == tenant_id, UserSessionModel.id == session_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_session(model) if model is not None else None

    async def consume(self, tenant_id: uuid.UUID, session_id: uuid.UUID, now: datetime) -> bool:
        """Mark a session used, but only if it is still usable (R2.1, R2.2).

        Conditional on purpose. Reading the row and then writing it is a
        read-then-write race: under READ COMMITTED two concurrent presentations of the
        same refresh token both see it usable, both rotate, and the reuse detection of
        R2.2 never fires — the token is honoured twice. Letting the database decide, and
        reporting whether this caller won, closes that window.

        EVERY condition that makes a session unusable belongs in this WHERE, not in the
        caller's in-memory check. `revoked_at IS NULL` matters as much as `used_at`: the
        caller reads the row, then makes another round trip before getting here, and a
        `revoke_family` committed in between (a concurrent logout, or reuse detection
        firing on a sibling) would otherwise lose the tie — `used_at` is still NULL, the
        UPDATE succeeds, and a fresh un-revoked child gets inserted that outlives the
        revocation meant to kill it. Postgres makes that worse, not better: a blocked
        UPDATE re-evaluates the WHERE against the new row version, so the condition has
        to be there to be seen.

        Returns True if this call consumed the session, False otherwise — which the
        caller must treat exactly like a detected reuse.
        """
        result = await self._session.execute(
            update(UserSessionModel)
            .where(
                UserSessionModel.tenant_id == tenant_id,
                UserSessionModel.id == session_id,
                UserSessionModel.used_at.is_(None),
                UserSessionModel.revoked_at.is_(None),
                UserSessionModel.expires_at > now,
            )
            .values(used_at=now)
        )
        return result.rowcount == 1

    async def revoke_family(
        self,
        tenant_id: uuid.UUID,
        family_id: uuid.UUID,
        reason: SessionRevokedReason,
        now: datetime,
    ) -> int:
        """Revoke a whole lineage in one statement (R2.2).

        A used refresh token is treated as evidence of theft, so every sibling and
        descendant goes down with it, not just the one presented.
        """
        result = await self._session.execute(
            update(UserSessionModel)
            .where(
                UserSessionModel.tenant_id == tenant_id,
                UserSessionModel.family_id == family_id,
                UserSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )
        return result.rowcount

    async def revoke_all_for_user(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: SessionRevokedReason,
        now: datetime,
    ) -> int:
        """Every family of one user, in one statement (user-management R3.7, R4.2).

        `tenant_id` is in the WHERE even though `user_id` is globally unique: this write
        is not covered by the session filter of `app/core/db.py` for the tenant it was
        marked with, and a repository able to revoke another tenant's sessions from a
        `user_id` alone is the kind of primitive that gets reused wrongly later.

        `revoked_at IS NULL` keeps it idempotent AND truthful: a session revoked earlier
        by a logout keeps `LOGOUT` instead of being relabelled by an administrative action
        that did not cause it.
        """
        result = await self._session.execute(
            update(UserSessionModel)
            .where(
                UserSessionModel.tenant_id == tenant_id,
                UserSessionModel.user_id == user_id,
                UserSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )
        return result.rowcount


class SqlAlchemyPasswordResetTokenRepository:
    """Recovery links (`auth-account-recovery` R3, design D1/D3/D7).

    Every method is scoped by tenant EXCEPT `consume_globally`, which is one of the system's
    unscoped queries (design D3) — see its docstring on the port for why, and
    `find_by_email_globally` above for the enumeration of all of them, which is the one place
    that count is stated. This docstring said "the second and last" until `guest-portal-api`
    added a third and the architecture panel of that change's merge caught the claim.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, token: PasswordResetToken) -> None:
        if token.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="password_reset_token",
                entity_tenant_id=token.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            PasswordResetTokenModel(
                id=token.id,
                tenant_id=token.tenant_id,
                user_id=token.user_id,
                token_hash=token.token_hash,
                expires_at=token.expires_at,
                used_at=token.used_at,
                revoked_at=token.revoked_at,
                # Persisted from the ENTITY rather than left to the column default, unlike
                # the other tables here — because `revoke_oldest_beyond` orders by it, and
                # `now()` in Postgres is transaction-scoped: two tokens inserted in one
                # transaction would carry the SAME default and "oldest" would fall to the
                # `id` tiebreaker, i.e. become arbitrary. Production creates each in its own
                # request, so the values differ anyway; making the domain's `now` the stored
                # value is what makes the ordering deterministic and testable instead of a
                # property of transaction timing.
                created_at=token.created_at,
            )
        )

    async def consume_globally(
        self, token_hash: str, now: datetime
    ) -> PasswordResetToken | None:
        """Spend the token in ONE conditional statement (R3.2, design D1).

        Conditional for the same reason `SessionRepository.consume` is: reading the row and
        then writing it is a read-then-write race, and under READ COMMITTED two concurrent
        presentations of the same link would both find it usable and both reset the password.
        Letting the database decide, and reporting which caller won, closes that window.

        EVERY condition that makes a token unspendable is in this WHERE — `used_at`,
        `revoked_at` and `expires_at` alike. `revoked_at` matters as much as `used_at`: a
        concurrent recovery on the same account calls `revoke_other_live`, and without the
        clause this UPDATE would win the tie against a revocation meant to kill it. Postgres
        re-evaluates the WHERE against the new row version when an UPDATE unblocks, so the
        condition has to be there to be seen.

        No `tenant_id` clause, deliberately (design D3): the endpoint is anonymous and the
        unique index on `token_hash` identifies at most one row in the whole installation. The
        tenant comes back OUT of that row.

        `RETURNING` the whole row rather than a bool: the caller is anonymous and cannot know
        whose token it just spent until this tells it.
        """
        result = await self._session.execute(
            update(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.token_hash == token_hash,
                PasswordResetTokenModel.used_at.is_(None),
                PasswordResetTokenModel.revoked_at.is_(None),
                PasswordResetTokenModel.expires_at > now,
            )
            .values(used_at=now)
            .returning(PasswordResetTokenModel)
        )
        model = result.scalar_one_or_none()
        return _to_reset_token(model) if model is not None else None

    async def count_live(self, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> int:
        """The per-account cap of design D7, read off the table rather than a second store."""
        result = await self._session.execute(
            select(func.count())
            .select_from(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.tenant_id == tenant_id,
                PasswordResetTokenModel.user_id == user_id,
                PasswordResetTokenModel.used_at.is_(None),
                PasswordResetTokenModel.revoked_at.is_(None),
                PasswordResetTokenModel.expires_at > now,
            )
        )
        return int(result.scalar_one())

    async def revoke_oldest_beyond(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        keep_newest: int,
        now: datetime,
        older_than: datetime,
    ) -> int:
        """Keep the `keep_newest` most recent live tokens, revoke the rest (R2.5, design D7).

        One statement with a subselect rather than a read followed by writes: the read-then-
        write shape would let two concurrent requests each decide to revoke the same row and
        each emit, leaving the account over its cap.

        `ORDER BY created_at DESC, id DESC` — the tiebreaker matters, because two tokens
        issued inside the same clock tick would otherwise make the window non-deterministic
        and `OFFSET` could keep one and drop the other arbitrarily.
        """
        live = (
            select(PasswordResetTokenModel.id)
            .where(
                PasswordResetTokenModel.tenant_id == tenant_id,
                PasswordResetTokenModel.user_id == user_id,
                PasswordResetTokenModel.used_at.is_(None),
                PasswordResetTokenModel.revoked_at.is_(None),
                PasswordResetTokenModel.expires_at > now,
            )
            .order_by(
                PasswordResetTokenModel.created_at.desc(),
                PasswordResetTokenModel.id.desc(),
            )
            .offset(max(keep_newest, 0))
        )
        result = await self._session.execute(
            update(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.id.in_(live.scalar_subquery()),
                # The grace boundary (R2.5, design D7's grace amendment): a link created after
                # it is never retired, so the one just mailed survives the window in which its
                # owner clicks it. Without this, a sustained attacker retired the owner's link
                # seconds after issuing, and per-account mail volume lost its only bound.
                PasswordResetTokenModel.created_at <= older_than,
            )
            .values(revoked_at=now)
            # `fetch`, not the default `auto`. The other conditional updates here have plain
            # WHEREs that SQLAlchemy can evaluate in Python, so it expires the matched objects
            # by itself; a subquery it cannot evaluate leaves them **stale in the identity
            # map**, so a later read on this session would still show `revoked_at = None`.
            # Production never re-reads them in the same session, but a primitive whose
            # in-session view disagrees with the database is one somebody debugs for an hour.
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount

    async def revoke_other_live(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, keep_id: uuid.UUID, now: datetime
    ) -> int:
        """Invalidate the account's other live links after a completed reset (R3.5b).

        `keep_id` is excluded because that row is `used`, not `revoked`, and overwriting it
        would erase the difference between a link somebody spent and a link this reset killed.
        """
        result = await self._session.execute(
            update(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.tenant_id == tenant_id,
                PasswordResetTokenModel.user_id == user_id,
                PasswordResetTokenModel.id != keep_id,
                PasswordResetTokenModel.used_at.is_(None),
                PasswordResetTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return result.rowcount


def _to_user(model: UserModel) -> User:
    return User(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        email=model.email,
        password_hash=model.password_hash,
        role=model.role,
        created_at=model.created_at,
        updated_at=model.updated_at,
        phone=model.phone,
        status=model.status,
        preferred_language=model.preferred_language,
        last_login_at=model.last_login_at,
        must_change_password=model.must_change_password,
    )


def _to_reset_token(model: PasswordResetTokenModel) -> PasswordResetToken:
    return PasswordResetToken(
        id=model.id,
        tenant_id=model.tenant_id,
        user_id=model.user_id,
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        used_at=model.used_at,
        revoked_at=model.revoked_at,
    )


def _to_session(model: UserSessionModel) -> UserSession:
    return UserSession(
        id=model.id,
        tenant_id=model.tenant_id,
        user_id=model.user_id,
        family_id=model.family_id,
        expires_at=model.expires_at,
        parent_id=model.parent_id,
        used_at=model.used_at,
        revoked_at=model.revoked_at,
        revoked_reason=model.revoked_reason,
    )
