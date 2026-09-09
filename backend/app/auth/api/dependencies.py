"""Authentication and authorisation dependencies (R3, R4, design D7/D12/D16)."""

import ipaddress
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
from app.auth.api.schemas import SESSION_REFRESH_COOKIE
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
from app.core.i18n import Locale, resolve_locale
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


def resolve_cookie_secure(request: Request) -> bool:
    """Whether the refresh cookie should carry `Secure` (design D2, R7.2, R7.3).

    Decided by the request's EXTERNAL scheme, resolved by `request.url.scheme == "https"`
    alone (design D2).

    **Corrected 2026-09-04** (the run panel's `sdd-security` found this docstring's
    original premise factually wrong against the installed uvicorn 0.51.0 source):
    uvicorn's `ProxyHeadersMiddleware` rewrites **both** `scope["client"]` (from
    `X-Forwarded-For`) **and** `scope["scheme"]` (from `X-Forwarded-Proto`) under the exact
    same `--forwarded-allow-ips` trust gate (`sdd/specs/auth-tenancy.md` §Identificación
    del cliente) — it was wrong to claim the scheme rewrite doesn't happen. So
    `request.url.scheme` is already proxy-aware and trust-gated, the same way
    `get_client_ip` above already trusts `scope["client"]` rather than reading
    `X-Forwarded-For` itself. A second, manual `request.headers.get("x-forwarded-proto")`
    read would be redundant on the trusted path and, worse, ungated on the untrusted one:
    the dev stage pins `--forwarded-allow-ips 127.0.0.1` in `backend/devops/Dockerfile` —
    not its absence — so `docker-compose.yml` can publish `:8000` on every interface and
    still trust nobody but the container's own loopback; a LAN peer reaching the published
    port directly does not present as loopback, so uvicorn never rewrites the scheme for
    it regardless of what header it sends. A raw header read would bypass that gate
    entirely and let any LAN peer force `secure=True` by spoofing it, breaking that
    standing principle for exactly the header `get_client_ip`'s own docstring warns
    against trusting unconditionally. This helper therefore reads `request.url.scheme`
    only.

    `True` in dev over plain HTTP would make the browser silently drop the cookie;
    unconditionally `True` would also break local `make up PORT_OFFSET=<n>`, which is why
    this is a per-request decision and not a setting (rejected at design gate).
    """
    return request.url.scheme == "https"


