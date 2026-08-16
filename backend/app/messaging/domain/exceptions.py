"""Domain errors of the messaging module (R1.5, R5.3, R6.3, design D4, D17).

Pure Python, exactly like `app/maintenance/domain/exceptions.py`: no import of
`app.core.errors`, because that module imports FastAPI and pulling it in here would put the
web framework inside `domain/` transitively. The translation to a status code lives in
`app/messaging/api/errors.py`.

The hierarchy is **flat on purpose**. `api/errors.py` resolves its table by `isinstance`
with first-match-wins, so a subclass is only answered correctly while its row happens to sit
above its base's — a property of the literal's line order, not of the type. `maintenance` and
`cleaning` both reached this conclusion before this module existed.
"""


class MessagingDomainError(Exception):
    """Base error for the messaging domain."""


#: The **one** message every conversation not-found path uses (R1.5). Two 404s with
#: distinguishable bodies are a probe: a body saying "belongs to another tenant" confirms the
#: conversation exists, which is precisely what R1.5 forbids being able to tell apart.
CONVERSATION_NOT_FOUND_MESSAGE = "Conversation does not exist"


class ConversationNotFoundError(MessagingDomainError):
    """The conversation does not exist *within the acting tenant* — answered 404.

    Deliberately the same error whether the id is unknown or belongs to another tenant
    (R1.5). It is not a courtesy: the repository reaches both outcomes through **the same
    query returning zero rows** (D3), so there is no branch that could tell them apart even
    if someone wanted to.

    **The constructor takes no message**, which is the difference from
    `IncidentNotFoundError` in `maintenance`. That one defaults to a constant and asks
    callers not to override it; the tenancy reviewer of section 2 pointed out that "callers
    do not override it" is a convention a future call site can break in one line, and R1.5
    is precisely a promise that no call site may break. Removing the parameter makes the
    single message a property of the type.
    """

    def __init__(self) -> None:
        super().__init__(CONVERSATION_NOT_FOUND_MESSAGE)


class InvalidConversationTransitionError(MessagingDomainError):
    """The conversation's current state does not admit the requested move (R5.3) — 409.

    Raised by the entity against its own two transition tables, never by a use case: the
    legal moves of a `Conversation` are a business rule, and `steering/backend-architecture.md`
    puts those in `domain/`. It is also what makes R5.4 true — `escalate` accepts only
    `NONE` as an origin, so a second escalation of the same conversation cannot happen and
    therefore cannot notify twice (D20).
    """


class ConversationClosedError(MessagingDomainError):
    """The conversation is `CLOSED` and admits no further message (D4) — answered 409.

    Its own class rather than an `InvalidConversationTransitionError`, because a closed
    conversation is not "the wrong step in the flow": no later step will ever admit it, so
    the caller has nothing to retry. A `RESOLVED` conversation is the opposite case — an
    inbound guest message reopens it — and never raises this.
    """


class PMSChannelUnavailableError(MessagingDomainError):
    """The conversation's channel only exists through the PMS (R6.3) — answered 422.

    `AIRBNB_MSG` and `BOOKING_MSG` are absent from the outbound registry of D14, so nothing
    can send on them until `beds24-messaging-adapter` implements `PMSMessagingPort`. Raising
    is the point: the alternative R6.3 forbids is falling back to a console adapter, where
    the operator would see a delivered message the guest never received.
    """


class MessagingValidationError(MessagingDomainError):
    """An invariant of an aggregate or value object was violated — answered 422."""
