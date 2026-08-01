"""Tenant configuration endpoints (PRD §23, R5, R7).

Two endpoints, one resource. `PROPERTY_MANAGER` reads them because it needs the approval
threshold and the SLAs to operate; only `TENANT_OWNER` writes, which is the "configurar
preferencias del tenant" of PRD §6 (design D8).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.tenants.api.dependencies import (
    get_tenant_settings_use_case,
    get_update_tenant_settings_use_case,
)
from app.tenants.api.schemas import TenantResponse, UpdateTenantRequest
from app.tenants.application.use_cases import (
    GetTenantSettingsUseCase,
    UpdateTenantSettingsUseCase,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_TENANT_SETTINGS))]
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_TENANT_SETTINGS))
]


@router.get(
    "/{tenant_id}",
    response_model=TenantResponse,
    summary="The tenant and its configuration",
    description=(
        "One resource with the configuration nested: PRD §23 defines no endpoint of its own "
        "for it and the relation is 1:1. Any id other than the token's own answers `404`, "
        "indistinguishable from a tenant that does not exist. The configuration row is created "
        "with its defaults if it is missing, so this does not depend on the bootstrap."
    ),
)
async def get_tenant(
    tenant_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetTenantSettingsUseCase, Depends(get_tenant_settings_use_case)],
) -> TenantResponse:
    settings = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        requested_id=tenant_id,
        now=now_utc(),
    )
    return TenantResponse.from_settings(settings)


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
    summary="Update the tenant and its configuration",
    description=(
        "Only the fields present in the body are applied, at either level. Two fields are "
        "deliberately absent and answer `422`: the tenant's `status`, because suspending your "
        "own tenant locks every user out with no way back through the API, and the "
        "configuration's `storage_type`, because switching it points already-uploaded photos "
        "at a backend that does not have them. A body that changes nothing writes nothing."
    ),
)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: UpdateTenantRequest,
    authenticated: ManageDep,
    client_ip: Annotated[str, Depends(get_client_ip)],
    use_case: Annotated[
        UpdateTenantSettingsUseCase, Depends(get_update_tenant_settings_use_case)
    ],
) -> TenantResponse:
    settings = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        requested_id=tenant_id,
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip,
        tenant_changes=body.tenant_changes(),
        config_changes=body.config_changes(),
        now=now_utc(),
    )
    return TenantResponse.from_settings(settings)
