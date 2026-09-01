"""The in-app notification inbox (PRD §14, `access-notifications` R4 design D6, and
`notifications-inbox-web`).

Four routes now, and together they are what makes `InAppNotificationAdapter` honest: PRD §14
defines the in-app channel as "Notification entity + API polling", so marking a row `SENT` is
only a true statement while something can return it to its recipient — and, since
`notifications-inbox-web`, while that recipient can say they have read it.

**The cycle closes here.** Listing (optionally narrowed to the unread ones), counting the
unread, acknowledging one, and acknowledging every one of them. `access-notifications`
design D6 parked the acknowledgement as OQ2 for want of a `read_at` column PRD §7.24 does
not declare; `notifications-inbox-web` is the roadmap entry that decided it, added the
column and the routes, and closed that open question. The paragraph that used to stand here
saying there is no "mark as read" was true until then and is kept only in this sentence, so
a reader of the git history knows it was answered rather than forgotten.

**Polling, not SSE.** PRD §14 offers both; SSE is a long-lived connection through the
ingress with its own operational shape, and no screen consumes it. Inherited explicitly
rather than re-decided (`notifications-inbox-web` proposal, Out of scope).

**Every route derives its recipient from the token** and none takes a parameter that widens
that (R1.2) — the same restriction the listing route has had since the beginning.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.auth.api.dependencies import AuthenticatedRequest, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.notifications.api.dependencies import (
    get_count_unread_notifications_use_case,
    get_list_own_notifications_use_case,
    get_mark_all_notifications_read_use_case,
    get_mark_notification_read_use_case,
)
from app.notifications.api.schemas import (
    MarkAllReadResponse,
    NotificationPageResponse,
    UnreadCountResponse,
)
from app.notifications.application.use_cases import (
    CountUnreadNotificationsUseCase,
    ListOwnNotificationsUseCase,
    MarkAllNotificationsReadUseCase,
    MarkNotificationReadUseCase,
)

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
    unread: Annotated[bool | None, Query()] = None,
) -> NotificationPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        # From the token, never from the path or a query parameter: an endpoint that took a
        # user id would let any authenticated caller read a colleague's inbox.
        user_id=authenticated.context.user_id,
        page=page,
        per_page=per_page,
        unread=unread,
    )
    return NotificationPageResponse.build(result.items, result.total, page, per_page)


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="How many of the caller's own notifications are unread",
    description=(
        "The bell's counter (design D4). One query, independent of any `per_page` the "
        "caller may be using on the listing, and consistent with listing and counting "
        "`read_at IS NULL`. Its own route rather than a field of the paginated envelope, "
        "so the bell can refresh without dragging a page of rows across the wire."
    ),
)
async def count_unread_notifications(
    authenticated: ReadDep,
    use_case: Annotated[
        CountUnreadNotificationsUseCase, Depends(get_count_unread_notifications_use_case)
    ],
) -> UnreadCountResponse:
    unread = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        user_id=authenticated.context.user_id,
    )
    return UnreadCountResponse(unread=unread)


@router.post(
    "/read-all",
    response_model=MarkAllReadResponse,
    summary="Acknowledge every unread notification of the caller",
    description=(
        "Marks all of the caller's unread notifications as read and answers how many it "
        "moved. Its scope is **all** of them, deliberately not the page or filter the "
        "client happens to be showing (design D6). Zero is the normal answer of an inbox "
        "already up to date, never an error."
    ),
)
async def mark_all_notifications_read(
    authenticated: ReadDep,
    use_case: Annotated[
        MarkAllNotificationsReadUseCase, Depends(get_mark_all_notifications_read_use_case)
    ],
) -> MarkAllReadResponse:
    updated = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        user_id=authenticated.context.user_id,
    )
    return MarkAllReadResponse(updated=updated)


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Acknowledge one of the caller's own notifications",
    description=(
        "Records that the caller has read this notification. **Idempotent**: acknowledging "
        "one already read succeeds and does not move the recorded instant — `read_at` is "
        "the first read, not the last visit. A notification that does not exist, belongs "
        "to another user or belongs to another tenant answers the same `404` with the same "
        "body: a `403` would confirm the existence of somebody else's row."
    ),
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[
        MarkNotificationReadUseCase, Depends(get_mark_notification_read_use_case)
    ],
) -> Response:
    await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        user_id=authenticated.context.user_id,
        notification_id=notification_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
