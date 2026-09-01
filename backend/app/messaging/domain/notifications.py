"""What gets written when a conversation reaches a person (R5.2, design D20;
`notification-channel-routing` R2, R4).

A pure builder, calqued on `app/maintenance/domain/notifications.py`, so the **content** of
the row is testable without a session and lives next to the rule that shapes it. That rule is
rule 11 of `sdd/steering/security.md`, whose contract for `notification_logs.subject`/`body`
was fixed by `celery-jobs`: this change does not derive a new one, it complies with the one
that exists — the body carries **ids and a type**, never the content of another row. Nothing
here reads the message the guest sent.

**Channel + contact (notification-channel-routing R2, R4, design D2, D3).** The builder
accepts `channel: NotificationChannel = IN_APP` and `contact: str | None = None` as
**optional** kwargs. `recipient_contact` derives from `contact` when given, otherwise
falls back to the legacy parameter. The dispatcher in
`notifications/application/channel_dispatch.py` is the function that calls this builder
once per resolved channel.
"""

import uuid
from datetime import datetime

from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

#: `related_type` for a row that points at `conversations`. A constant because anything that
#: later reads these rows back through the polymorphic pair would be orphaned by a second
#: spelling.
RELATED_TYPE_CONVERSATION = "conversation"

GUEST_ESCALATION_SUBJECT = "Guest conversation escalated"


def guest_escalation_notification(
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    property_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    recipient_contact: str = "",
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """The `GUEST_ESCALATION` row a manager gets when the AI hands a conversation over (R5.2).

    `NotificationType.GUEST_ESCALATION` has existed since `celery-jobs` with no writer; this
    is it.

    **No `sla_deadline_at`, on purpose** (D20). `escalation_for`
    (`app/notifications/domain/escalation.py`) has no rule for `GUEST_ESCALATION`, so a
    deadline here would produce a breach that escalates to nobody — exactly the reasoning
    `owner_approval_notification` records for `OWNER_APPROVAL_REQUIRED`. The SLA of a human
    reply is `celery-jobs`' machinery and is out of this change's scope.

    `status = PENDING`: queued work for the sender `access-notifications` left running, which
    is what moves it to `SENT`.

    The body names the conversation and the property and says nothing else. Not a word of what
    the guest wrote, and not the escalation reason either — the reason is an enum and would be
    safe, but it lives on the message's `metadata` and on the timeline event, and a third copy
    is a third thing to keep true.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=recipient_user_id,
        recipient_contact=contact if contact is not None else recipient_contact,
        channel=channel,
        notification_type=NotificationType.GUEST_ESCALATION.value,
        created_at=now,
        updated_at=now,
        subject=GUEST_ESCALATION_SUBJECT,
        body=(
            f"A guest conversation needs a person. Conversation {conversation_id}, "
            f"property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_CONVERSATION,
        related_id=conversation_id,
    )