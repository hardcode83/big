"""The `GUEST_ESCALATION` row, and the deadline it deliberately does not open (R5.2, D20)."""

import uuid
from datetime import datetime, timezone

from app.messaging.domain.notifications import (
    GUEST_ESCALATION_SUBJECT,
    RELATED_TYPE_CONVERSATION,
    guest_escalation_notification,
)
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)
CONVERSATION_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
PROPERTY_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def build() -> object:
    return guest_escalation_notification(
        tenant_id=uuid.uuid4(),
        conversation_id=CONVERSATION_ID,
        property_id=PROPERTY_ID,
        recipient_user_id=uuid.uuid4(),
        recipient_contact="manager@example.com",
        now=NOW,
    )


def test_the_row_is_a_pending_in_app_guest_escalation() -> None:
    """R5.2. `NotificationType.GUEST_ESCALATION` has existed since `celery-jobs` with no
    writer; this is its first."""
    notification = build()

    assert notification.notification_type == NotificationType.GUEST_ESCALATION.value
    assert notification.channel is NotificationChannel.IN_APP
    assert notification.status is NotificationStatus.PENDING


def test_the_row_points_at_the_conversation() -> None:
    notification = build()

    assert notification.related_type == RELATED_TYPE_CONVERSATION
    assert notification.related_id == CONVERSATION_ID


def test_the_row_opens_no_sla_deadline() -> None:
    """D20, and it is a decision rather than an omission: `escalation_for` has no rule for
    `GUEST_ESCALATION`, so a deadline here would produce a breach that escalates to nobody —
    the same reasoning `owner_approval_notification` records. The SLA of a human reply is
    `celery-jobs`' machinery and is out of scope."""
    notification = build()

    assert notification.sla_deadline_at is None
    assert notification.sla_breached is False


def test_the_body_carries_identifiers_and_nothing_else() -> None:
    """Rule 11 of `steering/security.md` for `notification_logs.subject`/`body`, as
    `celery-jobs` fixed it: ids and a type, never the content of another row. Nothing here
    reads the message the guest sent."""
    notification = build()

    assert notification.subject == GUEST_ESCALATION_SUBJECT
    assert str(CONVERSATION_ID) in notification.body
    assert str(PROPERTY_ID) in notification.body

    remainder = notification.body.replace(str(CONVERSATION_ID), "").replace(
        str(PROPERTY_ID), ""
    )
    assert remainder == "A guest conversation needs a person. Conversation , property ."


def test_the_builder_is_pure() -> None:
    """Two calls with the same arguments differ only in the row's own id, so the content is
    testable without a session — which is the whole reason it lives in `domain/`."""
    first, second = build(), build()

    assert first.body == second.body
    assert first.created_at == second.created_at == NOW
    assert first.id != second.id
