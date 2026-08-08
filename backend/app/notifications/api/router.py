"""The in-app notification inbox (PRD §14, `access-notifications` R4, design D6).

One route, and it is what makes `InAppNotificationAdapter` honest: PRD §14 defines the
in-app channel as "Notification entity + API polling", so marking a row `SENT` is only a
true statement while something can return it to its recipient.

**Polling, not SSE.** PRD §14 offers both; SSE is a long-lived connection through the
ingress with its own operational shape, and no screen consumes it yet.

**No "mark as read".** That needs a `read_at` column PRD §7.24 does not declare, and design
D6 decided not to invent schema for it here. Recorded as OQ2 of this change's `BLOCKED.md`,
so it is a parked decision rather than an oversight.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.api.dependencies import AuthenticatedRequest, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.notifications.api.dependencies import get_list_own_notifications_use_case
from app.notifications.api.schemas import NotificationPageResponse
from app.notifications.application.use_cases import ListOwnNotificationsUseCase

MAX_PER_PAGE = 100
# Same ceiling and same reason as `cleaning`/`reservations`: `page` becomes a SQL OFFSET, and
# a 20-digit page number overflows int8 into a driver error instead of a 422.
MAX_PAGE = 100_000

router = APIRouter(
    prefix="/notifications", tags=["notifications"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.READ_OWN_NOTIFICATIONS))
]


@router.get(
    "",
    response_model=NotificationPageResponse,
    summary="List the caller's own notifications",
    description=(
        "The in-app channel of PRD §14. Returns only the notifications addressed to the "
        "authenticated user — the restriction is derived from the token and there is no "
        "parameter that widens it. Newest first, paginated with `page`/`per_page` (PRD §23)."
    ),
)
async def list_own_notifications(
    authenticated: ReadDep,
    use_case: Annotated[
        ListOwnNotificationsUseCase, Depends(get_list_own_notifications_use_case)
    ],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
) -> NotificationPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        # From the token, never from the path or a query parameter: an endpoint that took a
        # user id would let any authenticated caller read a colleague's inbox.
        user_id=authenticated.context.user_id,
        page=page,
        per_page=per_page,
    )
    return NotificationPageResponse.build(result.items, result.total, page, per_page)
