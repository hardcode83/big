"""Incident endpoints (PRD §23, R1, R3, R4, R5; design D14).

Twelve routes, and the thirteenth — `POST /owner-approvals/{id}/respond` — lives in
`approvals_router.py` because it acts on the other aggregate. The twelfth is
`GET /{incident_id}/context`, the read-only projection `tech-incident-context` adds so a
technician can be told which flat to go to and how to get in without holding
`READ_PROPERTIES`.

D14's table listed ten here and `cancel` was not among them; the architecture panel of
sections 7-8 caught that. Its absence was a gap rather than a decision — task 6.11 mandates
`CancelIncidentUseCase`, `Incident._TRANSITIONS` declares `cancel` from every non-terminal
status, and R4.4 counts on it — so the route was added to D14 rather than removed here.

**There is deliberately no `POST /incidents`**, and the absence is the most visible thing
about this table, so it is stated rather than left to be noticed: the proposal asks for a
listing and a detail (R5.1), and every source that creates an incident has a declared owner
— the guest portal already creates them, `messaging-ai` will bring the conversational
intent, and `IncidentSource.LOCK_ALERT` is out of scope for want of an import surface.

Thin by contract: map Pydantic → use case → Pydantic. Every route declares its permission
with `require(...)`, which `tests/test_route_authorization.py` walks.

**The actor is built here and the row-level rule is derived from it, not from the request**
(D13): `IncidentActor.restrict_to_technician_id` returns the caller's own id when the role
is `TECHNICIAN`, so R5.3 cannot be dropped by omitting a query parameter — there is no query
parameter for it at all.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES, ErrorEnvelope
from app.maintenance.api.dependencies import (
    get_accept_incident_use_case,
    get_assign_incident_use_case,
    get_cancel_incident_use_case,
    get_classify_incident_use_case,
    get_incident_context_use_case,
    get_incident_use_case,
    get_list_incidents_use_case,
    get_resolve_incident_use_case,
    get_resume_work_use_case,
    get_start_incident_use_case,
    get_triage_incident_use_case,
    get_wait_for_parts_use_case,
)
from app.maintenance.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    AssignIncidentRequest,
    IncidentContextResponse,
    IncidentPageResponse,
    IncidentResponse,
    ResolveIncidentRequest,
    TriageIncidentRequest,
)
from app.maintenance.application.use_cases import (
    AcceptIncidentUseCase,
    AssignIncidentUseCase,
    CancelIncidentUseCase,
    ClassifyIncidentUseCase,
    GetIncidentContextUseCase,
    GetIncidentUseCase,
    IncidentActor,
    ListIncidentsUseCase,
    ResolveIncidentUseCase,
    ResumeWorkUseCase,
    StartIncidentUseCase,
    TriageIncidentUseCase,
    WaitForPartsUseCase,
)
from app.maintenance.domain.enums import IncidentSeverity, IncidentStatus
from app.maintenance.domain.repositories import IncidentFilters

router = APIRouter(
    prefix="/incidents", tags=["maintenance"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_INCIDENTS))]
ManageDep = Annotated[AuthenticatedRequest, Depends(require(Permission.MANAGE_INCIDENTS))]
ExecuteDep = Annotated[AuthenticatedRequest, Depends(require(Permission.EXECUTE_INCIDENTS))]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> IncidentActor:
    return IncidentActor(
        user_id=authenticated.context.user_id,
        role=authenticated.context.role,
        # `audit_logs.actor_ip` is one of the two things rule 9 keeps that
        # `property_state_transitions` cannot.
        ip=ip or None,
    )


@router.get(
    "",
    response_model=IncidentPageResponse,
    summary="List the tenant's incidents",
    description=(
        "Paginated with `page`/`per_page` (PRD §23). A `TECHNICIAN` sees only the incidents "
        "assigned to them; that restriction is derived from the token's role and there is no "
        "parameter that can widen it."
    ),
)
async def list_incidents(
    authenticated: ReadDep,
    use_case: Annotated[ListIncidentsUseCase, Depends(get_list_incidents_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    severity: IncidentSeverity | None = None,
) -> IncidentPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor=_actor(authenticated, client_ip),
        filters=IncidentFilters(
            property_id=property_id, status=status_filter, severity=severity
        ),
        page=page,
        per_page=per_page,
    )
    return IncidentPageResponse.from_domain(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    summary="Read one incident",
    description=(
        "A `TECHNICIAN` who is not the assignee receives the same `404` as for an incident "
        "that does not exist, and so does an incident of another tenant (R5.3, R5.4)."
    ),
)
async def get_incident(
    incident_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetIncidentUseCase, Depends(get_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
    )
    return IncidentResponse.from_domain(incident)


# The projection's only added status, on the same criterion `cleaning`'s `_CONTEXT_RESPONSES`
# uses: a row of `_MAPPING` reached from this handler's own raise site, not a guess.
#
#   404 ← `IncidentNotFoundError`, for an unknown incident, another tenant's incident, an
#         incident assigned to a different technician, and an incident whose property does not
#         resolve inside the tenant alike.
_INCIDENT_CONTEXT_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": (
            "The incident does not exist for this caller — an unknown id, another tenant's "
            "incident, an incident assigned to a different technician and an incident whose "
            "property does not resolve inside the tenant are all answered this way, "
            "indistinguishably."
        ),
    },
}


@router.get(
    "/{incident_id}/context",
    response_model=IncidentContextResponse,
    summary="Which flat the incident is in, and how to get into it",
    responses=_INCIDENT_CONTEXT_RESPONSES,
    description=(
        "The operating context of one incident: the property's name, internal code, postal "
        "address, timezone and access instructions, plus the note the manager left with the "
        "assignment. It exists so a `TECHNICIAN` can be told **which flat to go to and how to "
        "get in** without holding `READ_PROPERTIES`.\n\n"
        "A `TECHNICIAN` reaches only the incidents assigned to them; a manager or owner reaches "
        "every incident of their tenant. That restriction comes from the token's **persisted "
        "role** and **no request parameter can widen it** — there is no parameter for it at "
        "all.\n\n"
        "`property_name`, `property_internal_code`, `country` and `timezone` are always "
        "present. The other seven — `address_line1`, `address_line2`, `city`, `province`, "
        "`postal_code`, `access_notes` and `assignment_note` — can be `null`, and a `null` "
        "there means the column is not filled in, **not** that a value could not be resolved: "
        "a property that does not resolve inside the tenant is a `404`, never a partial "
        "answer.\n\n"
        "`assignment_note` is the note of the **assignment in force**. Every assignment writes "
        "it, so reassigning the incident without a note clears whatever the previous assignment "
        "carried.\n\n"
        "What this route never carries: the WiFi password in any form, the property's cleaning "
        "or emergency notes, and any field of a reservation."
    ),
)
async def get_incident_context(
    incident_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[
        GetIncidentContextUseCase, Depends(get_incident_context_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentContextResponse:
    """`READ_INCIDENTS`, plus the row-level rule derived inside the use case.

    `ReadDep` and not `ExecuteDep`: a manager and an owner read this too (R4.3). No new
    permission is created — this route is reachable by exactly the roles that already hold
    `READ_INCIDENTS`, over exactly the rows they already reach. The half that keeps a technician
    to their own incidents is not declared here and cannot be: it comes from
    `IncidentActor.restrict_to_technician_id`, off the role persisted on the user's row (R4.2).
    """
    context = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
    )
    return IncidentContextResponse.from_domain(context)


@router.post(
    "/{incident_id}/classify",
    response_model=IncidentResponse,
    summary="Force the classifier over one incident",
    description=(
        "The manual door of design D2: the job classifies on its own cadence, and this is "
        "how a manager asks for it now. Below the tenant's confidence threshold the incident "
        "stays `OPEN` for human triage (R1.3)."
    ),
)
async def classify_incident(
    incident_id: uuid.UUID,
    authenticated: ManageDep,
    use_case: Annotated[ClassifyIncidentUseCase, Depends(get_classify_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)


@router.patch(
    "/{incident_id}",
    response_model=IncidentResponse,
    summary="Triage an incident",
    description=(
        "Correct the category or the severity, and put a price on the job (R1.4). An "
        "`estimated_cost` above the tenant's threshold opens the owner-approval gate and "
        "moves the incident to `AWAITING_OWNER_APPROVAL` (R2.1)."
    ),
)
async def triage_incident(
    incident_id: uuid.UUID,
    payload: TriageIncidentRequest,
    authenticated: ManageDep,
    use_case: Annotated[TriageIncidentUseCase, Depends(get_triage_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
        category=payload.category,
        severity=payload.severity,
        estimated_cost=payload.estimated_cost,
    )
    return IncidentResponse.from_domain(incident)


@router.post(
    "/{incident_id}/assign",
    response_model=IncidentResponse,
    summary="Assign or reassign a technician",
    description=(
        "`POST` and not `PATCH`, because this opens an SLA deadline and notifies somebody — "
        "it is an operation, not an edit of a field (D14). Reassigning cancels the previous "
        "assignee's deadline (R3.5).\n\n"
        "`assignment_note` is optional free text the manager leaves for the technician, and "
        "belongs to the assignment **in force**: every call writes it, so reassigning without "
        "one clears whatever the previous assignment carried. It is returned by "
        "`GET /incidents/{incident_id}/context` and by no other route."
    ),
)
async def assign_incident(
    incident_id: uuid.UUID,
    payload: AssignIncidentRequest,
    authenticated: ManageDep,
    use_case: Annotated[AssignIncidentUseCase, Depends(get_assign_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        technician_id=payload.technician_id,
        assignment_note=payload.assignment_note,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)


@router.post(
    "/{incident_id}/accept",
    response_model=IncidentResponse,
    summary="The technician takes the job",
    description="Cancels the SLA deadline the assignment opened (R3.3).",
)
async def accept_incident(
    incident_id: uuid.UUID,
    authenticated: ExecuteDep,
    use_case: Annotated[AcceptIncidentUseCase, Depends(get_accept_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)


@router.post(
    "/{incident_id}/start",
    response_model=IncidentResponse,
    summary="The technician starts work",
)
async def start_incident(
    incident_id: uuid.UUID,
    authenticated: ExecuteDep,
    use_case: Annotated[StartIncidentUseCase, Depends(get_start_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)


@router.post(
    "/{incident_id}/wait-parts",
    response_model=IncidentResponse,
    summary="The job is waiting for an external part",
    description=(
        "The incident stays **open** — `WAITING_EXTERNAL_PARTS` counts as open, because the "
        "flat still has a broken thing in it."
    ),
)
async def wait_for_parts(
    incident_id: uuid.UUID,
    authenticated: ExecuteDep,
    use_case: Annotated[WaitForPartsUseCase, Depends(get_wait_for_parts_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)


@router.post(
    "/{incident_id}/resume",
    response_model=IncidentResponse,
    summary="Work resumes after the part arrived",
)
async def resume_work(
    incident_id: uuid.UUID,
    authenticated: ExecuteDep,
    use_case: Annotated[ResumeWorkUseCase, Depends(get_resume_work_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)


@router.post(
    "/{incident_id}/resolve",
    response_model=IncidentResponse,
    summary="Close the incident with its real cost",
    description=(
        "`final_cost` is required (R4.2). If it goes past the tenant's threshold and no "
        "approved budget covers it, the incident is **not** resolved: it moves to "
        "`AWAITING_OWNER_APPROVAL` with the cost recorded and no `resolved_at`, and the "
        "owner decides (R4.3)."
    ),
)
async def resolve_incident(
    incident_id: uuid.UUID,
    payload: ResolveIncidentRequest,
    authenticated: ExecuteDep,
    use_case: Annotated[ResolveIncidentUseCase, Depends(get_resolve_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        final_cost=payload.final_cost,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)


@router.post(
    "/{incident_id}/cancel",
    response_model=IncidentResponse,
    summary="Cancel an incident",
    description=(
        "Terminal from anywhere that is not already terminal. The property's operational "
        "state is recomposed from what is left (R4.4, R4.6)."
    ),
)
async def cancel_incident(
    incident_id: uuid.UUID,
    authenticated: ManageDep,
    use_case: Annotated[CancelIncidentUseCase, Depends(get_cancel_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentResponse.from_domain(incident)
