"""An incident's staff-to-manager message thread (`staff-messaging` R2, R3, R4, R5).

Its own module, the `photos_router.py`/`incidents_router.py` precedent rather than a
fourteenth and fifteenth route folded into `incidents_router.py`: the thread is a
sub-resource of an incident exactly as photos are, and splitting it out keeps that
router's existing routes from growing two more that belong to a narrower concern.

Thin by contract, same as every sibling router: map Pydantic → use case → Pydantic. **Both
routes are gated by permissions `maintenance`'s `ROLE_PERMISSIONS` already grants** (design
D3) — `READ_INCIDENTS` for the read, and `EXECUTE_INCIDENTS` for the write via plain
`require(...)`. **Unlike `cleaning`'s equivalent router, no `require_any` is needed here**:
`EXECUTE_INCIDENTS` already covers both `TECHNICIAN` and `PROPERTY_MANAGER` (design D3,
confirmed by `IncidentActor.restrict_to_technician_id`'s own docstring — "this is also why
`EXECUTE_INCIDENTS` can belong to two roles"), so there is no `or` to write. No permission is
declared here that `Permission`/`ROLE_PERMISSIONS` did not already have (R3.1).

**The actor is built here and the row-level rule is derived from it, not from the request**,
the same discipline `incidents_router.py`'s module docstring states: `IncidentActor` carries
the caller's persisted role, and `_load_incident_in_scope` inside the use case is what
resolves `restrict_to_technician_id` — a `TECHNICIAN` reaching only the incidents assigned to
them (R2.3). An unknown incident, another tenant's incident and another technician's incident
all answer the same `IncidentNotFoundError`-backed `404`, never a `403` (design D4): this
router does not special-case that error, so it surfaces through the app's ordinary exception
mapping exactly as every sibling route's does.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES, ErrorEnvelope
from app.maintenance.api.dependencies import (
    get_list_incident_messages_use_case,
    get_send_incident_message_use_case,
)
from app.maintenance.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    IncidentMessagePageResponse,
    IncidentMessageResponse,
    SendIncidentMessageRequest,
)
from app.maintenance.application.use_cases import (
    IncidentActor,
    ListIncidentMessagesUseCase,
    SendIncidentMessageUseCase,
)

router = APIRouter(
    prefix="/incidents", tags=["maintenance"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_INCIDENTS))]
ExecuteDep = Annotated[AuthenticatedRequest, Depends(require(Permission.EXECUTE_INCIDENTS))]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> IncidentActor:
    """The `incidents_router.py`/`photos_router.py` shape, redeclared rather than imported:
    each sibling router builds its own so that none of them depends on another router
    module."""
    return IncidentActor(
        user_id=authenticated.context.user_id,
        role=authenticated.context.role,
        ip=ip or None,
    )


_SEND_MESSAGE_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": (
            "The incident does not exist for this caller — an unknown id, another tenant's "
            "incident, and (for a `TECHNICIAN`) another technician's incident are all "
            "answered this way, indistinguishably."
        ),
    },
    422: {
        "model": ErrorEnvelope,
        "description": (
            "The body is not a single non-empty `content` the database can store within "
            "`MAX_INCIDENT_MESSAGE_LENGTH`, or it carries a field this operation does not "
            "accept."
        ),
    },
}


@router.post(
    "/{incident_id}/messages",
    response_model=IncidentMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message on an incident's staff thread",
    responses=_SEND_MESSAGE_RESPONSES,
    description=(
        "Writes one message to the incident's staff-to-manager thread and notifies the "
        "other side: a `TECHNICIAN` sending one notifies every active `PROPERTY_MANAGER` of "
        "the tenant, and a `PROPERTY_MANAGER` sending one notifies the incident's assigned "
        "technician, if any (R4).\n\n"
        "Gated by `EXECUTE_INCIDENTS` alone — no new permission is declared, and no `or` is "
        "needed: `EXECUTE_INCIDENTS` already covers both the technician and the manager "
        "(design D3).\n\n"
        "**Row-level scoping is derived inside the use case, never from a request field.** A "
        "`TECHNICIAN` reaches only the incident assigned to them — the same restriction "
        "`_load_incident_in_scope` already applies to every other incident endpoint — so an "
        "unowned incident and an unknown one are one indistinguishable `404`. A "
        "`PROPERTY_MANAGER` reaches every incident of the tenant."
    ),
)
async def send_incident_message(
    authenticated: ExecuteDep,
    incident_id: uuid.UUID,
    payload: SendIncidentMessageRequest,
    use_case: Annotated[
        SendIncidentMessageUseCase, Depends(get_send_incident_message_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentMessageResponse:
    message = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        content=payload.content,
        now=now_utc(),
    )
    return IncidentMessageResponse.from_domain(message)


@router.get(
    "/{incident_id}/messages",
    response_model=IncidentMessagePageResponse,
    summary="List an incident's staff thread",
    description=(
        "The incident's messages, chronologically ascending, paginated with "
        "`page`/`per_page` (PRD §23). Gated by `READ_INCIDENTS` alone — `TECHNICIAN`, "
        "`PROPERTY_MANAGER` and `TENANT_OWNER` already hold it, so reading needs no `or`.\n\n"
        "**Row-level scoping is derived inside the use case, never from a request field.** A "
        "`TECHNICIAN` reaches only the incident assigned to them; an unowned incident and an "
        "unknown one are one indistinguishable `404`. A `PROPERTY_MANAGER` or `TENANT_OWNER` "
        "reaches every incident of the tenant."
    ),
)
async def list_incident_messages(
    authenticated: ReadDep,
    incident_id: uuid.UUID,
    use_case: Annotated[
        ListIncidentMessagesUseCase, Depends(get_list_incident_messages_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
) -> IncidentMessagePageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        page=page,
        per_page=per_page,
    )
    return IncidentMessagePageResponse.build(result, page_number=page, per_page=per_page)
