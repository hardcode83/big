import uuid
from datetime import datetime, timezone

from app.messaging.domain.entities import Conversation, Message
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    MessageSenderType,
)


def test_conversation_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        channel=ConversationChannel.WHATSAPP,
        created_at=now,
        updated_at=now,
    )

    assert conversation.status == ConversationStatus.OPEN
    assert conversation.language == "es"
    assert conversation.ai_enabled is True
    assert conversation.escalation_status == ConversationEscalationStatus.NONE
    assert conversation.property_id is None


def test_message_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    message = Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        sender_type=MessageSenderType.GUEST,
        content="What time is check-in?",
        created_at=now,
    )

    assert message.ai_generated is False
    assert message.sender_user_id is None
    assert message.metadata is None
