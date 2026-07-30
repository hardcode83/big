"""SQLAlchemy adapters for the auth ports (R4.2, R6.5, design D6/D10).

Every method takes `tenant_id` and filters on it — except
`find_by_email_across_tenants`, the one deliberate exception (design D16), which is
therefore the only unscoped query in the system: every other cross-tenant need goes
through it rather than hand-rolling a second one.
No method commits: the transactional boundary is the use case (design D10).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.entities import User, UserSession
from app.auth.domain.enums import SessionRevokedReason, UserStatus
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.models import UserModel, UserSessionModel
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantModel


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

    async def find_by_email_across_tenants(self, email: str) -> Sequence[User]:
        """THE ONLY unscoped query in the system (design D16).

        Its callers are the anonymous login and the bootstrap conflict check; both go
        through here rather than writing their own, so a grep for this method name
        enumerates every cross-tenant read that exists.

        Login is anonymous, so there is no tenant yet. Matching is
        case-insensitive because an email is not case-sensitive to the person
        typing it; if that makes two users in the same tenant match, the caller
        refuses to authenticate (R1.4) — it fails closed.

        ASSUMPTION: `UniqueConstraint(tenant_id, email)` makes an email unique per
        tenant, not globally, so {email, password} does not identify one user once
        there is more than one tenant. This may therefore return several users, and
        login proceeds only when exactly one matches (design D16). Real multi-tenant
        login will need a discriminator (subdomain, or a tenant field).

        The comparison is a plain equality against the Python-normalised address —
        never `lower()` inside the query — see `normalize_email` and design D19.
        """
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == normalize_email(email))
        )
        return [_to_user(model) for model in result.scalars().all()]

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
