"""Cleaning task endpoints (PRD §23, R3, R4, R5, R7).

All twelve routes PRD §23 lists for cleaning. The two photo routes —
`POST` and `GET /cleaning-tasks/{id}/photos` — arrive with `cleaning-photos-storage`, which
completes the set; they were deliberately absent rather than stubbed until then, so the
OpenAPI contract never advertised something that answers nothing.

The third route that change adds, `GET /cleaning-photos/{photo_id}`, is **not** here: it is
anonymous and lives in `photos_router.py`, whose module docstring says why.

Thin by contract: map Pydantic → use case → Pydantic. Every route declares its permission
with `require(...)`, which `tests/test_route_authorization.py` walks.

**The actor is built here and the row-level rule is derived from it, not from the request**
(design D7): `CleaningActor.restrict_to_cleaner_id` returns the caller's own id when the role
is `CLEANER`, so R7.2 cannot be dropped by omitting a query parameter.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.cleaning.api.dependencies import (
    get_accept_cleaning_task_use_case,
    get_assign_cleaning_task_use_case,
    get_checklist_use_case,
    get_cleaning_task_context_use_case,
    get_cleaning_task_use_case,
    get_complete_checklist_item_use_case,
    get_complete_cleaning_task_use_case,
    get_create_cleaning_task_use_case,
    get_list_cleaning_photos_use_case,
    get_list_cleaning_tasks_use_case,
    get_reject_cleaning_task_use_case,
    get_start_cleaning_task_use_case,
    get_upload_cleaning_photo_use_case,
    get_validate_cleaning_task_use_case,
)
from app.cleaning.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    MAX_PHOTO_TYPE_LENGTH,
    AssignCleaningTaskRequest,
    ChecklistResponse,
    CleaningPhotoListResponse,
    CleaningPhotoResponse,
    CleaningTaskContextResponse,
    CleaningTaskPageResponse,
    CleaningTaskResponse,
    CreateCleaningTaskRequest,
    ValidateCleaningTaskRequest,
)
from app.cleaning.application.use_cases import (
    AcceptCleaningTaskUseCase,
    AssignCleaningTaskUseCase,
    CleaningActor,
    CompleteChecklistItemUseCase,
    CompleteCleaningTaskUseCase,
    CreateCleaningTaskCommand,
    CreateCleaningTaskUseCase,
    GetChecklistUseCase,
    GetCleaningTaskContextUseCase,
    GetCleaningTaskUseCase,
    ListCleaningPhotosUseCase,
    ListCleaningTasksUseCase,
    RejectCleaningTaskUseCase,
    StartCleaningTaskUseCase,
    UploadCleaningPhotoUseCase,
    ValidateCleaningTaskUseCase,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.core.openapi import AUTHENTICATED_RESPONSES, ErrorEnvelope

router = APIRouter(
    prefix="/cleaning-tasks", tags=["cleaning"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_CLEANING_TASKS))]
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_CLEANING_TASKS))
]
ExecuteDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.EXECUTE_CLEANING_TASKS))
]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> CleaningActor:
    return CleaningActor(
        user_id=authenticated.context.user_id,
        role=authenticated.context.role,
        # `audit_logs.actor_ip` is one of the two things rule 9 keeps that
        # `property_state_transitions` cannot.
        ip=ip or None,
    )


@router.get(
    "",
    response_model=CleaningTaskPageResponse,
    summary="List the tenant's cleaning tasks",
    description=(
        "Paginated with `page`/`per_page` (PRD §23). A `CLEANER` sees only the tasks assigned "
        "to them; that restriction is derived from the token's role and cannot be widened by "
        "a query parameter.\n\n"
        "Each row carries `assignment_blocked_by`: why that task cannot be assigned right now "
        "(`TASK_STATUS` if its own status refuses, `PROPERTY_STATE` if its property does), or "
        "`null` if nothing known is blocking it. **It is a courtesy, not a permission.** It is "
        "computed when the page is read, so it may be stale by the time a client acts on it; "
        "the assignment endpoint checks again and its refusal is the authority. `null` also "
        "covers a property whose state this read could not resolve, so a client must treat it "
        "as \"go ahead and let the server decide\", never as a guarantee."
    ),
)
async def list_cleaning_tasks(
    authenticated: ReadDep,
    use_case: Annotated[ListCleaningTasksUseCase, Depends(get_list_cleaning_tasks_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    status_filter: Annotated[CleaningTaskStatus | None, Query(alias="status")] = None,
) -> CleaningTaskPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor=_actor(authenticated, client_ip),
        property_id=property_id,
        status=status_filter,
        page=page,
        per_page=per_page,
    )
    return CleaningTaskPageResponse.build(result.items, result.total, page, per_page)


@router.post(
    "",
    response_model=CleaningTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a cleaning task by hand",
    description=(
        "The automatic path is `process_checkouts` (PRD §8.3). This one exists for a cleaning "
        "nobody's checkout implied. The checklist template is resolved for the property; a "
        "reservation that already has a live task is refused with `409`."
    ),
)
async def create_cleaning_task(
    authenticated: ManageDep,
    body: CreateCleaningTaskRequest,
    use_case: Annotated[CreateCleaningTaskUseCase, Depends(get_create_cleaning_task_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskResponse:
    task = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        command=CreateCleaningTaskCommand(
            property_id=body.property_id,
            reservation_id=body.reservation_id,
            scheduled_start=body.scheduled_start,
            scheduled_end=body.scheduled_end,
        ),
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningTaskResponse.from_domain(task)


@router.get(
    "/{task_id}",
    response_model=CleaningTaskResponse,
    summary="Read one cleaning task",
    description=(
        "`404` when the task belongs to another tenant, and also when it belongs to another "
        "cleaner and the caller is a `CLEANER` — both are indistinguishable from a task that "
        "does not exist."
    ),
)
async def get_cleaning_task(
    authenticated: ReadDep,
    task_id: uuid.UUID,
    use_case: Annotated[GetCleaningTaskUseCase, Depends(get_cleaning_task_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskResponse:
    task = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
    )
    return CleaningTaskResponse.from_domain(task)


@router.patch(
    "/{task_id}",
    response_model=CleaningTaskResponse,
    summary="Assign or reassign a cleaning task",
    description=(
        "Assignment is the only mutation this accepts: the status moves through the lifecycle "
        "endpoints so `PropertyStateMachine` is never bypassed. The person named must hold "
        "`CLEANER` in the caller's tenant.\n\n"
        "**The first assignment of a task requires its property to be in "
        "`AWAITING_CLEANING`.** Handing a `CREATED` task to a cleaner moves the property to "
        "`CLEANING_SCHEDULED`, and that transition is legal from no other state. A property in "
        "any other state is answered `409` with code `PROPERTY_STATE_CONFLICT` — distinct from "
        "the `409` `CONFLICT` returned when it is the task's own status that refuses, so the "
        "two causes can be told apart without reading the message. Reassigning a task that is "
        "already `ASSIGNED` does not transition the property and does not depend on its state."
    ),
)
async def assign_cleaning_task(
    authenticated: ManageDep,
    task_id: uuid.UUID,
    body: AssignCleaningTaskRequest,
    use_case: Annotated[AssignCleaningTaskUseCase, Depends(get_assign_cleaning_task_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskResponse:
    task = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        cleaner_id=body.assigned_cleaner_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningTaskResponse.from_domain(task)


@router.post(
    "/{task_id}/accept",
    response_model=CleaningTaskResponse,
    summary="Accept an assigned cleaning task",
    description=(
        "Only the assigned cleaner can accept, and only while the task is `ASSIGNED`; "
        "anyone else gets the same `404` an unknown task gives. Accepting stops the SLA "
        "clock in the operational sense — no second notification is written — and does **not** "
        "move the property, which is already `CLEANING_SCHEDULED`."
    ),
)
async def accept_cleaning_task(
    authenticated: ExecuteDep,
    task_id: uuid.UUID,
    use_case: Annotated[AcceptCleaningTaskUseCase, Depends(get_accept_cleaning_task_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskResponse:
    task = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningTaskResponse.from_domain(task)


@router.post(
    "/{task_id}/reject",
    response_model=CleaningTaskResponse,
    summary="Decline an assigned cleaning task",
    description=(
        "The declined task is terminal and keeps its assignee as the record of who declined; "
        "the response is the **replacement** task, created unassigned in the same transaction "
        "so the property is never left in `AWAITING_CLEANING` with nothing pending."
    ),
)
async def reject_cleaning_task(
    authenticated: ExecuteDep,
    task_id: uuid.UUID,
    use_case: Annotated[RejectCleaningTaskUseCase, Depends(get_reject_cleaning_task_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskResponse:
    replacement = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningTaskResponse.from_domain(replacement)


@router.post(
    "/{task_id}/start",
    response_model=CleaningTaskResponse,
    summary="Start a cleaning",
    description=(
        "Only the assigned cleaner, and only after accepting — PRD §11's flow is accept then "
        "start, so starting from `ASSIGNED` is a `409`. Moves the property to "
        "`CLEANING_IN_PROGRESS`, which is also what opens the checklist for writing."
    ),
)
async def start_cleaning_task(
    authenticated: ExecuteDep,
    task_id: uuid.UUID,
    use_case: Annotated[StartCleaningTaskUseCase, Depends(get_start_cleaning_task_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskResponse:
    task = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningTaskResponse.from_domain(task)


@router.post(
    "/{task_id}/complete",
    response_model=CleaningTaskResponse,
    summary="Finish a cleaning",
    description=(
        "Applies PRD §11's validation rule, all three clauses of it: every `required` "
        "checklist item completed, at least one photo uploaded for every `required` "
        "`photo_type` of the template, and no unresolved `CRITICAL` incident. The first two "
        "are answered `409` with what is missing enumerated in the message. A template that "
        "declares no `required` photo closes with none. The property's next state is resolved "
        "from its bookings, so it becomes `AWAITING_CHECKIN`, `READY_FOR_NEXT_GUEST` or "
        "`VACANT_READY`."
    ),
)
async def complete_cleaning_task(
    authenticated: ExecuteDep,
    task_id: uuid.UUID,
    use_case: Annotated[
        CompleteCleaningTaskUseCase, Depends(get_complete_cleaning_task_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskResponse:
    task = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningTaskResponse.from_domain(task)


@router.post(
    "/{task_id}/validate",
    response_model=CleaningTaskResponse,
    summary="Record a manager's verdict on a finished cleaning",
    description=(
        "Not in PRD §23's list, which stops at `complete`: R5.5 asks for the manual "
        "validation of PRD §11 and there is no endpoint for it, so this is the same kind of "
        "gap as the checklist templates. Automatic validation with `MockAIAdapter` belongs to "
        "`messaging-ai`."
    ),
)
async def validate_cleaning_task(
    authenticated: ManageDep,
    task_id: uuid.UUID,
    body: ValidateCleaningTaskRequest,
    use_case: Annotated[
        ValidateCleaningTaskUseCase, Depends(get_validate_cleaning_task_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskResponse:
    task = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        status=body.validation_status,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningTaskResponse.from_domain(task)


@router.get(
    "/{task_id}/checklist",
    response_model=ChecklistResponse,
    summary="Read a cleaning task's checklist",
    description=(
        "Driven by the task's template: an item nobody has touched still appears, and a "
        "completion for an item the template no longer declares does not."
    ),
)
async def get_checklist(
    authenticated: ReadDep,
    task_id: uuid.UUID,
    use_case: Annotated[GetChecklistUseCase, Depends(get_checklist_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> ChecklistResponse:
    views = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
    )
    return ChecklistResponse.build(views)


# The four statuses this route adds on top of the router's 401/403, declared so the published
# contract lists what the handler can actually answer. `app/core/openapi.py` (design D8 of
# `cleaning`) refuses to *invent* per-endpoint catalogues of 404/409/429 — "declaring a
# plausible-but-unverified set would replace today's lie with a different one" — and leaves the
# door open for "an endpoint that wants to declare its own". This one qualifies: each entry
# below is a row of `app/cleaning/api/errors.py::_MAPPING` reached from this handler's own
# raise sites, not a guess about what an upload might plausibly return.
#
#   404 ← `PhotoTypeNotFoundError` / `CleaningTaskNotFoundError`
#   409 ← `InvalidCleaningTransitionError` (task not `IN_PROGRESS`)
#   413 ← `PhotoTooLargeError` from the use case, and the `MaxBodySizeMiddleware` 413 that
#         precedes it — the middleware never reaches this handler but answers on its path, so
#         a client sees it from this operation and the contract has to say so.
#   502 ← `PhotoStorageUnavailableError`
#
# The `422` is not here on purpose: FastAPI injects it automatically for any route with a
# validated body or parameter, and `_point_errors_at_envelope` rewrites it to the envelope.
_PHOTO_UPLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": (
            "The `photo_type` is not declared by the task's template, or the task does not "
            "exist for this caller — another tenant's task and another cleaner's task are "
            "both answered this way, indistinguishably."
        ),
    },
    409: {
        "model": ErrorEnvelope,
        "description": "The task is not `IN_PROGRESS`, so no evidence can be filed against it.",
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
    502: {
        "model": ErrorEnvelope,
        "description": "The file store refused the write; no row was persisted.",
    },
}


@router.post(
    "/{task_id}/photos",
    response_model=CleaningPhotoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a photo of the cleaning",
    responses=_PHOTO_UPLOAD_RESPONSES,
    description=(
        "`multipart/form-data` with a `photo_type` the task's template declares and a `file`. "
        "The format is decided from the file's **bytes** — JPEG, PNG or WebP — and the "
        "`Content-Type` the client sends is never consulted; anything else is a `422`. "
        "Several photos of the same `photo_type` are allowed on purpose. `404` when the "
        "`photo_type` is not in the template, `409` when the task is not `IN_PROGRESS`, `413` "
        "over the configured size ceiling, `502` when the file store refuses the write. "
        "\n\n"
        "The response carries a **signed URL valid for 3600 s**, and what that URL reveals "
        "depends on the tenant's `storage_type`:\n\n"
        "* `LOCAL` — the URL is a route of this API (`/api/v1/cleaning-photos/{photo_id}`) "
        "carrying only the photo's id, its expiry and a signature. The internal storage path "
        "is not in it.\n"
        "* `S3` — the URL is a **presigned URL minted by the object store itself**, so it "
        "necessarily contains the bucket and the full object key. That is inherent to how "
        "presigned URLs work and is not something this API can strip; see "
        "`S3FileStorage.signed_url`.\n\n"
        "In neither case does `storage_key` appear as a field of the response body (R3.2)."
    ),
)
async def upload_cleaning_photo(
    authenticated: ExecuteDep,
    task_id: uuid.UUID,
    photo_type: Annotated[str, Form(min_length=1, max_length=MAX_PHOTO_TYPE_LENGTH)],
    # The `UploadFile` is handed to the use case unread, which consumes it in chunks counting
    # bytes (design D11). Read that as "this handler adds no buffering of its own", NOT as
    # "the body has not been received yet" — by the time this signature binds, it has. Why is
    # rule 14 of `sdd/steering/security.md`, the single home of that contract; do not
    # re-derive it here. The thing that actually stops an oversized upload from being received
    # is `MaxBodySizeMiddleware`. See `_read_within_limit` for what the use case's count covers.
    file: Annotated[UploadFile, File()],
    use_case: Annotated[
        UploadCleaningPhotoUseCase, Depends(get_upload_cleaning_photo_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningPhotoResponse:
    """`EXECUTE_CLEANING_TASKS`, i.e. the `CLEANER`, and only over her own tasks.

    The row-level half is not declared here and cannot be: it is derived inside the use case
    from `CleaningActor.restrict_to_cleaner_id`, off the **persisted** role in the verified
    token (R6.4). There is no request field — path, query, form or otherwise — through which a
    caller could name a different cleaner, and `file.filename` reaches neither the storage key
    nor the response.
    """
    uploaded = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        photo_type=photo_type,
        upload=file,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningPhotoResponse.from_upload(uploaded)


# Same criterion as the photo listing below: a row of `_MAPPING` reached from this handler's own
# raise site, not a guess.
#
#   404 ← `CleaningTaskNotFoundError`, for an unknown task, another tenant's task, another
#         cleaner's task, and a task whose property does not resolve inside the tenant alike.
_CONTEXT_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": (
            "The task does not exist for this caller — an unknown id, another tenant's task "
            "and another cleaner's task are all answered this way, indistinguishably."
        ),
    },
}


@router.get(
    "/{task_id}/context",
    response_model=CleaningTaskContextResponse,
    summary="Where the cleaning is and the window it has to happen in",
    responses=_CONTEXT_RESPONSES,
    description=(
        "The operating context of one cleaning task: the property's name, internal code, postal "
        "address and timezone, plus the two instants that bound the work. It exists so a "
        "`CLEANER` can be told **which flat to go to** without holding `READ_PROPERTIES` or "
        "`READ_RESERVATIONS`.\n\n"
        "A `CLEANER` reaches only the tasks assigned to them; a manager or owner reaches every "
        "task of their tenant. That restriction comes from the token's persisted role and **no "
        "request parameter can widen it**.\n\n"
        "`checkout_at` and `next_checkin_deadline` are resolved **now**, against the current "
        "reservations — they are not the task's `scheduled_start`/`scheduled_end`, which are the "
        "plan the scheduler committed to and what the assignment and the SLA were built on. The "
        "two pairs can legitimately disagree, and are named differently so the difference does "
        "not read as a contradiction.\n\n"
        "Both instants are ISO 8601 with an explicit offset, in the property's timezone. Either "
        "can be `null`, and each `null` means something specific: `checkout_at` is `null` for a "
        "manual task with no outgoing reservation, or when the stay's local bounds cannot be "
        "resolved; `next_checkin_deadline` is `null` when there is **no `CONFIRMED` arrival "
        "within the 14 days following the anchor** — not merely when no arrival exists. A "
        "`PENDING` arrival imposes no deadline."
    ),
)
async def get_cleaning_task_context(
    authenticated: ReadDep,
    task_id: uuid.UUID,
    use_case: Annotated[
        GetCleaningTaskContextUseCase, Depends(get_cleaning_task_context_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskContextResponse:
    """`READ_CLEANING_TASKS`, plus the row-level rule derived inside the use case.

    `ReadDep` and not `ExecuteDep`: a manager and an owner read this too (R3.5). The half that
    keeps a cleaner to her own tasks is not declared here and cannot be — it comes from
    `CleaningActor.restrict_to_cleaner_id`, off the role persisted on the user's row (R3.1).

    `now` is the server's clock, never a request field: it anchors the deadline window when the
    task has no outgoing reservation, so a caller who could set it could shift what the response
    reports.
    """
    context = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningTaskContextResponse.from_domain(context)


# The listing's only added status, on the same criterion as `_PHOTO_UPLOAD_RESPONSES` above:
# a row of `_MAPPING` reached from this handler's own raise site, not a guess.
#
#   404 ← `CleaningTaskNotFoundError` from `_load_task`, for an unknown task, another
#         tenant's task and another cleaner's task alike.
_PHOTO_LISTING_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": (
            "The task does not exist for this caller — an unknown id, another tenant's task "
            "and another cleaner's task are all answered this way, indistinguishably."
        ),
    },
}


@router.get(
    "/{task_id}/photos",
    response_model=CleaningPhotoListResponse,
    summary="List a cleaning task's photos",
    responses=_PHOTO_LISTING_RESPONSES,
    description=(
        "Every photo uploaded for the task, oldest first, each with a **signed URL valid for "
        "3600 s** minted for this response. A `CLEANER` reaches only the tasks assigned to "
        "them; a manager or owner reaches every task of their tenant. That restriction comes "
        "from the token's persisted role and no request field can widen it.\n\n"
        "`storage_key` is not a field of this response and never will be (R3.2): what the URL "
        "reveals depends on the tenant's `storage_type`, exactly as documented on the upload."
    ),
)
async def list_cleaning_photos(
    authenticated: ReadDep,
    task_id: uuid.UUID,
    use_case: Annotated[ListCleaningPhotosUseCase, Depends(get_list_cleaning_photos_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningPhotoListResponse:
    """`READ_CLEANING_TASKS`, plus the row-level rule derived inside the use case.

    `ReadDep` and not `ExecuteDep`: reading the evidence is what a manager and an owner do
    (R3.1), while uploading it is the cleaner's alone. The half that keeps a cleaner to her own
    tasks is not declared here and cannot be — it comes from
    `CleaningActor.restrict_to_cleaner_id` off the persisted role (R6.4).
    """
    photos = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return CleaningPhotoListResponse.build(photos)


@router.post(
    "/{task_id}/checklist/{item_id}/complete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Tick one checklist item",
    description=(
        "Idempotent: ticking twice is not an error. `404` when the item does not belong to "
        "the task's template, `409` when the task is not in progress."
    ),
)
async def complete_checklist_item(
    authenticated: ExecuteDep,
    task_id: uuid.UUID,
    item_id: str,
    use_case: Annotated[
        CompleteChecklistItemUseCase, Depends(get_complete_checklist_item_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> Response:
    await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        item_id=item_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
