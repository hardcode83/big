"""Authentication and authorisation dependencies (R3, R4, design D7/D12/D16)."""

import ipaddress
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import get_route_path

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.application.recovery import (
    ChangeOwnPasswordUseCase,
    ConsumePasswordResetUseCase,
    RequestPasswordResetUseCase,
)
from app.auth.application.use_cases import (
    GetCurrentUserUseCase,
    LoginUseCase,
    LogoutUseCase,
    RefreshTokenUseCase,
)
from app.auth.domain.context import RequestContext
from app.auth.domain.exceptions import InvalidTokenError, PasswordChangeRequiredError
from app.auth.domain.policy import Permission, is_allowed
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import (
    SqlAlchemyPasswordResetTokenRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyTenantStatusReader,
    SqlAlchemyUserRepository,
)
from app.notifications.infrastructure.adapters import adapter_registry
from app.notifications.infrastructure.repositories import (
    SqlAlchemyNotificationLogRepository,
)
from app.auth.infrastructure.throttle import RedisLoginThrottle
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.config import settings
from app.core.db import bind_session_to_tenant, get_db_session
from app.core.errors import ForbiddenError
# The single SqlAlchemyUnitOfWork of the project. `auth` used to carry its own
# eight-line copy; `user-management` consolidated them (its design D16), which was the
# debt `sdd/specs/reservations.md` assigned to "the next change that touches auth".
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.core.redis import get_redis

# auto_error=False so a missing or non-Bearer header reaches our own handler and comes
# back in the PRD §23 envelope instead of FastAPI's default body.
bearer_scheme = HTTPBearer(auto_error=False)

LOOPBACK = "127.0.0.1"

# The widest address this may return. Ties to `audit_logs.actor_ip`, which is VARCHAR(45)
# and whose factory RAISES past that length rather than truncating — so a value longer
# than this does not produce a wrong audit row, it aborts the transaction of whatever
# audited operation was in flight. Kept as a local constant instead of importing
# `app.audit.domain.services.MAX_ACTOR_IP_LENGTH`, which would couple the auth API layer
# to another domain's internals; `tests/auth/test_client_ip.py` asserts the two agree.
MAX_CLIENT_IP_LENGTH = 45


def now_utc() -> datetime:
    return datetime.now(UTC)


def get_client_ip(request: Request) -> str:
    """The client address used by the per-IP limit (R5.1) and by `AuditLog.actor_ip`.

    Always the socket peer, and that is the whole implementation. Resolving a proxy's
    forwarding header does NOT happen here: uvicorn's `ProxyHeadersMiddleware` does it
    upstream and rewrites `scope["client"]`, but only when the peer is listed in
    `--forwarded-allow-ips`. So by the time this runs the peer already IS the real
    client wherever a trusted proxy fronts the API, and is the raw socket peer
    everywhere else.

    Why it is not done twice (change `api-ingress-routing`, design D3): `proxy_headers`
    defaults to **True** in uvicorn, so a second header reader here would be deciding
    whether to trust a peer that the first one may already have rewritten from
    attacker-controlled input — a check that validates its own input. One mechanism,
    chosen explicitly, is the property that matters; which one it is matters less.

    This is also why the resolution belongs at the ASGI boundary rather than in this
    function: five call sites feed `AuditLog.actor_ip` through it (rule 9 of
    steering/security.md), so a fix here would have been a fix for the throttle only.

    What delegating does NOT buy, measured rather than assumed: uvicorn picks the right
    hop but never checks it is an address. `get_trusted_client_address` returns the
    first entry that is not in the trusted set, so `X-Forwarded-For: not-an-ip` becomes
    `scope["client"][0]` verbatim. That value would land in the throttle key and in
    `audit_logs.actor_ip`, which is `String(45)` with a domain guard that RAISES past
    45 characters — turning a forged header into a failed audited write. So the parse
    stays here, at the boundary where the value enters the application.

    The fallback is `LOOPBACK` and that direction is deliberate. An unparseable value
    can only arrive from a peer uvicorn already trusted (it does not rewrite for
    untrusted ones), so it means our own proxy or a compromised one — and collapsing
    every such request into ONE bucket is fail-closed: they share a single 10/min
    budget instead of each inventing its own. Canonicalising matters for the same
    reason: without it `2001:0db8::1` and `2001:db8::1` are two buckets for one client.

    **Parsing is necessary but not sufficient, and this is the part that bites**: a
    scoped IPv6 address like `fe80::1%eth0` parses, and the zone id after `%` is an
    almost unconstrained string. `ipaddress.ip_address("fe80::1%" + "z" * 100)` is a
    valid address object 108 characters long, and a zone may contain CR or LF. So
    "parses as an IP" alone still let three things through, all measured: a rotating
    zone id gave a fresh throttle bucket per request (defeating rule 7 of
    steering/security.md and growing Redis keys without bound), a CR/LF zone forged
    lines in the login log an operator reads during an incident, and a long one raised
    `AuditContractError` — aborting the transaction of the audited operation in flight.
    A zone identifier is link-local scoping meaningful only on one host, so it can
    never legitimately describe a remote client: it is rejected outright.
    """
    host = request.client.host if request.client else None
    if host is None:
        return LOOPBACK
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return LOOPBACK

    if getattr(address, "scope_id", None) is not None:
        return LOOPBACK

    # `::ffff:1.2.3.4` and `1.2.3.4` are the same client; without this they are two
    # buckets and two distinct `actor_ip` values for one person.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped

    canonical = str(address)
    # Belt and braces over the column bound. Nothing reachable should exceed it once the
    # zone is rejected, which is exactly why a cheap assertion belongs here: the next
    # surprising-but-valid address form must fail closed rather than reach the sinks.
    return canonical if len(canonical) <= MAX_CLIENT_IP_LENGTH else LOOPBACK


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


