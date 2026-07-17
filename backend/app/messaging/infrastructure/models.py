import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    MessageSenderType,
)


class ConversationModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_tenant_id_status", "tenant_id", "status"),
        Index("ix_conversations_reservation_id", "reservation_id"),
    )

    property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), default=None
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), default=None
    )
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("guests.id", ondelete="RESTRICT"), default=None
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        Enum(ConversationChannel, name="conversation_channel", native_enum=True)
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status", native_enum=True),
        default=ConversationStatus.OPEN,
        server_default=ConversationStatus.OPEN.value,
    )
    language: Mapped[str] = mapped_column(String(5), default="es", server_default="es")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    escalation_status: Mapped[ConversationEscalationStatus] = mapped_column(
        Enum(ConversationEscalationStatus, name="conversation_escalation_status", native_enum=True),
        default=ConversationEscalationStatus.NONE,
        server_default=ConversationEscalationStatus.NONE.value,
    )


class MessageModel(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="RESTRICT")
    )
    sender_type: Mapped[MessageSenderType] = mapped_column(
        Enum(MessageSenderType, name="message_sender_type", native_enum=True)
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    content: Mapped[str] = mapped_column()
    language: Mapped[str | None] = mapped_column(String(5), default=None)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), default=None)
    intent: Mapped[str | None] = mapped_column(String(100), default=None)
    # Mapped as `metadata_` to avoid colliding with SQLAlchemy's reserved
    # Base.metadata attribute — the real column name stays "metadata"
    # (same pattern as TimelineEventModel, D7).
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
