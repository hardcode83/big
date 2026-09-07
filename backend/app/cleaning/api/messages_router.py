"""A cleaning task's staff-to-manager message thread (`staff-messaging` R1, R3, R4, R5).

Its own module, the `photos_router.py` precedent rather than a third router folded into
`tasks_router.py`: the thread is a sub-resource of a cleaning task exactly as photos are, and
splitting it out keeps `tasks_router.py`'s twelve routes from growing a thirteenth and
fourteenth that belong to a narrower concern.

Thin by contract, same as every sibling router: map Pydantic → use case → Pydantic. **Both
routes are gated by permissions `cleaning`'s `ROLE_PERMISSIONS` already grants** (design D3) —
`READ_CLEANING_TASKS` for the read, and `EXECUTE_CLEANING_TASKS` **or**
`MANAGE_CLEANING_TASKS` for the write, via `require_any(...)`. No permission is declared here
that `Permission`/`ROLE_PERMISSIONS` did not already have (R3.1).

**The actor is built here and the row-level rule is derived from it, not from the request**,
the same discipline `tasks_router.py`'s module docstring states: `CleaningActor` carries the
caller's persisted role, and `_load_task` inside the use case is what resolves
`restrict_to_cleaner_id` — a `CLEANER` reaching only the tasks assigned to her (R1.3). An
unknown task, another tenant's task and another cleaner's task all answer the same
`CleaningTaskNotFoundError`-backed `404`, never a `403` (design D4): this router does not
special-case that error, so it surfaces through the app's ordinary exception mapping exactly as
every sibling route's does.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    get_client_ip,
    now_utc,
    require,
    require_any,
)
from app.auth.domain.policy import Permission
from app.cleaning.api.dependencies import (
    get_list_cleaning_task_messages_use_case,
    get_send_cleaning_task_message_use_case,
)
from app.cleaning.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    CleaningTaskMessagePageResponse,
    CleaningTaskMessageResponse,
    SendCleaningTaskMessageRequest,
)
from app.cleaning.application.use_cases import (
    CleaningActor,
    ListCleaningTaskMessagesUseCase,
    SendCleaningTaskMessageUseCase,
)
from app.core.openapi import AUTHENTICATED_RESPONSES, ErrorEnvelope

router = APIRouter(
    prefix="/cleaning-tasks", tags=["cleaning"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_CLEANING_TASKS))]
SendMessageDep = Annotated[
    AuthenticatedRequest,
    Depends(require_any(Permission.EXECUTE_CLEANING_TASKS, Permission.MANAGE_CLEANING_TASKS)),
]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> CleaningActor:
    """The `tasks_router.py`/`photos_router.py` shape, redeclared rather than imported: each
    sibling router builds its own so that none of them depends on another router module."""
    return CleaningActor(
        user_id=authenticated.context.user_id,
        role=authenticated.context.role,
        ip=ip or None,
    )


_SEND_MESSAGE_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": (
            "The task does not exist for this caller — an unknown id, another tenant's task, "
            "and (for a `CLEANER`) another cleaner's task are all answered this way, "
            "indistinguishably."
        ),
    },
    422: {
        "model": ErrorEnvelope,
        "description": (
            "The body is not a single non-empty `content` the database can store within "
            "`MAX_CLEANING_TASK_MESSAGE_LENGTH`, or it carries a field this operation does not "
            "accept."
        ),
    },
}


@router.post(
    "/{task_id}/messages",
    response_model=CleaningTaskMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message on a cleaning task's staff thread",
    responses=_SEND_MESSAGE_RESPONSES,
    description=(
        "Writes one message to the task's staff-to-manager thread and notifies the other "
        "side: a `CLEANER` sending one notifies every active `PROPERTY_MANAGER` of the "
        "tenant, and a `PROPERTY_MANAGER` sending one notifies the task's assigned cleaner, "
        "if any (R4).\n\n"
        "Gated by `EXECUTE_CLEANING_TASKS` **or** `MANAGE_CLEANING_TASKS` — no new permission "
        "is declared; the two that already exist cover the cleaner and the manager "
        "respectively.\n\n"
        "**Row-level scoping is derived inside the use case, never from a request field.** A "
        "`CLEANER` reaches only the task assigned to her — the same restriction `_load_task` "
        "already applies to every other cleaning-task endpoint — so an unowned task and an "
        "unknown one are one indistinguishable `404`. A `PROPERTY_MANAGER` reaches every task "
        "of the tenant."
    ),
)
async def send_cleaning_task_message(
    authenticated: SendMessageDep,
    task_id: uuid.UUID,
    payload: SendCleaningTaskMessageRequest,
    use_case: Annotated[
        SendCleaningTaskMessageUseCase, Depends(get_send_cleaning_task_message_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> CleaningTaskMessageResponse:
    message = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
        content=payload.content,
        now=now_utc(),
    )
    return CleaningTaskMessageResponse.from_domain(message)


@router.get(
    "/{task_id}/messages",
    response_model=CleaningTaskMessagePageResponse,
    summary="List a cleaning task's staff thread",
    description=(
        "The task's messages, chronologically ascending, paginated with `page`/`per_page` "
        "(PRD §23). Gated by `READ_CLEANING_TASKS` alone — `CLEANER`, `PROPERTY_MANAGER` and "
        "`TENANT_OWNER` already hold it, so reading needs no `or`.\n\n"
        "**Row-level scoping is derived inside the use case, never from a request field.** A "
        "`CLEANER` reaches only the task assigned to her; an unowned task and an unknown one "
        "are one indistinguishable `404`. A `PROPERTY_MANAGER` or `TENANT_OWNER` reaches every "
        "task of the tenant."
    ),
)
async def list_cleaning_task_messages(
    authenticated: ReadDep,
    task_id: uuid.UUID,
    use_case: Annotated[
        ListCleaningTaskMessagesUseCase, Depends(get_list_cleaning_task_messages_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
) -> CleaningTaskMessagePageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        task_id=task_id,
        actor=_actor(authenticated, client_ip),
        page=page,
        per_page=per_page,
    )
    return CleaningTaskMessagePageResponse.build(result, page_number=page, per_page=per_page)
