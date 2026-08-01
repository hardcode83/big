import enum


class NotificationChannel(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (NotificationLog.channel) without a named block (§7.24). Not the same enum as
    ConversationChannel (§7.14): PUSH, IN_APP and CONSOLE do not exist there."""

    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    PUSH = "PUSH"
    IN_APP = "IN_APP"
    CONSOLE = "CONSOLE"


class NotificationStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (NotificationLog.status) without a named block (§7.24)."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
