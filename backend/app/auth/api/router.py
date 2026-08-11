"""Auth endpoints (PRD §23, R1, R2, R3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    get_change_own_password_use_case,
    get_client_ip,
    get_consume_password_reset_use_case,
    get_current_user_use_case,
    get_login_use_case,
    get_logout_use_case,
    get_refresh_use_case,
    get_request_password_reset_use_case,
    now_utc,
    require,
)
from app.auth.api.schemas import (
    ChangePasswordRequest,
    CurrentUserResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenPairResponse,
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
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES

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
    use_case: Annotated[LoginUseCase, Depends(get_login_use_case)],
) -> TokenPairResponse:
    pair = await use_case.execute(
        email=body.email,
        password=body.password,
        client_ip=get_client_ip(request),
        now=now_utc(),
    )
    return TokenPairResponse(**vars(pair))


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Rotate a refresh token",
    description=(
        "Anonymous: the refresh token itself is the credential. The presented token is "
        "invalidated. Presenting an already-used one revokes the whole session family."
    ),
)
async def refresh(
    request: Request,
    body: RefreshRequest,
    use_case: Annotated[RefreshTokenUseCase, Depends(get_refresh_use_case)],
) -> TokenPairResponse:
    pair = await use_case.execute(
        refresh_token=body.refresh_token,
        # R8 of `api-ingress-routing`: the per-IP budget needs the client, same as login.
        client_ip=get_client_ip(request),
        now=now_utc(),
    )
    return TokenPairResponse(**vars(pair))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the session this access token belongs to",
    description=(
        "Revokes the refresh family named by the token. Access tokens already issued "
        "keep working until they expire — at most their configured lifetime."
    ),
    responses=AUTHENTICATED_RESPONSES,
)
async def logout(
    authenticated: Annotated[
        AuthenticatedRequest, Depends(require(Permission.MANAGE_OWN_SESSION))
    ],
    use_case: Annotated[LogoutUseCase, Depends(get_logout_use_case)],
) -> Response:
    await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        family_id=authenticated.family_id,
        now=now_utc(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
