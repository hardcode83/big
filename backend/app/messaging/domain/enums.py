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


class MessageIntent(str, enum.Enum):
    """What a guest's message is about (`messaging-ai` R2.3, design D5).

    The fourteen names are **literally** the ones PRD §13 lists, and a test pins each of
    them: `messages.intent` is a `VARCHAR(100)` that looks like an enum and is not one, so
    the column's closed form (rule 11 of `steering/security.md`, D16) rests on this type
    alone. A rename that only touched Python would silently split every persisted row into
    a value nobody maps.

    No `ASSUMPTION` on the *name*, unlike its three siblings above: the PRD declares this
    vocabulary as a block of its own, and only leaves it unnamed — and `<Entidad><Campo>`
    yields `MessageIntent` anyway.

    `UNKNOWN` is a real member and not an error: it is what a classifier returns when it has
    no verdict, and what `Message` degrades an unrecognised value to (R3.4).
    """

    CHECKIN_INSTRUCTIONS = "CHECKIN_INSTRUCTIONS"
    ACCESS_PROBLEM = "ACCESS_PROBLEM"
    WIFI = "WIFI"
    PARKING = "PARKING"
    LATE_CHECKOUT = "LATE_CHECKOUT"
    EARLY_CHECKIN = "EARLY_CHECKIN"
    CLEANING_ISSUE = "CLEANING_ISSUE"
    MAINTENANCE_ISSUE = "MAINTENANCE_ISSUE"
    NOISE = "NOISE"
    REFUND_OR_COMPENSATION = "REFUND_OR_COMPENSATION"
    EMERGENCY = "EMERGENCY"
    GENERAL_FAQ = "GENERAL_FAQ"
    REVIEW_REQUEST = "REVIEW_REQUEST"
    UNKNOWN = "UNKNOWN"


class EscalationReason(str, enum.Enum):
    """Why a conversation stopped being the AI's to answer (R5.1, design D10).

    Six of the seven are the conditions PRD §13 enumerates. `DELIVERY_FAILED` is the
    seventh and is **not** from the PRD: the six decide *whether to answer*, while this one
    is the state a conversation is left in when the answer could not be delivered (D14), and
    R6.5 requires a human be able to recover it. Named as a divergence rather than smuggled
    in among the others.

    The declaration order here is documentation only — the order that decides which reason
    wins when several hold at once is declared and tested in
    `app/messaging/domain/escalation.py`, because that is where it is applied.
    """

    EMERGENCY_KEYWORD = "EMERGENCY_KEYWORD"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    EMERGENCY_INTENT = "EMERGENCY_INTENT"
    REFUND_OR_COMPENSATION = "REFUND_OR_COMPENSATION"
    IMMINENT_CHECKIN_ACCESS_PROBLEM = "IMMINENT_CHECKIN_ACCESS_PROBLEM"
    REPEATED_INTENT = "REPEATED_INTENT"
    DELIVERY_FAILED = "DELIVERY_FAILED"
