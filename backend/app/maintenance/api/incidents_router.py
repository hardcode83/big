"""Incident endpoints (PRD §23, R1, R3, R4, R5; design D14).

Thirteen routes, and the fourteenth — `POST /owner-approvals/{id}/respond` — lives in
`approvals_router.py` because it acts on the other aggregate. Twelve until
`tech-cycle-completion` added `POST /{incident_id}/reject`, the operation PRD §6 asks for when
it says the technician "acepta/rechaza" and only `accept` existed. The twelfth is
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

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES, ErrorEnvelope
from app.maintenance.api.dependencies import (
    get_accept_incident_use_case,
    get_assign_incident_use_case,
    get_cancel_incident_use_case,
    get_classify_incident_use_case,
    get_en_route_incident_use_case,
    get_incident_context_use_case,
    get_incident_use_case,
    get_list_incident_photos_use_case,
    get_list_incidents_use_case,
    get_reject_incident_use_case,
    get_resolve_incident_use_case,
    get_resume_work_use_case,
    get_triage_incident_use_case,
    get_upload_incident_photo_use_case,
    get_wait_for_parts_use_case,
)
from app.maintenance.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    AssignIncidentRequest,
    IncidentContextResponse,
    IncidentEtaRequest,
    IncidentPageResponse,
    IncidentPhotoListResponse,
    IncidentPhotoResponse,
    IncidentResponse,
    ResolveIncidentRequest,
    TriageIncidentRequest,
)
from app.maintenance.application.use_cases import (
    AcceptIncidentUseCase,
    ListIncidentPhotosUseCase,
    AssignIncidentUseCase,
    CancelIncidentUseCase,
    ClassifyIncidentUseCase,
    EnRouteIncidentUseCase,
    GetIncidentContextUseCase,
    GetIncidentUseCase,
    IncidentActor,
    ListIncidentsUseCase,
    RejectIncidentUseCase,
    ResolveIncidentUseCase,
    ResumeWorkUseCase,
    TriageIncidentUseCase,
    UploadIncidentPhotoUseCase,
    WaitForPartsUseCase,
)
from app.maintenance.domain.enums import (
    IncidentPhotoStage,
    IncidentSeverity,
    IncidentStatus,
)
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
    description=(
        "Cancels the SLA deadline the assignment opened (R3.3).\n\n"
        "The body is **optional**: `POST` with nothing keeps working exactly as before. When "
        "it carries an `eta_at`, that instant is recorded as when the technician says they "
        "will arrive — it must carry a timezone and must not be in the past, or the answer is "
        "`422`. The ETA belongs to the assignment in force, so a reassignment clears it."
    ),
)
async def accept_incident(
    incident_id: uuid.UUID,
    authenticated: ExecuteDep,
    use_case: Annotated[AcceptIncidentUseCase, Depends(get_accept_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
    payload: IncidentEtaRequest | None = None,
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
        eta_at=payload.eta_at if payload is not None else None,
    )
    return IncidentResponse.from_domain(incident)


@router.post(
    "/{incident_id}/reject",
    response_model=IncidentResponse,
    summary="The technician refuses the job",
    description=(
        "The incident goes back to `CLASSIFIED` for the manager to reassign (R1.1, R1.2) — it "
        "is **not** closed, which is what `cancel` does and what only a manager may do. The "
        "assignee, the ETA and the assignment note are all cleared, because all three belong "
        "to the assignment that just ended; who refused survives in the audit trail and on "
        "the timeline.\n\n"
        "Cancels the SLA deadline the assignment opened — a refusal is an answer, so nobody "
        "is late (R1.3) — and leaves the tenant's `PROPERTY_MANAGER` a notification with no "
        "deadline of its own (R1.4). A tenant with no active manager still gets the refusal "
        "applied (R1.5)."
    ),
)
async def reject_incident(
    incident_id: uuid.UUID,
    authenticated: ExecuteDep,
    use_case: Annotated[RejectIncidentUseCase, Depends(get_reject_incident_use_case)],
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
    "/{incident_id}/en-route",
    response_model=IncidentResponse,
    summary="The technician is on the way",
    description=(
        "`ACCEPTED → IN_PROGRESS`, and the milestone PRD §12 draws as \"Técnico en ruta\" "
        "(R2.1, R2.2). This route was `POST /{incident_id}/start` until "
        "`tech-cycle-completion` renamed it; the old path no longer exists (R2.3).\n\n"
        "The body is **optional** and takes the same `eta_at` as `accept`, under the same "
        "rules: a timezone is required and the past is refused with `422`."
    ),
)
async def en_route_incident(
    incident_id: uuid.UUID,
    authenticated: ExecuteDep,
    use_case: Annotated[EnRouteIncidentUseCase, Depends(get_en_route_incident_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
    payload: IncidentEtaRequest | None = None,
) -> IncidentResponse:
    incident = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
        eta_at=payload.eta_at if payload is not None else None,
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
        "owner decides (R4.3).\n\n"
        "`materials` is optional free text describing what was fitted, bounded to 2000 "
        "characters. It **preserves**: sending the field writes it, omitting it leaves "
        "whatever was there — so the repeat close after an owner approval does not erase what "
        "the first attempt declared. Send no field for \"none\"; an empty string is a `422`. "
        "It explains `final_cost` and is never derived from or validated against it."
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
        materials=payload.materials,
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



#: The photo upload's own status codes, on top of `AUTHENTICATED_RESPONSES`.
#:
#: Written out rather than left to FastAPI's defaults because three of the four are decisions
#: this change made and a reader of the contract has no other way to learn them: which of the
#: `409`s can occur, that the `413` is answered by a middleware and not by the route, and that
#: the `422` covers two unrelated causes.
_PHOTO_UPLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorEnvelope,
        "description": (
            "The incident does not accept a photo, with **three distinguishable messages** "
            "(design D6): it is already `RESOLVED`/`CANCELLED`; it is waiting for the owner "
            "to answer an approval; or it is in a status where the technician's work has not "
            "started. Only `IN_PROGRESS` and `WAITING_EXTERNAL_PARTS` accept one."
        ),
    },
    413: {
        "model": ErrorEnvelope,
        "description": (
            "The body exceeds `PHOTO_UPLOAD_MAX_BYTES` (10 MB by default). Answered by "
            "`MaxBodySizeMiddleware`, which is the layer that refuses before the body is "
            "read. The use case counts again as it consumes the stream, but that bounds the "
            "in-memory copy rather than repeating the refusal — rule 14 of "
            "`sdd/steering/security.md`."
        ),
    },
    422: {
        "model": ErrorEnvelope,
        "description": (
            "Either the bytes are not a JPEG, PNG or WebP, or `stage` is not one of "
            "`BEFORE`/`AFTER`. The second is answered by FastAPI before the use case runs, "
            "and is deliberately **not** a `404`: unlike a cleaning photo's `photo_type`, the "
            "admissible stages come from a closed enum rather than from a row, so there is "
            "nothing whose existence a `404` could describe (design D11)."
        ),
    },
    502: {
        "model": ErrorEnvelope,
        "description": "The file store refused the write; no row was persisted.",
    },
}


@router.post(
    "/{incident_id}/photos",
    response_model=IncidentPhotoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a photo of the incident",
    responses=_PHOTO_UPLOAD_RESPONSES,
    description=(
        "`multipart/form-data` with a `stage` of `BEFORE` or `AFTER` and a `file`. PRD §6 "
        "grants the technician exactly those two — \"subir fotos (antes y despu\u00e9s)\" — and "
        "the enum is closed, so there is no third value and no free-text alternative.\n\n"
        "The format is decided from the file's **bytes** — JPEG, PNG or WebP — and the "
        "`Content-Type` the client sends is never consulted; anything else is a `422`. "
        "Several photos of the same `stage` are allowed on purpose: a technician photographs "
        "two angles of one fault.\n\n"
        "The response carries a **signed URL valid for 3600 s**, and what that URL reveals "
        "depends on the tenant's `storage_type`:\n\n"
        "* `LOCAL` \u2014 the URL is a route of this API "
        "(`/api/v1/incident-photos/{photo_id}`) carrying only the photo's id, its expiry and "
        "a signature. The internal storage path is not in it.\n"
        "* `S3` \u2014 the URL is a **presigned URL minted by the object store itself**, so it "
        "necessarily contains the bucket and the full object key. That is inherent to how "
        "presigned URLs work and is not something this API can strip.\n\n"
        "In neither case does `storage_key` appear as a field of the response body (R3.3)."
    ),
)
async def upload_incident_photo(
    authenticated: ExecuteDep,
    incident_id: uuid.UUID,
    # `Annotated[IncidentPhotoStage, Form()]` is design D11 and it is what makes R2.10 free:
    # FastAPI rejects anything that is not `BEFORE`/`AFTER` with a `422` before this function
    # body runs, so the use case never sees an invalid stage and does not check for one.
    stage: Annotated[IncidentPhotoStage, Form()],
    # The `UploadFile` is handed to the use case unread, which consumes it in chunks counting
    # bytes. Read that as "this handler adds no buffering of its own", NOT as "the body has not
    # been received yet" — by the time this signature binds, it has. Why is rule 14 of
    # `sdd/steering/security.md`, the single home of that contract; do not re-derive it here.
    # The thing that actually stops an oversized upload from being received is
    # `MaxBodySizeMiddleware`.
    file: Annotated[UploadFile, File()],
    use_case: Annotated[
        UploadIncidentPhotoUseCase, Depends(get_upload_incident_photo_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentPhotoResponse:
    """`EXECUTE_INCIDENTS` — the assigned `TECHNICIAN`, and `PROPERTY_MANAGER` to unblock.

    **No new permission** (R2.2): `EXECUTE_INCIDENTS` is what already drives the technician's
    cycle, and `ROLE_PERMISSIONS` is untouched by this change.

    The row-level half is not declared here and cannot be: it is derived inside the use case
    from `IncidentActor.restrict_to_technician_id`, off the **persisted** role in the verified
    token (R2.3). There is no request field — path, query, form or otherwise — through which a
    caller could name a different technician, and `file.filename` reaches neither the storage
    key nor the response.
    """
    uploaded = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        stage=stage,
        upload=file,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentPhotoResponse.from_upload(uploaded)


@router.get(
    "/{incident_id}/photos",
    response_model=IncidentPhotoListResponse,
    summary="List the photos of an incident",
    description=(
        "Oldest first, so `BEFORE` and `AFTER` read in the order the work happened. Each "
        "entry carries a signed URL **minted for this response**; a URL from an earlier "
        "response may already have expired.\n\n"
        "`READ_INCIDENTS`, so a `TENANT_OWNER` can read the evidence as well as the manager "
        "\u2014 reading it is what they do, uploading it is the technician's. A `TECHNICIAN` "
        "sees only the incidents assigned to them, and that restriction is derived from the "
        "token's role with no parameter that can widen it."
    ),
)
async def list_incident_photos(
    authenticated: ReadDep,
    incident_id: uuid.UUID,
    use_case: Annotated[
        ListIncidentPhotosUseCase, Depends(get_list_incident_photos_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> IncidentPhotoListResponse:
    """`READ_INCIDENTS` (R3.2), with the same row-level rule the rest of the module applies."""
    uploaded = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        incident_id=incident_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return IncidentPhotoListResponse.from_uploads(uploaded)