def is_same_origin_allowed(request: Request) -> bool:
    """Whether this request's `Origin` (if any) is on the CORS allowlist.

    The shared primitive behind `enforce_same_origin` (which raises on `False`) and
    `/auth/logout`'s cookie-fallback check (which folds `False` into "nothing to
    revoke" instead — it can never raise, design D6/D6b). `CORSMiddleware` only gates
    whether the BROWSER may read the response; a cross-origin `POST` with a body
    simple enough to skip preflight still reaches the handler and executes.
    `SameSite` (`Lax` or `Strict`, see `emit_refresh_cookie`) cannot help either: both
    flag the cookie for *cross-site* delivery only, and a sibling origin under the
    same registrable domain (`https://*.digitalsec.work`) is *same-site* by
    definition — the cookie rides along regardless of which value is set. The only
    signal that distinguishes "this frontend" from a same-site sibling is the
    `Origin` the browser reports, checked here against the exact allowlist CORS
    already reflects (`settings.backend_cors_allowed_origin_regex`).

    A request with no `Origin` header at all is treated as allowed: per the Fetch
    standard a browser always attaches one to a `POST`, same-origin or not, and a
    script cannot suppress it (`Origin` is a forbidden header name) — so its absence
    means this call did not originate from a browser's `fetch`/`XHR`/form in the
    first place, and there is nothing here to gate. This is the same non-goal
    `get_client_ip`'s docstring already accepts for a differently-shaped input.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return re.fullmatch(settings.backend_cors_allowed_origin_regex, origin) is not None


def enforce_same_origin(request: Request) -> None:
    """Rejects a same-site-but-cross-origin `POST /auth/refresh` (security panel finding,
    review round 4 of `auth-session-persistence`: CORS and `SameSite` both fail to cover
    this) — see `is_same_origin_allowed` for the shared check this wraps.

    `/auth/logout` does NOT use this dependency: design D6/D6b commits it to never
    answering `401` for an authentication reason, and raising here would break that
    invariant. It calls `is_same_origin_allowed` directly instead, in two places: the
    cookie-fallback branch of `get_logout_subject` folds a mismatch into the existing
    "nothing to revoke" `204`, and the router additionally skips the `Set-Cookie`
    deletion in that case (review round 6 — an earlier version of this fix left the
    deletion unconditional, so a forged-Origin request could not revoke the session
    but could still evict the victim's cookie from their browser).
    """
    if not is_same_origin_allowed(request):
        raise InvalidTokenError("Origin is not allowed to use this credential")


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

    The adapter registry is the shared one: `EMAIL` resolves to `SMTPEmailAdapter` when a
    relay is configured (`smtp-delivery-adapter`), or `ConsoleEmailAdapter` otherwise, in
    which case the notice reaches nobody (R6.4, EXTERNAL_DEPENDENCY). The flow is exercised
    by the suite, where the adapter is a double that captures what was sent.
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

    # `preferred_language` costs no query: the user row was just reloaded above, and
    # discarding it here is what `dashboard-api` design D3 changed. `Locale.resolve`
    # degrades an unsupported stored value to `es` rather than failing the request.
    context = RequestContext(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        preferred_language=Locale.resolve(user.preferred_language),
    )
    # From here on every ORM statement on this session is tenant-filtered (design D16).
    # `SUPER_ADMIN` has no tenant (`super-admin-identity` R2.2, R3.1, design D3): the
    # session is simply never marked, the same state the bootstrap, the anonymous login
    # lookup and `POST /auth/refresh` are already in — `bind_session_to_tenant` itself
    # refuses a `None` tenant_id, so this is the guard that keeps it from ever seeing one.
    if context.tenant_id is not None:
        bind_session_to_tenant(session, context.tenant_id)
    return AuthenticatedRequest(context=context, family_id=claims.family_id)


AuthenticatedDep = Annotated[AuthenticatedRequest, Depends(get_authenticated_request)]


#: The header the interface states its active language in (`frontend-verification-fixes`
#: design D1). A product header and not `Accept-Language` on purpose: the browser sends
#: `Accept-Language` by itself, carrying the *operating system's* preference, and the proxy
#: forwards it untouched — so reusing that name would let a header nobody in our interface
#: wrote decide the language of composed text on any request that does not go through the
#: `ApiClient`. With a name of our own, every value arriving here was put there by our code,
#: and "the language the client asked for" is a checkable claim instead of an inference.
#:
#: The `X-` prefix is discouraged by RFC 6648 and is used deliberately: it marks the header
#: as ours right next to a standard one it could otherwise be confused with.
LOCALE_HEADER = "X-Locale"


async def get_request_locale(request: Request, authenticated: AuthenticatedDep) -> Locale:
    """The locale to render this request's composed text in (design D2, D3; R1.1, R1.5).

    Read off the `Request` object rather than declared as `Annotated[str | None, Header()]`,
    which is what R1.5 asks for: FastAPI publishes header *parameters* in `openapi.json` and
    publishes nothing it cannot see, so the routes that depend on this gain no parameter and
    the generated client does not grow one.

    Costs no query. It depends on `AuthenticatedDep`, which FastAPI resolves once per
    request, so the stored preference it falls back to is the one the revalidation in
    `get_authenticated_request` already read off the user row.

    The effective locale deliberately does NOT enter `RequestContext`: that object documents
    itself as built "never from request input" and is what tenant isolation rests on, so the
    untrusted half of this resolution gets its own carrier instead. `RequestContext.
    preferred_language` stays the stored preference of the row; this is the language the
    answer is painted in. See `app/auth/domain/context.py`.
    """
    return resolve_locale(
        request.headers.get(LOCALE_HEADER), authenticated.context.preferred_language
    )


RequestLocaleDep = Annotated[Locale, Depends(get_request_locale)]


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


@dataclass(frozen=True)
class LogoutSubject:
    """What `/auth/logout` revokes: just enough to call `LogoutUseCase.execute`."""

    tenant_id: uuid.UUID | None
    family_id: uuid.UUID


async def get_logout_subject(
    request: Request,
    session: SessionDep,
    codec: CodecDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> LogoutSubject | None:
    """Resolves who `/auth/logout` should revoke (review: `sdd-security`, R3.1/R6.2).

    A Bearer access token, when presented AND valid, is authenticated exactly as every
    other endpoint does (`get_authenticated_request`) — unchanged behaviour. In every
    other case — no Bearer at all, OR a Bearer that fails to authenticate (expired,
    malformed, an unknown/inactive user or tenant) — this falls back to the refresh
    cookie itself as the credential, the same stance `/auth/refresh` already takes
    ("the token IS the credential"): the family it names is decoded directly from the
    JWT's `fam`/`tenant_id` claims, with no repository round trip, since revocation
    does not need to know whether the session row is still live — `revoke_family` is
    a no-op update either way.

    **A failed Bearer falls through instead of raising — this is the fix for a gap
    the panel found in the first version of this function (added 2026-09-05, same
    day, review round 2 of `get_logout_subject` itself)**: that version only
    fell back when NO Bearer was presented at all. A stale-but-present Bearer (the
    common case: an access token that expired without ever being cleared) still hit
    `get_authenticated_request` and raised — reaching the client's ordinary
    401-recovery, which calls `refreshSession()` before retrying, rotating and
    re-extending the refresh cookie by a fresh week. If THAT retry then failed, the
    browser was left holding a freshly-extended, still-valid session — the exact
    failure mode this dependency exists to close, just reached through a different
    door (a stale Bearer instead of an empty store). Falling through here means a
    stale Bearer alone can never trigger that refresh-before-revoke round trip for
    logout specifically: whatever the Bearer's fate, revocation is attempted straight
    off the cookie.

    Calls `bind_session_to_tenant` in the cookie branch when the decoded `tenant_id`
    is not `None` (added 2026-09-05, review: `sdd-security` — the unmarked-session
    state `steering/security.md` rule 1 names is the SUPER_ADMIN, `tenant_id is None`
    case alone; a cookie naming a real tenant left the session unmarked too, a second,
    undocumented way to reach that state). `revoke_family` already filters on the
    explicit `tenant_id` argument regardless, so this adds a second, defense-in-depth
    layer rather than fixing a reachable cross-tenant path — `LogoutUseCase.execute`
    takes no other statement that could run unscoped today — but it keeps this route
    on the same one mechanism every other tenant-scoped write relies on, so a future
    edit to it inherits the global filter rather than needing its own tenant_id
    argument to get it right.

    Tagged with `MANAGE_OWN_SESSION` for `test_route_authorization.py`'s structural
    walk even though the cookie path checks no role: that permission is in
    `_SELF_SERVICE`, held by every role there is (`policy.py`), so there is no
    identity a valid credential — of either kind — could resolve to that this would
    ever refuse. Authenticating by the cookie alone is therefore equivalent to being
    authorised, unlike every other endpoint `require(...)` guards.

    Returns `None` when there is nothing to revoke — no working Bearer AND (no cookie,
    a cookie whose `Origin` is not on the CORS allowlist, or a cookie that fails to
    decode: expired, tampered, wrong signature) — so the endpoint's existing
    idempotent-204 behaviour (R3.2) covers this case too rather than turning a failed
    credential into a new, distinguishable error surface. The Origin check is the CSRF
    fix from review round 4 (security panel finding): folded in here, inline, rather
    than as a separate `Depends(enforce_same_origin)` like `/auth/refresh` uses, because
    that helper raises on a mismatch and this route must not. `PasswordChangeRequiredError`
    is not caught here: `/auth/logout` is on
    `PASSWORD_CHANGE_EXEMPT`, so `get_authenticated_request` never raises it for this
    route — an unrelated exception type surfacing here would be a genuine bug, not a
    failed-credential case to fall through on.
    """
    if credentials is not None:
        try:
            authenticated = await get_authenticated_request(request, session, codec, credentials)
        except InvalidTokenError:
            authenticated = None
        if authenticated is not None:
            return LogoutSubject(
                tenant_id=authenticated.context.tenant_id, family_id=authenticated.family_id
            )

    token = request.cookies.get(SESSION_REFRESH_COOKIE)
    if token is None:
        return None
    if not is_same_origin_allowed(request):
        # CSRF from a same-site-but-cross-origin sibling (security panel finding, review
        # round 4): `SameSite` cannot distinguish these, and design D6/D6b forbids this
        # route from ever answering 401 for an auth reason, so a bad Origin is folded
        # into "nothing to revoke" rather than raised — see `enforce_same_origin` for the
        # full rationale. The router (`logout()`) makes the same check separately before
        # deleting the cookie (review round 6): this dependency only decides whether to
        # revoke, not whether the response purges the browser's cookie.
        return None
    try:
        claims = codec.decode_refresh(token)
    except InvalidTokenError:
        return None
    if claims.tenant_id is not None:
        bind_session_to_tenant(session, claims.tenant_id)
    return LogoutSubject(tenant_id=claims.tenant_id, family_id=claims.family_id)


setattr(get_logout_subject, REQUIRED_PERMISSION_ATTR, Permission.MANAGE_OWN_SESSION)


def require_any(*permissions: Permission) -> Callable[..., Awaitable[AuthenticatedRequest]]:
    """`require`'s sibling for a route two disjoint roles can both reach (`staff-messaging`
    design D3): authorised when the caller's role holds **any** of `permissions`.

    Exists because `cleaning`'s staff-message thread has no single permission that covers
    both writers — `EXECUTE_CLEANING_TASKS` is the cleaner's alone and `MANAGE_CLEANING_TASKS`
    is the manager's alone (`auth/domain/policy.py`), and R3.1 refuses to add a new permission
    just to name their union.

    **The tag carries a `frozenset`, not a single `Permission`** — the one thing this function
    does differently from `require`. `tests/test_route_authorization.py`'s route walk reads
    `REQUIRED_PERMISSION_ATTR` off the dependency and needs to see every permission a route
    declares, not one arbitrary member of the set; a scalar tag would let the walk observe only
    whichever permission this function happened to check first.
    """

    permission_set = frozenset(permissions)

    async def dependency(authenticated: AuthenticatedDep) -> AuthenticatedRequest:
        if not any(is_allowed(authenticated.context.role, permission) for permission in permission_set):
            raise ForbiddenError("Role is not allowed to perform this action")
        return authenticated

    setattr(dependency, REQUIRED_PERMISSION_ATTR, permission_set)
    return dependency
