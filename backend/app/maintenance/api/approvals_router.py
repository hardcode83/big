"""The owner-approval endpoints (PRD §23, R2; design D14; `approvals-web` D1, R1).

`GET ""` lists the tenant's approvals (`approvals-web` R1), guarded by
`Permission.READ_OWNER_APPROVALS` — the owner and the manager, never the technician or the
cleaner (R1.4). `POST /{id}/respond` is the owner's alone, under
`Permission.RESPOND_OWNER_APPROVALS`.

Its own module rather than a route on `incidents_router.py` because it acts on the other
aggregate: the id in the path is an approval's, and `owner_approvals` has an identity the
incident cannot stand in for — one incident can raise two of them, D11's budget gate and its
real-cost gate.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.maintenance.api.dependencies import (
    get_list_owner_approvals_use_case,
    get_respond_owner_approval_use_case,
)
from app.maintenance.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    IncidentResponse,
    OwnerApprovalPageResponse,
    RespondOwnerApprovalRequest,
)
from app.maintenance.application.use_cases import (
    IncidentActor,
    ListOwnerApprovalsUseCase,
    RespondOwnerApprovalUseCase,
)
from app.maintenance.domain.enums import OwnerApprovalStatus
from app.maintenance.domain.repositories import OwnerApprovalFilters

router = APIRouter(
    prefix="/owner-approvals", tags=["maintenance"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_OWNER_APPROVALS))]
RespondDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.RESPOND_OWNER_APPROVALS))
]


@router.get(
    "",
    response_model=OwnerApprovalPageResponse,
    summary="List the tenant's owner approvals",
    description=(
        "Paginated with `page`/`per_page` (PRD §23), tenant-scoped from the token alone "
        "(R1.1). Omitting `status` returns only `PENDING` rows, oldest request first — the "
        "to-do-list default (R1.2); an answered status (`APPROVED`/`REJECTED`) returns "
        "newest-answered-first. `TENANT_OWNER` and `PROPERTY_MANAGER` only (R1.4) — a "
        "`TECHNICIAN` or `CLEANER` gets the same `403` `require()` gives for any permission "
        "they lack, with no hint of whether any approval exists (R1.5)."
    ),
)
async def list_owner_approvals(
    authenticated: ReadDep,
    use_case: Annotated[
        ListOwnerApprovalsUseCase, Depends(get_list_owner_approvals_use_case)
    ],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    status_filter: Annotated[OwnerApprovalStatus | None, Query(alias="status")] = None,
) -> OwnerApprovalPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        filters=OwnerApprovalFilters(status=status_filter),
        page=page,
        per_page=per_page,
    )
    return OwnerApprovalPageResponse.from_domain(result, page=page, per_page=per_page)


@router.post(
    "/{approval_id}/respond",
    response_model=IncidentResponse,
    summary="The owner answers a pending approval",
    description=(
        "`TENANT_OWNER` only (R2.6), once only, and only within their own tenant. An "
        "`APPROVED` answer returns the incident to where the approval's `related_type` says "
        "it belongs — `CLASSIFIED` for a budget, `IN_PROGRESS` for a real cost — and a "
        "`REJECTED` one cancels it and recomposes the property's operational state (R2.5).\n\n"
        "Returns the **incident**, not the approval: what the caller does next depends on "
        "where the incident ended up."
    ),
)
async def respond_owner_approval(
    approval_id: uuid.UUID,
    payload: RespondOwnerApprovalRequest,
    authenticated: RespondDep,
    use_case: Annotated[
        RespondOwnerApprovalUseCase, Depends(get_respond_owner_approval_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        approval_id=approval_id,
        status=payload.status,
        response_notes=payload.response_notes,
        actor=IncidentActor(
            user_id=authenticated.context.user_id,
            role=authenticated.context.role,
            ip=client_ip or None,
        ),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)
