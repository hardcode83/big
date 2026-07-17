import enum


class ConversationChannel(str, enum.Enum):
    WHATSAPP = "WHATSAPP"
    AIRBNB_MSG = "AIRBNB_MSG"
    BOOKING_MSG = "BOOKING_MSG"
    EMAIL = "EMAIL"
    PHONE_TRANSCRIPT = "PHONE_TRANSCRIPT"
    MANUAL = "MANUAL"


class ConversationStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Conversation.status) without a named block (§7.14)."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class ConversationEscalationStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Conversation.escalation_status) without a named block (§7.14)."""

    NONE = "NONE"
    PENDING_HUMAN = "PENDING_HUMAN"
    HUMAN_HANDLING = "HUMAN_HANDLING"
    RESOLVED = "RESOLVED"


class MessageSenderType(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Message.sender_type) without a named block (§7.15)."""

    GUEST = "GUEST"
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    AI = "AI"
    SYSTEM = "SYSTEM"
