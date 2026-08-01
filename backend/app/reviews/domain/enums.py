import enum


class ReviewChannel(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Review.channel) without a named block (§7.20). Not the same enum as
    ConversationChannel or NotificationChannel — different values."""

    AIRBNB = "AIRBNB"
    BOOKING = "BOOKING"
    GOOGLE = "GOOGLE"
    MANUAL = "MANUAL"
    OTHER = "OTHER"


class ReviewSentiment(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Review.sentiment) without a named block (§7.20)."""

    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class ReviewStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Review.status) without a named block (§7.20)."""

    NEW = "NEW"
    DRAFTED = "DRAFTED"
    APPROVED = "APPROVED"
    POSTED_MANUALLY = "POSTED_MANUALLY"
    IGNORED = "IGNORED"
