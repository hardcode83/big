"""Every value that crosses a port of `messaging` refuses to be built out of contract.

Constructed **out of contract on purpose**, which is the shape `maintenance` settled on for
`IncidentClassification`: the guarantee has to be a property of the type, because a check
that lives in the one adapter written so far is satisfied by accident and inherited by
nobody. R2.4, R2.1, R3.5, R6.5.
"""

import uuid
from decimal import Decimal

import pytest

from app.messaging.domain.enums import (
    ConversationChannel,
    EscalationReason,
    MessageIntent,
)
from app.messaging.domain.exceptions import MessagingValidationError
from app.messaging.domain.value_objects import (
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_SENT,
    ChannelErrorCode,
    ChannelSendResult,
    ConversationContext,
    GeneratedResponse,
    MessageClassification,
    MessageMetadata,
)

VOCABULARY = frozenset({"Check-in is from 15:00.", "El check-in es a partir de las 15:00."})


def make_response(content: str = "Check-in is from 15:00.", language: str = "en") -> GeneratedResponse:
    return GeneratedResponse(
        content=content,
        language=language,
        template_key=f"{MessageIntent.CHECKIN_INSTRUCTIONS.value}:{language}",
        vocabulary=VOCABULARY,
    )


def make_context(
    *, language: str = "es", guest_message_count: int = 3
) -> ConversationContext:
    return ConversationContext(
        conversation_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        reservation_id=None,
        channel=ConversationChannel.WHATSAPP,
        language=language,
        ai_enabled=True,
        guest_message_count=guest_message_count,
    )


# --- MessageClassification (R2.4) -------------------------------------------------------


@pytest.mark.parametrize("confidence", ["0", "0.5", "0.75", "1"])
def test_confidence_within_the_unit_interval_is_accepted(confidence: str) -> None:
    classification = MessageClassification(
        intent=MessageIntent.WIFI, confidence=Decimal(confidence)
    )

    assert classification.confidence == Decimal(confidence)


@pytest.mark.parametrize("confidence", ["-0.01", "1.01", "80", "-1"])
def test_confidence_outside_the_unit_interval_is_refused(confidence: str) -> None:
    """It is compared against `TenantConfig.ai_confidence_threshold`, a 0..1 fraction (R4.2).

    A percentage (`80`) would never be strictly below any threshold, so every message would
    be answered automatically by an adapter that meant the opposite.
    """
    with pytest.raises(MessagingValidationError):
        MessageClassification(intent=MessageIntent.WIFI, confidence=Decimal(confidence))


def test_an_intent_outside_the_enum_is_refused() -> None:
    """`messages.intent` is a `VARCHAR(100)` that looks like an enum (R3.4, D16)."""
    with pytest.raises(MessagingValidationError):
        MessageClassification(intent="WIFI", confidence=Decimal("0.8"))  # type: ignore[arg-type]


def test_classification_is_frozen() -> None:
    classification = MessageClassification(
        intent=MessageIntent.WIFI, confidence=Decimal("0.8")
    )

    with pytest.raises(Exception):
        classification.intent = MessageIntent.EMERGENCY  # type: ignore[misc]


def test_classification_carries_no_escalation_verdict() -> None:
    """D10: the policy is the system's, never the adapter's — the field must not exist."""
    assert "requires_escalation" not in MessageClassification.__dataclass_fields__


# --- GeneratedResponse (R2.4, R3.3) -----------------------------------------------------


def test_a_response_inside_its_declared_vocabulary_is_accepted() -> None:
    assert make_response().content in VOCABULARY


def test_a_response_outside_its_declared_vocabulary_is_refused() -> None:
    """The mechanism of R3.3: what reaches `messages.content` from *our* writer is literally
    a member of the catalogue, so guest text has nowhere to ride in."""
    with pytest.raises(MessagingValidationError):
        make_response(content="Claro, le devolvemos los 250 EUR de su reserva.")


def test_an_adapter_must_declare_some_vocabulary() -> None:
    """An empty set would satisfy "declare the closed set" while constraining nothing."""
    with pytest.raises(MessagingValidationError):
        GeneratedResponse(
            content="Check-in is from 15:00.",
            language="en",
            template_key="CHECKIN_INSTRUCTIONS:en",
            vocabulary=frozenset(),
        )


