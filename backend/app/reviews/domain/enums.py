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


class RecurringIssueTag(str, enum.Enum):
    """The closed set of labels `reviews.recurring_issues` may carry (R2.2, design D7).

    Nine members and not a `str` because the column is the only thing the manager uses to
    decide what to fix, and an invented label cannot reach it. PRD §18 names them in prose;
    this enum is the spelling the table accepts, and the test
    `tests/reviews/test_recurring_issues_vocabulary.py` walks `backend/app/reviews/infrastructure/`
    to ensure no adapter smuggles an unknown value past the constructor.

    `OTHER` is the degradation sink: an adapter that invents a tag is dropped to `OTHER`
    by `Review.__post_init__` with a `logger.warning`, so the catalogue can be widened
    deliberately rather than silently accumulating synonyms.
    """

    WIFI = "WIFI"
    NOISE = "NOISE"
    CLEANLINESS = "CLEANLINESS"
    ACCESS = "ACCESS"
    COMMUNICATION = "COMMUNICATION"
    LOCATION = "LOCATION"
    VALUE = "VALUE"
    AMENITIES = "AMENITIES"
    OTHER = "OTHER"
