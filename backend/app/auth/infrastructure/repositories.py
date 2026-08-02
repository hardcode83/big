"""SQLAlchemy adapters for the auth ports (R4.2, R6.5, design D6/D10).

Every method takes `tenant_id` and filters on it — except
`find_by_email_globally`, the one deliberate exception (design D16), which is
therefore the only unscoped query in the system: every other cross-tenant need goes
through it rather than hand-rolling a second one.
No method commits: the transactional boundary is the use case (design D10).
"""

import uuid
from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.entities import User, UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import EmailAlreadyExistsError
from app.auth.domain.repositories import UserFilters, UserPage, offset_for
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.models import UserModel, UserSessionModel
from app.core.tenancy import CrossTenantWriteError
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantModel

# The functional unique index of ADR 0005. Named here so the translation to `409` matches THIS
# constraint and re-raises anything else (design D11).
LOWER_EMAIL_CONSTRAINT = "uq_users_lower_email"

# Columns `apply_changes` may write. `email` is included — it is the login identity and can be
# corrected — with the duplicate translation that implies.
WRITABLE_COLUMNS = frozenset(
    {"name", "email", "phone", "preferred_language", "role", "status", "password_hash"}
)

# Named separately from "unknown" so the error says WHY, not just "no".
FORBIDDEN_UPDATE_COLUMNS = frozenset({"tenant_id", "id", "last_login_at", "created_at"})


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
        """THE ONLY unscoped query in the system (design D16).

        Its callers are the anonymous login and the bootstrap conflict check; both go
        through here rather than writing their own, so a grep for this method name
        enumerates every cross-tenant read that exists.

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
