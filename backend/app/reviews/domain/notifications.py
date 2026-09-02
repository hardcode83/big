"""The notifications a review produces (R6.2, design D9 of revenue-reviews).

Pure builder, calqued on `app/maintenance/domain/notifications.py` and
`app/messaging/domain/notifications.py`, so the **content** of what gets written is
testable without a session and lives next to the rule that shapes it — rule 11 of
`sdd/steering/security.md`, whose contract for `notification_logs.subject`/`body` was
fixed by `celery-jobs`: the body carries **ids and a type**, never the content of another
row. Nothing here reads the reviewer's `content`, the `ai_summary`, or the draft text.

**No `sla_deadline_at` on purpose** (D9): R6.2 says "notificación", not "notificación con
plazo". `escalation_for` has a rule for `REVIEW_RESPONSE_APPROVED` (added in this change),
but R6.2 leaves SLA optional — and the resolver does not set one here — so the deadline
column stays NULL.

**Channel + contact (notification-channel-routing D2/D3).** The builder accepts
`channel: NotificationChannel = IN_APP` and `contact: str | None = None` as **optional**
kwargs, the same shape as `cleaning/domain/notifications.py` and the other builders
listed in `tests/notifications/test_channel_literals.py::CHANNEL_LITERAL_WHITELIST`.
The default is the reason this file is on that allowlist: a legacy single-row test (or a
call site that has not been rewired through `dispatch_channels` yet) can still construct
the row without going through the fan-out.
"""

import uuid
from datetime import datetime

from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

#: `related_type` for a row that points at `reviews`. A constant because the polymorphic
#: pair is the only way a later reader can group by entity and a second spelling would
#: orphan the rows this change writes.
RELATED_TYPE_REVIEW = "review"

#: Subject line of the `REVIEW_RESPONSE_APPROVED` row. A constant for the same reason
#: every notification subject is — `notification_logs.subject` is a rule-11 sink and the
#: only thing this module may put there is a constant plus identifiers.
REVIEW_RESPONSE_APPROVED_SUBJECT = "Review response approved"


def build_review_response_approved_log(
    *,
    tenant_id: uuid.UUID,
    review_id: uuid.UUID,
    property_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    recipient_contact: str = "",
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """The `REVIEW_RESPONSE_APPROVED` row a manager/owner receives (R6.2).

    The body names the review and the property and says nothing else. Not a word of what
    the reviewer wrote, and not the draft text either — the draft lives in
    `review_response_drafts.draft_content` and is reachable via the `review_id` it names.

    `status = PENDING`: queued work for the sender `access-notifications` left running,
    which is what moves it to `SENT`.

    `channel` and `contact` are the optional kwargs that `dispatch_channels` populates
    per channel; `recipient_contact` is kept as the legacy parameter so existing tests
    that build a single row continue to work without going through the fan-out.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=recipient_user_id,
        recipient_contact=contact if contact is not None else recipient_contact,
        channel=channel,
        notification_type=NotificationType.REVIEW_RESPONSE_APPROVED.value,
        created_at=now,
        updated_at=now,
        subject=REVIEW_RESPONSE_APPROVED_SUBJECT,
        body=(
            f"A review response has been approved. Review {review_id}, "
            f"property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_REVIEW,
        related_id=review_id,
    )
