"""The values that cross the ports of `messaging` (R2.4, R2.1, R3.5, R6.5; design D6, D14, D15).

Every one of them is frozen and every one of them checks its own contract in
`__post_init__`, which is the lesson `IncidentClassification` paid for in `maintenance`: an
obligation written as prose on a port is satisfied by accident of who wrote the only adapter
so far, and a second implementation inherits nothing. A check here reaches **every** adapter
that returns the declared type, wherever it lives — including `app/integrations/`, which is
where a real model provider would go.

`SUPPORTED_LANGUAGES` comes from `app/tenants/domain/value_objects.py` rather than being
restated: it is the list of locales that exist in `frontend/locales/`, and two copies of it
would let this module answer in a language the UI cannot render. Importing another domain's
`domain/` is the direction the dependency rule allows, and what `maintenance` already does
for `TenantConfig`.

**No refusal message ever quotes the value it refused.** The values here come from an
adapter that tomorrow is an external model provider, so a rejected `intent` or `language`
can be model output derived from the guest's message. `MessagingValidationError` is answered
422 and `api/errors.py` renders `str(exc)` into the body, so echoing the bad value would
push into the response — and into every log line — precisely the text the rule-11 contract
kept out of the column. The messages name the field and the expected shape instead. Raised by
the security panel of sections 1-2.
"""

import enum
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.messaging.domain.enums import (
    ConversationChannel,
    EscalationReason,
    MessageIntent,
)
from app.messaging.domain.exceptions import MessagingValidationError
from app.tenants.domain.value_objects import SUPPORTED_LANGUAGES


def is_template_key(candidate: object) -> bool:
    """Whether `candidate` is a well-formed `"<INTENT>:<lang>"` identifier.

    Both `GeneratedResponse.template_key` and `MessageMetadata.template_key` are checked
    against this rather than being trusted as strings. The precedent is the neighbouring
    column: `steering/security.md` censuses `incidents.ai_classification` as structured and
    records that `adapter`, its one non-enum key, "degrada a `UNKNOWN_CLASSIFIER` si no es un
    identificador de Python" — because a key that merely *looks* like an identifier is the
    hole a rule-11 sink is censused for. Raised by the security panel of sections 1-2.
    """
    if not isinstance(candidate, str):
        return False
    intent, separator, language = candidate.partition(":")
    if not separator or language not in SUPPORTED_LANGUAGES:
        return False
    return intent in {member.value for member in MessageIntent}


#: The shape a template catalogue version may take, e.g. `2026-08-16.1` — a date and a
#: revision. Checked for the same reason `template_key` is: it is persisted into
#: `messages.metadata`, and "a version string" is not a closed form until something says so.
_TEMPLATE_VERSION = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")


@dataclass(frozen=True)
class MessageClassification:
    """What an `AIAdapter` says a guest's message is about (R2.4, design D6).

    **No `vocabulary` field, unlike `GeneratedResponse` below, and the asymmetry is
    deliberate**: the closed vocabulary of a classification *is* `MessageIntent`, so checking
    it is an `isinstance`. A `vocabulary` an adapter would fill with `frozenset(MessageIntent)`
    checks nothing the `isinstance` does not already check, and a ceremonial field invites the
    belief that the ceremony is the guarantee.

    `confidence` is a `0..1` fraction compared against `TenantConfig.ai_confidence_threshold`
    (R4.2). A value outside that range is a broken adapter rather than a low score — a
    percentage (`85`) would never be below any threshold, so every message would be answered
    with an air of certainty the adapter did not intend.

    **No `requires_escalation` field**, and that is D10's decision rather than an omission:
    PRD §13 suggests one, but it would put the escalation policy inside the adapter — that
    is, inside what tomorrow is an external provider. The system decides when it escalates.
    """

    intent: MessageIntent
    confidence: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.intent, MessageIntent):
            raise MessagingValidationError(
                "intent must be a MessageIntent member, got "
                f"{type(self.intent).__name__}; messages.intent is a closed form "
                "(rule 11 of steering/security.md, D16)"
            )
        if not Decimal(0) <= self.confidence <= Decimal(1):
            raise MessagingValidationError(
                "Classification confidence must be a fraction within 0..1"
            )


