import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    MessageSenderType,
)


@dataclass
class Conversation:
    id: uuid.UUID
    tenant_id: uuid.UUID
    channel: ConversationChannel
    created_at: datetime
    updated_at: datetime
    property_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    guest_id: uuid.UUID | None = None
    status: ConversationStatus = ConversationStatus.OPEN
    language: str = "es"
    last_message_at: datetime | None = None
    ai_enabled: bool = True
    escalation_status: ConversationEscalationStatus = ConversationEscalationStatus.NONE


@dataclass
class Message:
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: MessageSenderType
    content: str
    created_at: datetime
    sender_user_id: uuid.UUID | None = None
    language: str | None = None
    ai_generated: bool = False
    confidence_score: Decimal | None = None
    intent: str | None = None
    metadata: dict[str, Any] | None = None