@pytest.mark.parametrize("template_key", ["CHECKIN_INSTRUCTIONS", "REEMBOLSO:en", "en"])
def test_a_response_with_a_template_key_that_is_not_one_is_refused(
    template_key: str,
) -> None:
    """The key is persisted into `messages.metadata`, so it has to be an identifier rather
    than a promise of one."""
    with pytest.raises(MessagingValidationError):
        GeneratedResponse(
            content="Check-in is from 15:00.",
            language="en",
            template_key=template_key,
            vocabulary=VOCABULARY,
        )


@pytest.mark.parametrize("language", ["fr", "ES", "", "es-ES"])
def test_a_response_in_an_unsupported_language_is_refused(language: str) -> None:
    """`SUPPORTED_LANGUAGES` is the set of locales `frontend/locales/` actually renders."""
    with pytest.raises(MessagingValidationError):
        GeneratedResponse(
            content="Check-in is from 15:00.",
            language=language,
            template_key=f"CHECKIN_INSTRUCTIONS:{language}",
            vocabulary=VOCABULARY,
        )


# --- ConversationContext (R2.1) ---------------------------------------------------------


def test_context_carries_only_identifiers_and_closed_values() -> None:
    """The object is handed to something that tomorrow is an external provider (D6).

    Asserted as an exact field set rather than as "does not contain X": a field added later
    has to be added here too, which is the review a widening of this contract deserves.
    """
    assert set(ConversationContext.__dataclass_fields__) == {
        "conversation_id",
        "property_id",
        "reservation_id",
        "channel",
        "language",
        "ai_enabled",
        "guest_message_count",
    }


def test_context_has_no_free_text_field() -> None:
    """No message history, no guest name, no notes — nothing anybody typed."""
    free_text = {"content", "history", "messages", "guest_name", "notes", "subject", "body"}

    assert free_text.isdisjoint(ConversationContext.__dataclass_fields__)


@pytest.mark.parametrize("language", ["fr", "ES", "", "es-ES"])
def test_context_refuses_an_unsupported_language(language: str) -> None:
    """The one field of the seven that its type does not close. Without this the
    "identifiers and closed values only" claim would hold for the field list and not for the
    values, and whatever string a conversation row carried would ship to an external
    provider with its own logging."""
    with pytest.raises(MessagingValidationError):
        make_context(language=language)


def test_context_refuses_a_negative_message_count() -> None:
    with pytest.raises(MessagingValidationError):
        make_context(guest_message_count=-1)


def test_context_is_frozen() -> None:
    context = make_context()

    with pytest.raises(Exception):
        context.language = "en"  # type: ignore[misc]


# --- MessageMetadata (R3.5) -------------------------------------------------------------


def test_metadata_declares_the_six_closed_keys_of_the_design() -> None:
    assert set(MessageMetadata.__dataclass_fields__) == {
        "escalation_reason",
        "template_key",
        "template_version",
        "delivery_status",
        "delivery_error_code",
        "source_message_id",
    }


SOURCE_MESSAGE_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("escalation_reason", EscalationReason.EMERGENCY_KEYWORD, "EMERGENCY_KEYWORD"),
        ("template_key", "WIFI:es", "WIFI:es"),
        ("template_version", "2026-08-16.1", "2026-08-16.1"),
        ("delivery_status", DELIVERY_STATUS_SENT, "SENT"),
        ("delivery_error_code", ChannelErrorCode.INVALID_RECIPIENT, "INVALID_RECIPIENT"),
        ("source_message_id", SOURCE_MESSAGE_ID, str(SOURCE_MESSAGE_ID)),
    ],
)
def test_metadata_emits_each_key_alone_and_no_other(
    field: str, value: object, expected: str
) -> None:
    """One key at a time, so a bug in a single key's emission has nowhere to hide behind the
    all-set and one-set cases."""
    assert MessageMetadata(**{field: value}).to_dict() == {field: expected}


def test_metadata_of_a_message_with_nothing_to_say_emits_nothing() -> None:
    assert MessageMetadata().to_dict() == {}


def test_metadata_emits_every_key_when_every_key_is_set() -> None:
    source_id = uuid.uuid4()
    metadata = MessageMetadata(
        escalation_reason=EscalationReason.DELIVERY_FAILED,
        template_key="WIFI:es",
        template_version="2026-08-16.1",
        delivery_status=DELIVERY_STATUS_FAILED,
        delivery_error_code=ChannelErrorCode.INVALID_RECIPIENT,
        source_message_id=source_id,
    )

    assert metadata.to_dict() == {
        "escalation_reason": "DELIVERY_FAILED",
        "template_key": "WIFI:es",
        "template_version": "2026-08-16.1",
        "delivery_status": "FAILED",
        "delivery_error_code": "INVALID_RECIPIENT",
        "source_message_id": str(source_id),
    }