def get_refresh_use_case(
    session: SessionDep,
    codec: CodecDep,
    throttle: Annotated[RedisLoginThrottle, Depends(get_login_throttle)],
) -> RefreshTokenUseCase:
    return RefreshTokenUseCase(
        users=SqlAlchemyUserRepository(session),
        sessions=SqlAlchemySessionRepository(session),
        tokens=codec,
        # R8 of `api-ingress-routing`: anonymous and internet-reachable, so it gets the
        # same per-IP budget as login. See the use case for why the bucket is shared.
        throttle=throttle,
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_logout_use_case(session: SessionDep) -> LogoutUseCase:
    return LogoutUseCase(
        sessions=SqlAlchemySessionRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_current_user_use_case(session: SessionDep) -> GetCurrentUserUseCase:
    return GetCurrentUserUseCase(users=SqlAlchemyUserRepository(session))


def get_change_own_password_use_case(
    session: SessionDep,
    hasher: Annotated[BcryptPasswordHasher, Depends(get_password_hasher)],
    throttle: Annotated[RedisLoginThrottle, Depends(get_login_throttle)],
) -> ChangeOwnPasswordUseCase:
    """`auth-account-recovery` R1, R1.8.

    The throttle is here for the per-ACCOUNT half only — the failure counter and the lockout
    `login` already owns (design D14). It gets no per-IP budget: the caller is authenticated,
    so `user_id` is both available and a sharper key than the address.

    An earlier version of this factory passed no throttle at all, on the reasoning that an
    authenticated caller is outside the anonymous endpoints' budget. The security panel of
    section 4 showed that was the right observation and the wrong conclusion: this endpoint
    verifies a credential exactly as `login` does, so without the counter it becomes the
    CHEAPER place to guess one — no lockout, no record, no trace — and a wrong-password loop
    holds the bcrypt limiter that `login` shares.
    """
    return ChangeOwnPasswordUseCase(
        users=SqlAlchemyUserRepository(session),
        sessions=SqlAlchemySessionRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        hasher=hasher,
        throttle=throttle,
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_request_password_reset_use_case(
    session: SessionDep,
    throttle: Annotated[RedisLoginThrottle, Depends(get_login_throttle)],
) -> RequestPasswordResetUseCase:
    """`auth-account-recovery` R2. Anonymous, so it takes the per-IP budget (R2.4).

    The adapter registry is the shared one: `EMAIL` resolves to `ConsoleEmailAdapter` today,
    which means the notice reaches nobody until SMTP arrives with `hardening-release`
    (R6.4, EXTERNAL_DEPENDENCY). The flow is exercised by the suite, where the adapter is a
    double that captures what was sent.
    """
    return RequestPasswordResetUseCase(
        users=SqlAlchemyUserRepository(session),
        tokens=SqlAlchemyPasswordResetTokenRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        adapters=adapter_registry(),
        throttle=throttle,
        uow=SqlAlchemyUnitOfWork(session),
        token_minutes=settings.password_reset_token_minutes,
        max_live_tokens=settings.password_reset_max_live_tokens,
        grace_minutes=settings.password_reset_grace_minutes,
        frontend_base_url=settings.frontend_base_url,
    )


def get_consume_password_reset_use_case(
    session: SessionDep,
    hasher: Annotated[BcryptPasswordHasher, Depends(get_password_hasher)],
    throttle: Annotated[RedisLoginThrottle, Depends(get_login_throttle)],
) -> ConsumePasswordResetUseCase:
    """`auth-account-recovery` R3. Anonymous, so it takes the per-IP budget (R3.7), and the
    throttle again for R3.5(c) — the same object clears the account lock after the commit."""
    return ConsumePasswordResetUseCase(
        users=SqlAlchemyUserRepository(session),
        tokens=SqlAlchemyPasswordResetTokenRepository(session),
        sessions=SqlAlchemySessionRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        hasher=hasher,
        throttle=throttle,
        uow=SqlAlchemyUnitOfWork(session),
    )


class AuthenticatedRequest:
    """What an authenticated endpoint gets: the context plus its token's family."""

    def __init__(self, context: RequestContext, family_id: uuid.UUID) -> None:
        self.context = context
        self.family_id = family_id


# The only authenticated routes an account still owing a password change may reach
# (`auth-account-recovery` R5.4, design D6). Pairs of (method, path), NOT bare paths: a
# `GET` would otherwise inherit the exemption of a `POST` of the same name, which is the
# same reasoning `tests/test_route_authorization.py` applies to its anonymous list.
#
# Each entry is here because without it the account would be trapped:
#   - `POST /auth/change-password` is the way OUT of the state. Losing this one turns the
#     flag into a permanent lockout with no endpoint back.
#   - `GET /auth/me` is how the frontend learns to redirect there (R5.6).
#   - `POST /auth/logout` is how somebody who cannot change it right now walks away
#     cleanly instead of leaving a live session behind.
#
# `POST /auth/refresh` is deliberately ABSENT and still works: it does not depend on this
# function at all, which is what R5.5 requires — a temporary password must still yield a
# usable session, or the account is dead rather than merely fenced.
PASSWORD_CHANGE_EXEMPT: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/auth/change-password"),
    }
)


def password_change_exempt_key(request: Request) -> tuple[str, str]:
    """The `(method, path)` pair the gate matches: the method and the **routed** path.

    `starlette.routing.Route.matches` computes `get_route_path(scope)` and regexes the route
    against it, so using the same function here makes the key by construction the path the
    routing decision was made on. That property is the whole point: both bugs below were the
    key disagreeing with what actually routed.

    Exported so `test_the_exempt_key_uses_the_routed_path` pins this function directly rather
    than re-deriving a path of its own.

    **Two formulas were tried and both are wrong**, each having produced or threatened the
    same failure — an account owing a password change refused on all three of its escape
    routes, i.e. a permanent lockout with no endpoint back:

    - `request.scope["route"].path` returns `/auth/me`, not `/api/v1/auth/me`. This version
      shipped and fenced everything. The reason is not a `Mount`: this FastAPI version
      composes `include_router(prefix=...)` **lazily** through `_IncludedRouter` rather than
      flattening child routes' `.path`, so the object in the scope carries the path as the
      child router declared it, prefix excluded — and it does so at dependency-resolution
      time too, not only in middleware. Diagnosed by the QA panel of section 5.
    - `request.url.path` is `scope["path"]` unstripped, so whenever the server leaves the
      prefix in it — the case an ingress produces — it reads `root_path + routed path` and
      the key becomes `/gw/api/v1/auth/me`, matching nothing. Not universal: some ASGI
      servers strip `root_path` before the app sees it, which is why `get_route_path` carries
      its own `startswith` guard. But the project already routes through an ingress
      (`api-ingress-routing`), so the breaking case was live rather than hypothetical. Found
      by the security panel of section 5.

    `get_route_path` strips `root_path` and returns the app-relative path, which is what
    `PASSWORD_CHANGE_EXEMPT` holds and what stays true wherever the app is mounted.

    **Constraint this imposes on the exempt list**: every entry must be a literal,
    parameterless path, because a route pattern like `/users/{id}` would never equal a
    routed path. All three entries are, and R5.4 names no others;
    `test_no_password_change_exemption_uses_a_path_parameter` enforces it so a future
    parameterised exemption fails loudly instead of silently never matching.

    **Do not trust a test that merely inspects the exempt list.** Two such guards were
    written for this and both were vacuous — the measurements are recorded in
    `test_where_the_exempt_list_is_actually_enforced`. What holds the property is the four
    behavioural tests in `tests/auth/test_recovery_api.py` that fence an account and walk
    each escape route, plus `test_the_exempt_key_uses_the_routed_path`, which is non-vacuous
    only because it constructs a scope carrying both rejected formulas' traps at once.
    """
    return request.method, get_route_path(request.scope)


async def get_authenticated_request(
    request: Request,
    session: SessionDep,
    codec: CodecDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedRequest:
    """Verifies the Bearer token and rebuilds the context from the database (design D7).

    The claims are not taken on trust: the user and its tenant are reloaded and both
    must be ACTIVE, and the effective role is the one stored now — so suspending an
    account or demoting a role takes effect immediately instead of waiting up to 15
    minutes for the access token to expire.

    Also the gate of R5.4 (design D6): this is the single point every authenticated
    request passes through, and it already holds the reloaded `User`, so the
    `must_change_password` check costs no extra query. Putting it in `require(...)`
    instead would miss any future endpoint written with the public `AuthenticatedDep`,
    which is the hole that function's own docstring documents.
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
        # takes no resource identifier, so the 404-vs-403 case cannot arise. R4.3 belongs
        # to `user-management`, the first change with endpoints that take one, where it
        # is a blocking acceptance criterion (design D15).
        raise InvalidTokenError("Token is not valid")

    # R5.4: a temporary password authenticates, but it does not operate.
    if (
        user.must_change_password
        and password_change_exempt_key(request) not in PASSWORD_CHANGE_EXEMPT
    ):
        raise PasswordChangeRequiredError(
            "This account must change its password before performing this action"
        )

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