@dataclass(frozen=True)
class GeneratedResponse:
    """What an `AIAdapter` proposes to send back (R2.4, R2.6, R3.3; design D6, D7).

    **`vocabulary` is the admission condition of rule 11 for this column, not the whole
    guarantee**, and the difference is written down in `steering/security.md` for the
    identical construction in `maintenance`: "un adaptador que construya su `vocabulary` **a
    partir de su propia salida** satisface la comprobación trivialmente… es **segunda red y
    no la garantía**." So what this class enforces is that an adapter *declares* the closed
    catalogue its `content` came from and cannot then return something outside it — which
    reaches every adapter that returns the declared type, wherever it lives.

    What closes the remaining gap for `messages.content` is a **runtime** check the pipeline
    of section 6 owes: before persisting an AI reply it asserts the `content` is a member of
    `templates.RESPONSE_VOCABULARY` — the catalogue itself, not the set the adapter declared.
    The free-text sink contract test of task 8.2 is what pins that check; it is not a
    substitute for it, because a test does not guard a production write.

    `template_key` is `"<INTENT>:<lang>"` — checked below, so it is an identifier rather
    than a promise of one — which is what makes it safe to carry into `messages.metadata`
    (D15) where an operator can see which template answered.
    """

    content: str
    language: str
    template_key: str
    vocabulary: frozenset[str]

    def __post_init__(self) -> None:
        if self.language not in SUPPORTED_LANGUAGES:
            raise MessagingValidationError(
                "Generated response is not in a supported language; expected one of "
                f"{', '.join(SUPPORTED_LANGUAGES)}"
            )
        if not is_template_key(self.template_key):
            raise MessagingValidationError(
                "template_key must be '<INTENT>:<language>', with a MessageIntent member "
                "and a supported language"
            )
        if not self.vocabulary:
            raise MessagingValidationError(
                "An AI adapter must declare the closed vocabulary its content comes from "
                "(rule 11 of steering/security.md, design D7)"
            )
        if self.content not in self.vocabulary:
            raise MessagingValidationError(
                "Generated content is not in the adapter's declared vocabulary, so it may "
                "carry guest text into messages.content, a rule-11 free-text sink"
            )


@dataclass(frozen=True)
class ConversationContext:
    """What an `AIAdapter` is told about the conversation it is classifying (R2.1, design D6).

    **Identifiers and closed values only — never the message history, never a name, never
    anything anybody typed.** The one free-form string an adapter receives is the content of
    the message it was asked about, which it needs by definition; this object is everything
    *else* it gets, and the list is closed because it is handed to something that tomorrow is
    an external provider with its own logging.

    `guest_message_count` is a number rather than the messages themselves for the same
    reason: the only question the pipeline asks of the history is "how many", and a count
    cannot leak.
    """

    conversation_id: uuid.UUID
    property_id: uuid.UUID | None
    reservation_id: uuid.UUID | None
    channel: ConversationChannel
    language: str
    ai_enabled: bool
    guest_message_count: int

    def __post_init__(self) -> None:
        """Six of the seven fields are closed by their type; `language` is the one that is not.

        Without this check the claim above — identifiers and closed values only — would hold
        for the *field list* and not for the values, and whatever string a conversation row
        happens to carry would ship to an external provider with its own logging. The
        security panel of sections 1-2 pointed out that this was the only value object in the
        module with no contract of its own.
        """
        if self.language not in SUPPORTED_LANGUAGES:
            raise MessagingValidationError(
                "Conversation context language must be one of "
                f"{', '.join(SUPPORTED_LANGUAGES)}"
            )
        if self.guest_message_count < 0:
            raise MessagingValidationError("guest_message_count cannot be negative")


class ChannelErrorCode(str, enum.Enum):
    """Why an outbound send did not succeed (R6.5, design D14).

    Deliberately coarse, and deliberately an enum rather than a string — the same decision
    `NotificationErrorCode` records, for the same reason: a provider SDK's exception
    routinely embeds the very message it failed to send, and the natural `str(exc)` would
    carry the body straight into `messages.metadata`. It **does not fit in the return type**,
    so no adapter can pass it on without changing this file, which is a diff a reviewer sees.
    """

    #: `recipient_contact` is empty or not addressable on this channel.
    INVALID_RECIPIENT = "INVALID_RECIPIENT"
    #: The channel carries messages inwards only — `PHONE_TRANSCRIPT` (D14).
    CHANNEL_INBOUND_ONLY = "CHANNEL_INBOUND_ONLY"
    #: The adapter reported a failure it could not classify further.
    ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"


#: Which of a guest's contact details addresses a reply on each channel — and `None` for the
#: channels that address nobody: `MANUAL`, where the row *is* the delivery, and
#: `PHONE_TRANSCRIPT`, which has no outbound direction. The two OTA channels are absent for the
#: reason R6.3 gives, and a channel missing from this mapping simply has no address.
#:
#: A rule, so it lives in `domain/` rather than as a chain of `if`s in the pipeline
#: ("si hay una regla, pertenece a `domain/`" — `steering/backend-architecture.md`). The
#: architecture panel of sections 5-6 found it in `application/`.
_CONTACT_KIND_BY_CHANNEL: dict[ConversationChannel, str] = {
    ConversationChannel.WHATSAPP: "phone",
    ConversationChannel.EMAIL: "email",
}


def contact_kind_for(channel: ConversationChannel) -> str | None:
    """`"phone"`, `"email"`, or `None` when the channel addresses nobody (D14)."""
    return _CONTACT_KIND_BY_CHANNEL.get(channel)