def test_metadata_accepts_no_arbitrary_key() -> None:
    """The mechanism of `ChangeSet`, applied to the column next door: a use case written
    next year has no signature through which to pass the guest's words (D15)."""
    with pytest.raises(TypeError):
        MessageMetadata(guest_said="mi DNI es 12345678Z")  # type: ignore[call-arg]


@pytest.mark.parametrize("status", ["sent", "DELIVERED", "PENDING", ""])
def test_metadata_refuses_a_delivery_status_outside_the_closed_pair(status: str) -> None:
    with pytest.raises(MessagingValidationError):
        MessageMetadata(delivery_status=status)


@pytest.mark.parametrize(
    "template_key",
    ["WIFI", "WIFI:fr", "REEMBOLSO:es", "wifi:es", "", ":es", "WIFI:", "mi DNI es 12345678Z"],
)
def test_metadata_refuses_a_template_key_that_is_not_one(template_key: str) -> None:
    """The precedent is the column next door: `steering/security.md` records that
    `incidents.ai_classification`'s one non-enum key "degrada a `UNKNOWN_CLASSIFIER` si no es
    un identificador de Python", because a key that merely *looks* like an identifier is the
    hole a rule-11 sink gets censused for."""
    with pytest.raises(MessagingValidationError):
        MessageMetadata(template_key=template_key)


@pytest.mark.parametrize(
    "template_version",
    [
        "latest",
        "1",
        "2026-08-16",
        "v2026-08-16.1",
        "",
        # `$` in a regex also matches just before a trailing newline, so a `match` would let
        # this through. A closed form that admits a trailing newline is not closed.
        "2026-08-16.1\n",
    ],
)
def test_metadata_refuses_a_template_version_that_is_not_one(
    template_version: str,
) -> None:
    with pytest.raises(MessagingValidationError):
        MessageMetadata(template_version=template_version)


def test_metadata_refuses_a_raw_string_where_an_enum_belongs() -> None:
    with pytest.raises(MessagingValidationError):
        MessageMetadata(escalation_reason="EMERGENCY_KEYWORD")  # type: ignore[arg-type]
    with pytest.raises(MessagingValidationError):
        MessageMetadata(
            delivery_status=DELIVERY_STATUS_FAILED,
            delivery_error_code="INVALID_RECIPIENT",  # type: ignore[arg-type]
        )


def test_metadata_of_a_delivered_message_is_the_sent_constant() -> None:
    assert MessageMetadata(delivery_status=DELIVERY_STATUS_SENT).to_dict() == {
        "delivery_status": "SENT"
    }


# --- ChannelSendResult (R6.5) -----------------------------------------------------------


def test_a_delivered_result_carries_no_error_code() -> None:
    assert ChannelSendResult.ok() == ChannelSendResult(delivered=True, error_code=None)


def test_a_failed_result_names_its_code() -> None:
    result = ChannelSendResult.failure(ChannelErrorCode.CHANNEL_INBOUND_ONLY)

    assert result.delivered is False
    assert result.error_code is ChannelErrorCode.CHANNEL_INBOUND_ONLY


def test_a_result_cannot_be_both_delivered_and_failed() -> None:
    with pytest.raises(MessagingValidationError):
        ChannelSendResult(delivered=True, error_code=ChannelErrorCode.ADAPTER_UNAVAILABLE)


def test_a_failure_without_a_reason_is_refused() -> None:
    with pytest.raises(MessagingValidationError):
        ChannelSendResult(delivered=False)


def test_the_result_has_no_string_field() -> None:
    """R6.5 says the failure is recorded "código y campo, nunca el cuerpo". The body cannot
    be carried because there is nowhere to carry it."""
    assert set(ChannelSendResult.__dataclass_fields__) == {"delivered", "error_code"}


def test_channel_error_codes_are_the_three_of_the_design() -> None:
    assert tuple(member.name for member in ChannelErrorCode) == (
        "INVALID_RECIPIENT",
        "CHANNEL_INBOUND_ONLY",
        "ADAPTER_UNAVAILABLE",
    )
