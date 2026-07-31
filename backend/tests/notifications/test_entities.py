import uuid
from datetime import datetime, timezone

from app.messaging.domain.enums import ConversationChannel
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus


def test_notification_log_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    log = NotificationLog(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        recipient_contact="owner@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type="cleaning.assigned",
        created_at=now,
        updated_at=now,
    )

    assert log.status is NotificationStatus.PENDING
    assert log.attempts == 0
    assert log.sla_breached is False
    assert log.recipient_user_id is None
    assert log.sla_deadline_at is None


def test_notification_channel_is_not_the_conversation_channel() -> None:
    """D6: three distinct `channel` enums, deliberately not shared."""
    notification_values = {member.value for member in NotificationChannel}
    conversation_values = {member.value for member in ConversationChannel}

    assert {"PUSH", "IN_APP", "CONSOLE"} <= notification_values
    assert not {"PUSH", "IN_APP", "CONSOLE"} & conversation_values
    assert NotificationChannel is not ConversationChannel
