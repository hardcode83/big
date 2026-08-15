"""The owner-approval endpoint (PRD §23, R2; design D14).

One route, and one is the whole surface on purpose. There is deliberately **no listing and
no `READ_OWNER_APPROVALS`**: the dashboard already exposes the pending approvals of a
property (`OwnerApprovalReader.list_pending_for_property`), the notification of R2.3 tells
the owner there is one, and `app/auth/domain/policy.py` declares in its header that the
catalogue carries only the permissions a change actually applies.

Its own module rather than a route on `incidents_router.py` because it acts on the other
aggregate: the id in the path is an approval's, and `owner_approvals` has an identity the
incident cannot stand in for — one incident can raise two of them, D11's budget gate and its
real-cost gate.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.maintenance.api.dependencies import get_respond_owner_approval_use_case
from app.maintenance.api.schemas import IncidentResponse, RespondOwnerApprovalRequest
from app.maintenance.application.use_cases import (
    IncidentActor,
    RespondOwnerApprovalUseCase,
)

router = APIRouter(
    prefix="/owner-approvals", tags=["maintenance"], responses=AUTHENTICATED_RESPONSES
)

RespondDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.RESPOND_OWNER_APPROVALS))
]


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
