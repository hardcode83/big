"""Auth endpoints (PRD §23, R1, R2, R3)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    LogoutSubject,
    enforce_same_origin,
    get_change_own_password_use_case,
    get_client_ip,
    get_consume_password_reset_use_case,
    get_current_user_use_case,
    get_login_use_case,
    get_logout_subject,
    get_logout_use_case,
    get_refresh_use_case,
    get_request_password_reset_use_case,
    now_utc,
    require,
    resolve_cookie_secure,
)
from app.auth.api.schemas import (
    SESSION_REFRESH_COOKIE,
    ChangePasswordRequest,
    CurrentUserResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    ResetPasswordRequest,
    TokenPairResponse,
    emit_refresh_cookie,
)
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
from app.auth.domain.exceptions import InvalidTokenError
from app.auth.domain.policy import Permission
from app.core.config import settings
from app.core.openapi import AUTHENTICATED_RESPONSES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenPairResponse,
    summary="Exchange email and password for a token pair",
    description=(
        "Anonymous. Rate limited per client IP, and an account is temporarily locked "
        "after too many consecutive failures. Every failure answers the same 401, "
        "whatever the cause."
    ),
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    use_case: Annotated[LoginUseCase, Depends(get_login_use_case)],
) -> TokenPairResponse:
    # `InvalidCredentialsError`/`TooManyAttemptsError` raised inside `execute` propagate
    # past this point, so the cookie below is never set on a failed login (R1.3) — no
    # extra guard needed, `tests/auth/test_api.py` asserts it directly.
    pair = await use_case.execute(
        email=body.email,
        password=body.password,
        client_ip=get_client_ip(request),
        now=now_utc(),
    )
    secure = resolve_cookie_secure(request)
    logger.info(
        "auth.refresh_cookie_issued",
        extra={"secure": secure, "scheme": request.url.scheme, "endpoint": "login"},
    )
    emit_refresh_cookie(
        response,
        pair.refresh_token,
        secure=secure,
        max_age_seconds=settings.jwt_refresh_token_days * 86400,
    )
    return TokenPairResponse(**vars(pair))


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Rotate a refresh token",
    description=(
        "Anonymous: the refresh token itself is the credential. The presented token is "
        "invalidated. Presenting an already-used one revokes the whole session family. "
        "Rejects a cross-origin caller outside the CORS allowlist with the same 401 a "
        "missing/invalid cookie gets (review: sdd-security, CSRF finding) — SameSite "
        "alone does not cover a same-site sibling origin."
    ),
    dependencies=[Depends(enforce_same_origin)],
)
async def refresh(
    request: Request,
    response: Response,
    use_case: Annotated[RefreshTokenUseCase, Depends(get_refresh_use_case)],
) -> TokenPairResponse:
    # R2.3: the refresh token travels exclusively via the `SESSION_REFRESH_COOKIE`
    # cookie — a body carrying `refresh_token` is never read, so it is silently ignored
    # rather than accepted as a fallback.
    token = request.cookies.get(SESSION_REFRESH_COOKIE)
    if token is None:
        # Same 401 `INVALID_TOKEN` envelope a missing/invalid Bearer token gets
        # (`backend/app/auth/api/errors.py`) — no new error path for a missing cookie.
        raise InvalidTokenError("Token is not valid")
    pair = await use_case.execute(
        refresh_token=token,
        # R8 of `api-ingress-routing`: the per-IP budget needs the client, same as login.
        client_ip=get_client_ip(request),
        now=now_utc(),
    )
    secure = resolve_cookie_secure(request)
    logger.info(
        "auth.refresh_cookie_issued",
        extra={"secure": secure, "scheme": request.url.scheme, "endpoint": "refresh"},
    )
    emit_refresh_cookie(
        response,
        pair.refresh_token,
        secure=secure,
        max_age_seconds=settings.jwt_refresh_token_days * 86400,
    )
    return TokenPairResponse(**vars(pair))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the session this access token or refresh cookie belongs to",
    description=(
        "Revokes the refresh family named by a valid access token, or by the refresh "
        "cookie itself when there is no access token, or the one presented does not "
        "authenticate — the cookie is as much a credential here as it already is for "
        "/auth/refresh (review: sdd-security, R3.1/R6.2), so a caller with no valid "
        "access token can still end its own session without minting a new one first. "
        "Never answers 401 for an authentication reason: idempotent, nothing to "
        "revoke answers the same 204 — including a cookie presented by a cross-origin "
        "caller outside the CORS allowlist (CSRF finding), which is treated as nothing "
        "to revoke rather than raised."
    ),
    responses=AUTHENTICATED_RESPONSES,
)
async def logout(
    response: Response,
    subject: Annotated[LogoutSubject | None, Depends(get_logout_subject)],
    use_case: Annotated[LogoutUseCase, Depends(get_logout_use_case)],
) -> Response:
    # Design D6: unconditional on "revoked something", "nothing to revoke" (idempotent,
    # R3.2) AND "no credential to resolve" (R6.2's cookie fallback) — none of these
    # branch the response, so there is nothing to condition it on.
    if subject is not None:
        await use_case.execute(
            tenant_id=subject.tenant_id,
            family_id=subject.family_id,
            now=now_utc(),
        )
    # Mutates and returns the SAME `response` FastAPI injected, rather than
    # constructing a fresh `Response(...)`: when an endpoint returns its own `Response`
    # instance, FastAPI sends that instance as-is and does NOT merge headers set on the
    # injected dependency — a fresh instance here would silently drop the
    # `Set-Cookie` deletion.
    response.delete_cookie(SESSION_REFRESH_COOKIE, path="/api/v1/auth")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for a password recovery link",
    description=(
        "Anonymous. Always answers the same 202 with the same body, whether or not the "
        "address belongs to an account — otherwise it would be a user-enumerator open to "
        "the internet. Shares the per-IP rate limit with login and refresh."
    ),
)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    use_case: Annotated[
        RequestPasswordResetUseCase, Depends(get_request_password_reset_use_case)
    ],
) -> ForgotPasswordResponse:
    await use_case.execute(
        email=body.email,
        # R2.4: the same per-IP budget as login and refresh, so one caller cannot spend two.
        client_ip=get_client_ip(request),
        now=now_utc(),
    )
    # Constructed with no arguments on purpose (R2.1/R2.2): there is no branch above that
    # could vary it, so the response cannot describe what happened.
    return ForgotPasswordResponse()


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password using a recovery token",
    description=(
        "Anonymous: the token from the emailed link is the credential, and it is single "
        "use. Every reason it can fail — unknown, already used, expired, revoked, or an "
        "account that is no longer active — answers the same 401. On success every session "
        "of the account is revoked and any other outstanding recovery link is invalidated; "
        "no session is returned, so log in afterwards. Shares the per-IP rate limit with "
        "login and refresh."
    ),
)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    use_case: Annotated[
        ConsumePasswordResetUseCase, Depends(get_consume_password_reset_use_case)
    ],
) -> Response:
    await use_case.execute(
        token=body.token,
        new_password=body.new_password,
        # R3.7: the same per-IP budget as login, refresh and forgot-password.
        client_ip=get_client_ip(request),
        now=now_utc(),
    )
    # R3.6: no token pair. Possession of a link must not become a session without a
    # credential being presented.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change your own password",
    description=(
        "Self-service, for any role that can authenticate. The subject is the holder of "
        "the access token — the body cannot name another user. On success EVERY refresh "
        "family of the account is revoked, including the one that made this call, so the "
        "caller must log in again: a change that left the old sessions alive would add a "
        "credential rather than rotate one."
    ),
    responses=AUTHENTICATED_RESPONSES,
)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedRequest, Depends(require(Permission.MANAGE_OWN_SESSION))
    ],
    use_case: Annotated[
        ChangeOwnPasswordUseCase, Depends(get_change_own_password_use_case)
    ],
) -> Response:
    await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        user_id=authenticated.context.user_id,
        actor_ip=get_client_ip(request),
        current_password=body.current_password,
        new_password=body.new_password,
        now=now_utc(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="The authenticated user's own profile",
    description=(
        "Returns the identity behind the access token: the user, their role and the "
        "tenant the token is scoped to. Reads nothing from the request beyond the "
        "token, so it never resolves another tenant's data."
    ),
    responses=AUTHENTICATED_RESPONSES,
)
async def me(
    authenticated: Annotated[
        AuthenticatedRequest, Depends(require(Permission.READ_OWN_PROFILE))
    ],
    use_case: Annotated[GetCurrentUserUseCase, Depends(get_current_user_use_case)],
) -> CurrentUserResponse:
    user = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, user_id=authenticated.context.user_id
    )
    return CurrentUserResponse.from_domain(user)
