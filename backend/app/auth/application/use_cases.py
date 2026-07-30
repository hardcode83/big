"""Auth use cases: orchestration only, no business rules of their own.

Rules live in the entities (`UserSession.is_usable`, `.rotate`) and in the policy
(`policy.is_allowed`). These classes wire ports together and own the transactional
boundary (design D10) — nothing here imports FastAPI or SQLAlchemy.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.auth.domain.entities import User, UserSession
from app.auth.domain.enums import SessionRevokedReason, UserStatus
from app.auth.domain.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    SessionReuseDetectedError,
    TooManyAttemptsError,
)
from app.auth.domain.ports import (
    LoginThrottle,
    PasswordHasher,
    SessionRepository,
    TenantStatusReader,
    TokenCodec,
    UnitOfWork,
    UserRepository,
)
from app.auth.domain.value_objects import TokenPair

# R5.5: failed attempts and lockouts are recorded in English, never with the
# submitted password.
logger = logging.getLogger("app.auth")


@dataclass
class LoginUseCase:
    users: UserRepository
    tenants: TenantStatusReader
    sessions: SessionRepository
    hasher: PasswordHasher
    tokens: TokenCodec
    throttle: LoginThrottle
    uow: UnitOfWork

    async def execute(self, *, email: str, password: str, client_ip: str, now: datetime) -> TokenPair:
        if not await self.throttle.ip_attempt_allowed(client_ip):
            logger.warning("Login rate limit exceeded for ip=%s", client_ip)
            raise TooManyAttemptsError("Too many login attempts")

        user = await self._authenticate(email, password, client_ip)

        await self.throttle.reset_failures(user.id)
        await self.users.touch_last_login(user.tenant_id, user.id, now)

        pair = await self._start_session(user, now)
        await self.uow.commit()
        return pair

    async def _authenticate(self, email: str, password: str, client_ip: str) -> User:
        candidates = await self.users.find_by_email_across_tenants(email)
        if len(candidates) != 1:
            # Unknown address, or an ambiguity that must not authenticate anybody
            # (design D16). Both answer exactly like a wrong password (R1.4).
            #
            # `burn` is not decoration: bcrypt is the only expensive step on this path,
            # so returning without it answers in ~2 ms where a real address takes as
            # long as the configured cost. That gap is a user-enumeration oracle by
            # latency, which is precisely what R1.4's ASSUMPTION exists to prevent —
            # identical bodies are not enough.
            self.hasher.burn(password)
            logger.warning(
                "Login failed: %s match for the address, ip=%s",
                "no" if not candidates else f"{len(candidates)} candidates",
                client_ip,
            )
            raise InvalidCredentialsError("Invalid email or password")

        user = candidates[0]

        if await self.throttle.is_account_locked(user.id):
            # Deliberately NOT recording a failure here: counting an attempt that was
            # never evaluated would push the lock forward on every try and the
            # 15-minute bound of R5.2 would stop being a bound.
            #
            # Same reason for burning: without it the responses of a locked account go
            # fast again, which tells an attacker exactly when the lock engaged and
            # when it lapsed.
            self.hasher.burn(password)
            logger.warning("Login refused: account locked user_id=%s ip=%s", user.id, client_ip)
            raise InvalidCredentialsError("Invalid email or password")

        if not self.hasher.verify(password, user.password_hash):
            await self._record_failure(user.id, "wrong password", client_ip)
            raise InvalidCredentialsError("Invalid email or password")

        if user.status is not UserStatus.ACTIVE:
            await self._record_failure(user.id, f"user status {user.status.value}", client_ip)
            raise InvalidCredentialsError("Invalid email or password")

        if not await self.tenants.is_active(user.tenant_id):
            await self._record_failure(user.id, "tenant not active", client_ip)
            raise InvalidCredentialsError("Invalid email or password")

        return user

    async def _record_failure(self, user_id: uuid.UUID, reason: str, client_ip: str) -> None:
        logger.warning("Login failed (%s) user_id=%s ip=%s", reason, user_id, client_ip)
        await self.throttle.record_failure(user_id)

    async def _start_session(self, user: User, now: datetime) -> TokenPair:
        family_id = uuid.uuid4()
        session = UserSession(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            user_id=user.id,
            family_id=family_id,
            expires_at=now + self.tokens.refresh_ttl,
        )
        await self.sessions.add(user.tenant_id, session)
        return TokenPair(
            access_token=self.tokens.issue_access(
                user_id=user.id,
                tenant_id=user.tenant_id,
                role=user.role,
                family_id=family_id,
                now=now,
            ),
            refresh_token=self.tokens.issue_refresh(
                user_id=user.id,
                tenant_id=user.tenant_id,
                role=user.role,
                session_id=session.id,
                family_id=family_id,
                now=now,
            ),
            expires_in=self.tokens.access_ttl_seconds,
        )


@dataclass
class RefreshTokenUseCase:
    users: UserRepository
    sessions: SessionRepository
    tokens: TokenCodec
    uow: UnitOfWork

    async def execute(self, *, refresh_token: str, now: datetime) -> TokenPair:
        claims = self.tokens.decode_refresh(refresh_token)

        session = await self.sessions.get(claims.tenant_id, claims.token_id)
        if session is None:
            raise InvalidTokenError("Token is not valid")

        if session.used_at is not None:
            # A used refresh token presented again is treated as evidence of theft,
            # so the whole lineage goes down — including the token the legitimate
            # holder is using right now (R2.2).
            revoked = await self.sessions.revoke_family(
                claims.tenant_id, session.family_id, SessionRevokedReason.REUSE_DETECTED, now
            )
            await self.uow.commit()
            logger.warning(
                "Refresh token reuse detected: revoked %d sessions of family=%s tenant_id=%s",
                revoked,
                session.family_id,
                claims.tenant_id,
            )
            raise SessionReuseDetectedError("Refresh token has already been used")

        if not session.is_usable(now):
            raise InvalidTokenError("Token is not valid")

        # Revalidated against the database, not trusted from the claims (design D7):
        # a user or tenant disabled after the token was issued must not renew.
        user = await self.users.get_active_by_id(claims.tenant_id, claims.user_id)
        if user is None:
            raise InvalidTokenError("Token is not valid")

        # The entity still owns the invariant and builds its replacement...
        child = session.rotate(
            new_id=uuid.uuid4(), expires_at=now + self.tokens.refresh_ttl, now=now
        )
        # ...but the write is conditional, so the database decides who consumed it.
        # Losing this race is indistinguishable from a reuse and is treated as one:
        # somebody else rotated this exact token between our read and our write.
        if not await self.sessions.consume(claims.tenant_id, session.id, now):
            revoked = await self.sessions.revoke_family(
                claims.tenant_id, session.family_id, SessionRevokedReason.REUSE_DETECTED, now
            )
            await self.uow.commit()
            logger.warning(
                "Refresh token consumed concurrently: revoked %d sessions of family=%s",
                revoked,
                session.family_id,
            )
            raise SessionReuseDetectedError("Refresh token has already been used")

        await self.sessions.add(claims.tenant_id, child)

        pair = TokenPair(
            access_token=self.tokens.issue_access(
                user_id=user.id,
                tenant_id=user.tenant_id,
                role=user.role,
                family_id=child.family_id,
                now=now,
            ),
            refresh_token=self.tokens.issue_refresh(
                user_id=user.id,
                tenant_id=user.tenant_id,
                role=user.role,
                session_id=child.id,
                family_id=child.family_id,
                now=now,
            ),
            expires_in=self.tokens.access_ttl_seconds,
        )
        await self.uow.commit()
        return pair


@dataclass
class LogoutUseCase:
    sessions: SessionRepository
    uow: UnitOfWork

    async def execute(self, *, tenant_id: uuid.UUID, family_id: uuid.UUID, now: datetime) -> None:
        """Ends the session the caller is authenticated with (R2.3).

        The family comes from the access token's `fam` claim (design D18). Access
        tokens already issued keep working until they expire — at most 15 minutes —
        because there is no access-token revocation list (R2.4).
        """
        await self.sessions.revoke_family(tenant_id, family_id, SessionRevokedReason.LOGOUT, now)
        await self.uow.commit()


@dataclass
class GetCurrentUserUseCase:
    users: UserRepository

    async def execute(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
        user = await self.users.get_active_by_id(tenant_id, user_id)
        if user is None:
            raise InvalidTokenError("Token is not valid")
        return user
