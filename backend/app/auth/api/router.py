"""Auth endpoints (PRD §23, R1, R2, R3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    get_client_ip,
    get_current_user_use_case,
    get_login_use_case,
    get_logout_use_case,
    get_refresh_use_case,
    now_utc,
    require,
)
from app.auth.api.schemas import (
    CurrentUserResponse,
    LoginRequest,
    RefreshRequest,
    TokenPairResponse,
)
from app.auth.application.use_cases import (
    GetCurrentUserUseCase,
    LoginUseCase,
    LogoutUseCase,
    RefreshTokenUseCase,
)
from app.auth.domain.policy import Permission

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
    body: RefreshRequest,
    use_case: Annotated[RefreshTokenUseCase, Depends(get_refresh_use_case)],
) -> TokenPairResponse:
    pair = await use_case.execute(refresh_token=body.refresh_token, now=now_utc())
    return TokenPairResponse(**vars(pair))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the session this access token belongs to",
    description=(
        "Revokes the refresh family named by the token. Access tokens already issued "
        "keep working until they expire — at most their configured lifetime."
    ),
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


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="The authenticated user's own profile",
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
