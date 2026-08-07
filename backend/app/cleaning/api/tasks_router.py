"""Cleaning task endpoints (PRD §23, R3, R4, R5, R7).

Ten of the twelve routes PRD §23 lists for cleaning. The two missing are
`POST`/`GET /cleaning-tasks/{id}/photos`, which belong to `cleaning-photos-storage`
(proposal §Out of scope) — deliberately absent rather than stubbed, so the OpenAPI contract
never advertises something that answers nothing.

Thin by contract: map Pydantic → use case → Pydantic. Every route declares its permission
with `require(...)`, which `tests/test_route_authorization.py` walks.

**The actor is built here and the row-level rule is derived from it, not from the request**
(design D7): `CleaningActor.restrict_to_cleaner_id` returns the caller's own id when the role
is `CLEANER`, so R7.2 cannot be dropped by omitting a query parameter.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.auth.api.dependencies import AuthenticatedRequest, get_client_ip, now_utc, require
from app.auth.domain.policy import Permission
from app.cleaning.api.dependencies import (
    get_accept_cleaning_task_use_case,
    get_assign_cleaning_task_use_case,
    get_checklist_use_case,
    get_cleaning_task_use_case,
    get_complete_checklist_item_use_case,
    get_complete_cleaning_task_use_case,
    get_create_cleaning_task_use_case,
    get_list_cleaning_tasks_use_case,
    get_reject_cleaning_task_use_case,
    get_start_cleaning_task_use_case,
    get_validate_cleaning_task_use_case,
)
from app.cleaning.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    AssignCleaningTaskRequest,
    ChecklistResponse,
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
    GetCleaningTaskUseCase,
    ListCleaningTasksUseCase,
    RejectCleaningTaskUseCase,
    StartCleaningTaskUseCase,
    ValidateCleaningTaskUseCase,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.core.openapi import AUTHENTICATED_RESPONSES

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
        "a query parameter."
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
        "`CLEANER` in the caller's tenant."
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
        "Applies PRD §11's validation rule: every `required` checklist item completed and no "
        "unresolved `CRITICAL` incident, answered `409` with the missing items enumerated. "
        "The required-photo clause arrives with `cleaning-photos-storage`. The property's next "
        "state is resolved from its bookings, so it becomes `AWAITING_CHECKIN`, "
        "`READY_FOR_NEXT_GUEST` or `VACANT_READY`."
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
