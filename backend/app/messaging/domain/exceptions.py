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


class NoInboundMessageError(MessagingDomainError):
    """The webhook body is well-formed but carries no inbound message
    (`whatsapp-cloud-adapter` R3.2, R4.1; design D9) — answered 422 if it ever escapes.

    Raised by `WhatsAppInboundProviderAdapter.parse`, and **it is a routine outcome rather
    than a fault**: Meta posts delivery and read receipts to the very same webhook URL as
    real messages, with `value.statuses` where a message would have had `value.messages`.
    A deployment that receives one message receives many of these. The same error covers an
    empty `entry`/`changes`/`messages`, a body that is not a JSON object at all, and a
    message with no text body (an image, a sticker, a location) — none of which the
    text-in/text-out pipeline of this change can process.

    **Its own class, and not `MessagingValidationError`**, because the two need opposite
    handling. A `MessagingValidationError` means somebody sent something wrong; this means
    nothing is wrong and there is simply nothing to do. The receiving use case of section 7
    must **catch it and answer `202`**: Meta redelivers on any non-2xx, so letting it reach
    the error handler would make every status receipt retry on a schedule forever, and the
    endpoint would spend its rate-limit budget on its own delivery receipts.

    The 422 row it has in `api/errors.py` is therefore the second net and not the plan — it
    exists so an escape is a named 422 rather than an unmapped 500 that leaks internals
    (`test_errors.py` requires the row of every error in this module).

    **The message names the field that was missing and never its value.** A webhook body is
    the guest's phone number and the guest's words, and `str(exc)` is rendered into the
    response body and into every log line — the standing rule of
    `domain/value_objects.py` applies here for the same reason.
    """

class WhatsAppPhoneNumberAlreadyAssociatedError(MessagingDomainError):
    """That `phone_number_id` already belongs to another tenant (R6.2) — answered 409.

    `AssociateWhatsAppPhoneNumberUseCase.execute` never checks this with a prior read: the
    value is genuinely global across tenants, so a read-then-write has a real TOCTOU race two
    concurrent tenants could both win. The repository's `upsert` lets the database's own
    unique constraint on `phone_number_id` raise, and this is what that `IntegrityError` is
    translated into — the existing association is never overwritten in silence (design D8,
    `steering/backend-architecture.md`'s "database-level check, not a prior read").
    """

class WhatsAppPhoneNumberNotFoundError(MessagingDomainError):
    """This tenant has no WhatsApp number associated — answered 404.

    Raised by `ReleaseWhatsAppPhoneNumberUseCase` when there is nothing to release. Not the
    same class as `WhatsAppPhoneNumberAlreadyAssociatedError`: one means "somebody else already
    has this number", the other "you have none to give up" — conflating them would answer a
    409 for a request that named no conflicting resource at all.
    """

class WhatsAppWebhookAuthenticationError(MessagingDomainError):
    """The inbound WhatsApp webhook did not authenticate — answered `403`, always the same.

    `whatsapp-cloud-adapter` R3.2, R3.3; design D3a. **One class, carrying no reason, raised
    from one place**, which is the whole of R3.3's indistinguishability: a missing
    `X-Hub-Signature-256`, a malformed one, a digest computed under another key and a body
    altered after signing are four different facts and exactly one answer. The structural
    sibling is `app/integrations/domain/errors.py`'s `WebhookAuthenticationError`, whose
    docstring records the same argument for the PMS receiver's uniform `404`.

    It carries no message either. `register_messaging_error_handlers` renders `str(exc)` into
    the envelope for any mapped status, so a message would become the oracle the class exists
    to close — and `ReceiveWhatsAppWebhookUseCase` raises it with no argument.

    **Nothing is written before this is raised.** The use case's `authenticate` touches no
    repository at all, which is what makes "sin escribir nada" a property of the call graph
    rather than of a caller remembering to roll back.
    """
