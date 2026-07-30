"""Authentication and authorisation dependencies (R3, R4, design D7/D12/D16)."""

import ipaddress
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.application.use_cases import (
    GetCurrentUserUseCase,
    LoginUseCase,
    LogoutUseCase,
    RefreshTokenUseCase,
)
from app.auth.domain.context import RequestContext
from app.auth.domain.exceptions import InvalidTokenError
from app.auth.domain.policy import Permission, is_allowed
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import (
    SqlAlchemySessionRepository,
    SqlAlchemyTenantStatusReader,
    SqlAlchemyUserRepository,
)
from app.auth.infrastructure.throttle import RedisLoginThrottle
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.auth.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from app.core.config import settings
from app.core.db import bind_session_to_tenant, get_db_session
from app.core.errors import ForbiddenError
from app.core.redis import get_redis

# auto_error=False so a missing or non-Bearer header reaches our own handler and comes
# back in the PRD §23 envelope instead of FastAPI's default body.
bearer_scheme = HTTPBearer(auto_error=False)

LOOPBACK = "127.0.0.1"


def now_utc() -> datetime:
    return datetime.now(UTC)


def get_client_ip(request: Request) -> str:
    """The client address used by the per-IP limit (R5.1, design D12).

    The socket peer unless `TRUSTED_CLIENT_IP_HEADER` is configured, which it is not
    by default.

    When it IS configured, the **right-most** hop is taken, and across the last
    occurrence of the header. That is deliberate and was wrong in the first version of
    this function: a proxy that appends (`$proxy_add_x_forwarded_for` in nginx, and any
    conforming implementation) leaves the value the CLIENT sent at the left, so taking
    the first hop reads attacker-controlled input and hands out a fresh 10/min budget
    per request — the exact bypass of R5.1 that design D12 is about. The right-most hop
    is the one the nearest proxy observed, which is also correct for a header that
    replaces rather than appends, such as Cloudflare's `CF-Connecting-IP`.

    What is still missing, and belongs to the change that introduces the proxy
    (`api-ingress-routing`): honouring the header only when the socket peer is a known
    proxy. Until then a directly reachable API could still be fed a whole header — the
    mitigation today is that the setting is empty, so nothing is trusted.
    """
    header_name = settings.trusted_client_ip_header
    if header_name:
        occurrences = request.headers.getlist(header_name)
        if occurrences:
            raw = occurrences[-1].split(",")[-1].strip()
            try:
                return str(ipaddress.ip_address(raw))
            except ValueError:
                pass
    return request.client.host if request.client else LOOPBACK


def get_token_codec() -> JwtTokenCodec:
    return JwtTokenCodec(
        secret=settings.jwt_secret_key,
        access_minutes=settings.jwt_access_token_minutes,
        refresh_days=settings.jwt_refresh_token_days,
    )


def get_password_hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher(rounds=settings.bcrypt_rounds)


def get_login_throttle() -> RedisLoginThrottle:
    return RedisLoginThrottle(
        get_redis(),
        attempts_per_minute=settings.login_rate_limit_per_minute,
        max_failures=settings.login_max_failed_attempts,
        lockout_minutes=settings.login_lockout_minutes,
    )


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
CodecDep = Annotated[JwtTokenCodec, Depends(get_token_codec)]


def get_login_use_case(
    session: SessionDep,
    codec: CodecDep,
    hasher: Annotated[BcryptPasswordHasher, Depends(get_password_hasher)],
    throttle: Annotated[RedisLoginThrottle, Depends(get_login_throttle)],
) -> LoginUseCase:
    return LoginUseCase(
        users=SqlAlchemyUserRepository(session),
        tenants=SqlAlchemyTenantStatusReader(session),
        sessions=SqlAlchemySessionRepository(session),
        hasher=hasher,
        tokens=codec,
        throttle=throttle,
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_refresh_use_case(session: SessionDep, codec: CodecDep) -> RefreshTokenUseCase:
    return RefreshTokenUseCase(
        users=SqlAlchemyUserRepository(session),
        sessions=SqlAlchemySessionRepository(session),
        tokens=codec,
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_logout_use_case(session: SessionDep) -> LogoutUseCase:
    return LogoutUseCase(
        sessions=SqlAlchemySessionRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_current_user_use_case(session: SessionDep) -> GetCurrentUserUseCase:
    return GetCurrentUserUseCase(users=SqlAlchemyUserRepository(session))


class AuthenticatedRequest:
    """What an authenticated endpoint gets: the context plus its token's family."""

    def __init__(self, context: RequestContext, family_id: uuid.UUID) -> None:
        self.context = context
        self.family_id = family_id


async def get_authenticated_request(
    session: SessionDep,
    codec: CodecDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedRequest:
    """Verifies the Bearer token and rebuilds the context from the database (design D7).

    The claims are not taken on trust: the user and its tenant are reloaded and both
    must be ACTIVE, and the effective role is the one stored now — so suspending an
    account or demoting a role takes effect immediately instead of waiting up to 15
    minutes for the access token to expire.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidTokenError("Bearer token required")

    claims = codec.decode_access(credentials.credentials)

    user = await SqlAlchemyUserRepository(session).get_active_by_id(
        claims.tenant_id, claims.user_id
    )
    if user is None:
        # Covers an unknown user, a disabled one, and a tenant that is missing or not
        # ACTIVE (R4.5) — all indistinguishable from an invalid token on purpose.
        #
        # ASSUMPTION (R4.3): the PRD does not say which status code a cross-tenant
        # reference should get; 404 was chosen over 403 so the answer never reveals that
        # a resource exists. Here that principle shows up as a flat 401: this endpoint
        # takes no resource identifier, so R4.3's own 404-vs-403 case has no
        # implementation in this change and is declared unmet in design D15.
        raise InvalidTokenError("Token is not valid")

    context = RequestContext(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    # From here on every ORM statement on this session is tenant-filtered (design D16).
    bind_session_to_tenant(session, context.tenant_id)
    return AuthenticatedRequest(context=context, family_id=claims.family_id)


AuthenticatedDep = Annotated[AuthenticatedRequest, Depends(get_authenticated_request)]


REQUIRED_PERMISSION_ATTR = "__required_permission__"


def require(permission: Permission) -> Callable[..., Awaitable[AuthenticatedRequest]]:
    """Declares the permission an endpoint needs (R3.2, design D8).

    Every non-anonymous route must declare one; `tests/test_route_authorization.py`
    walks the registered routes and fails the suite if one does not.

    The returned callable is TAGGED with the permission it enforces, and that tag is
    what the route walk looks for. Checking merely that the authentication dependency
    is reachable would not be enough: `AuthenticatedDep` is a public export, so an
    endpoint written with it instead of `require(...)` would satisfy such a check while
    consulting no permission at all — and `steering/security.md` rule 2 says "todo
    endpoint nuevo declara su permiso", not "se autentica".
    """

    async def dependency(authenticated: AuthenticatedDep) -> AuthenticatedRequest:
        if not is_allowed(authenticated.context.role, permission):
            raise ForbiddenError("Role is not allowed to perform this action")
        return authenticated

    setattr(dependency, REQUIRED_PERMISSION_ATTR, permission)
    return dependency
