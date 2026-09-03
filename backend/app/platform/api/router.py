"""Platform endpoints (PRD §23 platform surface, R1, R3, R6.1, R6.2, design D5, D6).

Thin by contract: map Pydantic → use case params → Pydantic. Two routes, one router, one
permission (`MANAGE_PLATFORM`). Both reach only `SUPER_ADMIN` today (`app.auth.domain.policy`).

`Cache-Control: no-store` is applied ONLY on the user-creation response (R3.1): the
temporary password is a one-time secret and design D10 forbids any intermediary from
storing it. The tenant-creation response carries no such secret — the tests pin the
absence in `test_post_tenants_does_not_set_cache_control_no_store`.

The `description` strings literally say "Requires SUPER_ADMIN — issues MANAGE_PLATFORM"
because the published OpenAPI is the source of truth for clients; the literal text lets
the frontend team grep for the gate without parsing the route's `require(...)` declaration.

**Parameter order in the endpoint signatures** matters and is part of the contract: the
authorisation dependency is declared BEFORE the body so a non-SUPER_ADMIN token gets a
single `403` reason without ever having its body parsed (R1.4 / 4.14). FastAPI resolves
dependencies before bodies regardless of order in practice, but the declaration order is
what the test pins and what a reviewer reads, and reordering it would invert that.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.auth.api.dependencies import get_client_ip, now_utc
from app.auth.api.users_router import NO_STORE
from app.auth.application.user_admin import CreateUserCommand
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.platform.api.dependencies import PlatformDep
from app.platform.api.schemas import (
    CreatePlatformUserRequest,
    CreateTenantRequest,
    CreatedPlatformUserResponse,
)
from app.platform.api.use_case_dependencies import (
    get_create_tenant_use_case,
    get_create_user_in_tenant_use_case,
)
from app.platform.application.use_cases import (
    CreateTenantCommand,
    CreateTenantUseCase,
    CreateUserInTenantUseCase,
)
from app.tenants.api.schemas import TenantResponse

router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    responses=AUTHENTICATED_RESPONSES,
)

ClientIpDep = Annotated[str, Depends(get_client_ip)]


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant (SUPER_ADMIN only)",
    description="Requires SUPER_ADMIN — issues MANAGE_PLATFORM.",
)
async def create_tenant(
    authenticated: PlatformDep,
    client_ip: ClientIpDep,
    body: CreateTenantRequest,
    use_case: Annotated[
        CreateTenantUseCase, Depends(get_create_tenant_use_case)
    ],
) -> TenantResponse:
    """Create an ACTIVE tenant and its default configuration (R1.1).

    `authenticated` is declared before `body` so a non-SUPER_ADMIN token gets a single
    `403` reason without the body being parsed (R1.4 / 4.14). FastAPI resolves
    dependencies before bodies in practice, but the declaration order is what the test
    pins and what a reviewer reads, and reversing it would invert that.
    """
    settings = await use_case.execute(
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip,
        command=CreateTenantCommand(
            name=body.name,
            billing_email=str(body.billing_email),
            country=body.country,
            timezone=body.timezone,
            default_language=body.default_language,
        ),
        now=now_utc(),
    )
    return TenantResponse.from_settings(settings)


@router.post(
    "/tenants/{tenant_id}/users",
    response_model=CreatedPlatformUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user in a named tenant (SUPER_ADMIN only)",
    description="Requires SUPER_ADMIN — issues MANAGE_PLATFORM.",
)
async def create_user_in_tenant(
    tenant_id: uuid.UUID,
    authenticated: PlatformDep,
    client_ip: ClientIpDep,
    body: CreatePlatformUserRequest,
    use_case: Annotated[
        CreateUserInTenantUseCase, Depends(get_create_user_in_tenant_use_case)
    ],
    response: Response,
) -> CreatedPlatformUserResponse:
    """Create a user in a tenant named by the path (R3.1, R3.4, R3.5).

    `tenant_id` comes from the path, never from the token: the actor is `SUPER_ADMIN`
    (no tenant of its own, design D3). A missing tenant and a `SUSPENDED` tenant both
    raise `TenantNotActiveError`, mapped to `404 NOT_FOUND` by
    `register_platform_error_handlers` (R3.3).

    `preferred_language` is not on the request body (the schema's `extra="forbid"` rejects
    it, design D5): the platform endpoint always uses the tenant's `default_language`. The
    lazy lookup happens inside the wrapper — `CreateUserInTenantUseCase.execute` reads the
    tenant config — so the platform router passes `"es"` as the command's default and lets
    the wrapper apply the tenant's choice. Today the wrapper does not yet read the
    config; the test pins only `user.tenant_id == tenant_a.id`, and the language
    inheritance is the wrapper's next step (not section 4's).
    """
    created = await use_case.execute(
        tenant_id=tenant_id,
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip,
        command=CreateUserCommand(
            name=body.full_name,
            email=str(body.email),
            role=body.role,
            phone=body.phone,
            preferred_language="es",
        ),
        now=now_utc(),
    )
    response.headers.update(NO_STORE)
    return CreatedPlatformUserResponse.build(
        created.user, created.temporary_password
    )


__all__ = ["router"]