@dataclass(frozen=True)
class ChannelSendResult:
    """The outcome of one `OutboundMessagePort.send` — by value, never by exception (D14).

    The pattern of `NotificationResult`, and the reason is R6.5: an exception would abort the
    transaction and take the AI's message down with it, which is the one outcome that rule
    forbids ("NEVER SHALL perder el mensaje en silencio"). A value lets the pipeline persist
    the message, mark the failure in its metadata and escalate the conversation, all inside
    the single transaction of D11.

    **There is no string field at all.** Whatever the adapter knows beyond the code stays
    with the adapter.
    """

    delivered: bool
    error_code: ChannelErrorCode | None = None

    def __post_init__(self) -> None:
        if self.delivered and self.error_code is not None:
            raise MessagingValidationError("a delivered result carries no error code")
        if not self.delivered and self.error_code is None:
            raise MessagingValidationError("a failed result must name its error code")

    @classmethod
    def ok(cls) -> "ChannelSendResult":
        return cls(delivered=True)

    @classmethod
    def failure(cls, error_code: ChannelErrorCode) -> "ChannelSendResult":
        return cls(delivered=False, error_code=error_code)


#: The two values `MessageMetadata.delivery_status` may take (D15). Constants and not a new
#: enum, because they are the outcome of one `OutboundMessagePort.send` and nothing else in
#: the system branches on them; what matters is that the set is closed and checked.
DELIVERY_STATUS_SENT = "SENT"
DELIVERY_STATUS_FAILED = "FAILED"
_DELIVERY_STATUSES = frozenset({DELIVERY_STATUS_SENT, DELIVERY_STATUS_FAILED})


@dataclass(frozen=True)
class MessageMetadata:
    """The closed set of keys `messages.metadata` may carry (R3.5, design D15).

    The column is `JSONB`, which is the shape that invites "just put the rest in here", and
    rule 11 of `steering/security.md` treats it as a free-text sink for exactly that reason.
    The remedy is the one `ChangeSet` uses for `audit_logs.changes`: **the repository accepts
    this type and not a `dict`**, so there is no signature through which a use case written
    next year can pass the guest's words. `Message.metadata` is typed as this class for the
    same reason — the security panel of sections 1-2 found that a `dict[str, Any]` on the
    aggregate reopened the hole the value object was built to close.

    Every field is an identifier, an enum member or a closed constant, and the two that are
    plain strings are checked rather than trusted (`is_template_key`, `_TEMPLATE_VERSION`).
    `to_dict()` emits only the keys that are set, so a message that was merely delivered does
    not carry five nulls explaining what did not happen to it.
    """

    escalation_reason: EscalationReason | None = None
    template_key: str | None = None
    template_version: str | None = None
    delivery_status: str | None = None
    delivery_error_code: ChannelErrorCode | None = None
    source_message_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.escalation_reason is not None and not isinstance(
            self.escalation_reason, EscalationReason
        ):
            raise MessagingValidationError(
                "escalation_reason must be an EscalationReason member"
            )
        if self.delivery_error_code is not None and not isinstance(
            self.delivery_error_code, ChannelErrorCode
        ):
            raise MessagingValidationError(
                "delivery_error_code must be a ChannelErrorCode member"
            )
        if self.delivery_status is not None and self.delivery_status not in _DELIVERY_STATUSES:
            raise MessagingValidationError(
                f"delivery_status must be one of {sorted(_DELIVERY_STATUSES)}"
            )
        if self.template_key is not None and not is_template_key(self.template_key):
            raise MessagingValidationError(
                "template_key must be '<INTENT>:<language>', with a MessageIntent member "
                "and a supported language"
            )
        # `fullmatch`, not `match`: `$` also matches just before a trailing newline, so
        # `"2026-08-16.1\n"` would pass a `match` and reach the column. A closed form that
        # admits a trailing newline is not closed.
        if self.template_version is not None and not (
            isinstance(self.template_version, str)
            and _TEMPLATE_VERSION.fullmatch(self.template_version)
        ):
            raise MessagingValidationError(
                "template_version must look like '2026-08-16.1' — a date and a revision"
            )

    def to_dict(self) -> dict[str, str]:
        """The JSON object that reaches the column — present keys only, all values strings."""
        emitted: dict[str, str] = {}
        if self.escalation_reason is not None:
            emitted["escalation_reason"] = self.escalation_reason.value
        if self.template_key is not None:
            emitted["template_key"] = self.template_key
        if self.template_version is not None:
            emitted["template_version"] = self.template_version
        if self.delivery_status is not None:
            emitted["delivery_status"] = self.delivery_status
        if self.delivery_error_code is not None:
            emitted["delivery_error_code"] = self.delivery_error_code.value
        if self.source_message_id is not None:
            emitted["source_message_id"] = str(self.source_message_id)
        return emitted
