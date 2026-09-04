"""Every value that crosses a port of `messaging` refuses to be built out of contract.

Constructed **out of contract on purpose**, which is the shape `maintenance` settled on for
`IncidentClassification`: the guarantee has to be a property of the type, because a check
that lives in the one adapter written so far is satisfied by accident and inherited by
nobody. R2.4, R2.1, R3.5, R6.5.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.messaging.domain.enums import (
    ConversationChannel,
    EscalationReason,
    MessageIntent,
)
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.messaging.domain.exceptions import MessagingValidationError
from app.messaging.domain.value_objects import (
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_SENT,
    ChannelErrorCode,
    ChannelSendResult,
    ConversationContext,
    GeneratedResponse,
    InboundMessageActor,
    InboundWhatsAppMessage,
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
    """Four now, not three: `whatsapp-cloud-adapter` R2.3/R2.4 (design D2) adds
    `OUTSIDE_SESSION_WINDOW`, symmetric with `NotificationErrorCode`'s own member of the same
    name."""
    assert tuple(member.name for member in ChannelErrorCode) == (
        "INVALID_RECIPIENT",
        "CHANNEL_INBOUND_ONLY",
        "ADAPTER_UNAVAILABLE",
        "OUTSIDE_SESSION_WINDOW",
    )


# --- `InboundMessageActor` (`guest-portal-messaging` R4.1, D8) ----------------------------

DIGEST = "a" * 64


def test_an_actor_can_be_a_user() -> None:
    actor = InboundMessageActor(user_id=uuid.uuid4(), ip="203.0.113.7")

    assert actor.token_hash is None


def test_an_actor_can_be_a_portal_token_bearer() -> None:
    """The second door R4.1 opens: no `User` exists behind `POST /guest/messages/{token}`."""
    actor = InboundMessageActor(token_hash=DIGEST, ip="203.0.113.7")

    assert actor.user_id is None


def test_an_actor_refuses_to_be_both() -> None:
    """A row claiming a logged-in manager **and** a portal bearer describes something that
    cannot have happened, and `audit_logs` is append-only."""
    with pytest.raises(MessagingValidationError):
        InboundMessageActor(user_id=uuid.uuid4(), token_hash=DIGEST)


def test_an_actor_refuses_to_be_neither() -> None:
    """Never constructible before either, but only by accident of `user_id` being required.
    Widening to a choice is what makes it worth asserting."""
    with pytest.raises(MessagingValidationError):
        InboundMessageActor()


def test_an_actor_is_frozen() -> None:
    actor = InboundMessageActor(token_hash=DIGEST)

    with pytest.raises(Exception):
        actor.user_id = uuid.uuid4()  # type: ignore[misc]


def test_the_refusal_quotes_neither_value() -> None:
    """The module docstring's standing rule, which is unconditional: "**No refusal message
    ever quotes the value it refused.**" `str(exc)` is rendered into a 422 body and into every
    log line. An earlier version of this refusal quoted the `user_id` half while masking the
    digest — the security panel of section 2 pointed out that the rule names no sensitivity
    threshold, so the asymmetry was an undeclared exception to it."""
    user_id = uuid.uuid4()

    with pytest.raises(MessagingValidationError) as raised:
        InboundMessageActor(user_id=user_id, token_hash=DIGEST)

    rendered = str(raised.value)
    assert DIGEST not in rendered
    assert str(user_id) not in rendered


#: `is_guest_token_digest` is `len(value) == 64 and set(value) <= _HEX_DIGITS`, and `and`
#: short-circuits — so a wrong-length value never reaches the character check. The two groups
#: below hit **one branch each**, deliberately: the QA panel of section 2 found that three
#: earlier tests here all tripped the length branch, so deleting the character check outright
#: would have left two of the three green.

#: Right length, wrong alphabet — these reach the character-set branch and nothing else.
NOT_HEX_BUT_SIXTY_FOUR = [
    "A" * 64,          # upper case: `hexdigest()` never emits it, so accepting it would only
                       # widen what a mistake can look like
    "z" + "a" * 63,    # a letter outside `0-9a-f`
    "-" + "a" * 63,    # a base64url character, which is what a real token is made of
]

#: Valid hex, wrong length — these reach the length branch and nothing else.
HEX_BUT_WRONG_LENGTH = ["a" * 63, "a" * 65, "", "abc"]


@pytest.mark.parametrize("value", NOT_HEX_BUT_SIXTY_FOUR)
def test_a_sixty_four_character_value_that_is_not_hex_is_refused(value: str) -> None:
    """The character-set half. Were `set(value) <= _HEX_DIGITS` deleted from the predicate,
    only these would go red."""
    with pytest.raises(MessagingValidationError):
        InboundMessageActor(token_hash=value)


@pytest.mark.parametrize("value", HEX_BUT_WRONG_LENGTH)
def test_a_hex_value_of_the_wrong_length_is_refused(value: str) -> None:
    """The length half, with the alphabet deliberately valid so nothing else can be doing the
    refusing."""
    with pytest.raises(MessagingValidationError):
        InboundMessageActor(token_hash=value)


def test_a_real_portal_token_is_refused_in_place_of_its_digest() -> None:
    """The mistake this predicate exists to stop: a caller passing the token itself.

    Built with the real generator rather than a hand-typed lookalike — `secrets.token_urlsafe(
    TOKEN_ENTROPY_BYTES)`, 43 base64url characters — because the value that matters is the one
    the system actually mints. An earlier version of this test used `"Zk3" * 20`, which is 60
    characters and shaped like nothing; it refused on length and proved nothing about tokens.
    """
    token = generate_guest_token()

    with pytest.raises(MessagingValidationError):
        InboundMessageActor(token_hash=token)

    # And the digest of that same token is accepted, so the test is about the *shape* rather
    # than about this particular string being unlucky.
    assert InboundMessageActor(token_hash=hash_guest_token(token)).user_id is None


def test_the_digest_refusal_quotes_neither_the_token_nor_the_value() -> None:
    """The module's standing rule applies to this branch too, and it was unpinned: the sibling
    refusal had exactly this bug and was fixed this round, so a future edit re-introducing
    `{self.token_hash!r}` here would have left the suite green while pushing a portal token
    into a 422 body and every log line."""
    token = generate_guest_token()

    with pytest.raises(MessagingValidationError) as raised:
        InboundMessageActor(token_hash=token)

    assert token not in str(raised.value)


def test_the_actor_carries_exactly_four_fields() -> None:
    """R4.1 names the actor and where it acted from, and nothing else. A fifth field here is
    a fifth thing that could reach `audit_logs` without passing `AuditLogFactory`.

    Four rather than three since `whatsapp-cloud-adapter` D6 added the webhook's identity;
    the count is pinned so a fourth *identity* cannot arrive without this test being read.
    """
    assert set(InboundMessageActor.__dataclass_fields__) == {
        "user_id",
        "token_hash",
        "resolved_phone",
        "ip",
    }


# --- `InboundMessageActor.resolved_phone` (`whatsapp-cloud-adapter` R4.2, D6) --------------

PHONE = "+34612345678"


def test_an_actor_can_be_a_resolved_phone_number() -> None:
    """The third door: a WhatsApp webhook has no `User` and no portal link behind it, only the
    E.164 number `PostWhatsAppInboundMessageUseCase` normalised (D6)."""
    actor = InboundMessageActor(resolved_phone=PHONE)

    assert actor.resolved_phone == PHONE
    assert actor.user_id is None
    assert actor.token_hash is None


def test_a_resolved_phone_actor_may_still_carry_an_ip() -> None:
    """`ip` says where, not who: it is outside the "exactly one" invariant for every identity,
    which is what makes the count in `__post_init__` a count of three and not of four."""
    actor = InboundMessageActor(resolved_phone=PHONE, ip="203.0.113.7")

    assert actor.ip == "203.0.113.7"


#: Every way of naming more than one actor, exhaustively — the three pairs and the triple.
#: Pairwise, three identities have three pairs, and an `if` chain that checks only two of them
#: leaves a real combination constructible; D6's invariant is "exactly one", so all four
#: shapes are pinned rather than the two an old two-field check happened to cover.
MORE_THAN_ONE_ACTOR = [
    {"user_id": uuid.uuid4(), "token_hash": DIGEST},
    {"user_id": uuid.uuid4(), "resolved_phone": PHONE},
    {"token_hash": DIGEST, "resolved_phone": PHONE},
    {"user_id": uuid.uuid4(), "token_hash": DIGEST, "resolved_phone": PHONE},
]


@pytest.mark.parametrize("kwargs", MORE_THAN_ONE_ACTOR)
def test_an_actor_refuses_to_name_more_than_one_identity(kwargs: dict[str, object]) -> None:
    with pytest.raises(MessagingValidationError):
        InboundMessageActor(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_a_blank_resolved_phone_names_nobody_and_is_refused(value: str) -> None:
    """A blank string is not `None`, so the count reads it as an identity while it names
    nobody — the one shape that could make "exactly one" true and empty at once."""
    with pytest.raises(MessagingValidationError):
        InboundMessageActor(resolved_phone=value)


def test_the_multiple_identity_refusal_quotes_no_value() -> None:
    """The module's standing rule reaches the third identity too: a guest's phone number in a
    422 body or a log line is exactly the leak rule 11 of `steering/security.md` forbids."""
    user_id = uuid.uuid4()

    with pytest.raises(MessagingValidationError) as raised:
        InboundMessageActor(user_id=user_id, resolved_phone=PHONE)

    rendered = str(raised.value)
    assert PHONE not in rendered
    assert str(user_id) not in rendered


def test_a_resolved_phone_is_not_checked_against_the_digest_predicate() -> None:
    """D6: "not a token, so no digest-shape check applies to it". An E.164 number is 12
    characters and not hex; were `is_guest_token_digest` applied to this field, every real
    WhatsApp message would be refused at construction."""
    assert InboundMessageActor(resolved_phone=PHONE).resolved_phone == PHONE


# --- InboundWhatsAppMessage (`whatsapp-cloud-adapter` R3.5, R4.1; design D9) ---------------

RECEIVED_AT = datetime(2023, 11, 14, 22, 13, 19, tzinfo=UTC)
GUEST_WORDS = "Hola, tengo una pregunta sobre el check-in"
GUEST_PHONE = "34600111222"


def make_inbound(**overrides: object) -> InboundWhatsAppMessage:
    fields: dict[str, object] = {
        "sender_phone": GUEST_PHONE,
        "provider_message_id": "wamid.HBgLMzQ2MDAxMTEyMjI",
        "text": GUEST_WORDS,
        "received_at": RECEIVED_AT,
        "business_phone_number": "1234567890",
    }
    fields.update(overrides)
    return InboundWhatsAppMessage(**fields)  # type: ignore[arg-type]


def test_an_inbound_whatsapp_message_of_the_expected_shape_is_accepted() -> None:
    """The guard on the negatives below: without it a class that refused *everything* would
    make every refusal test pass and the type would be unusable."""
    message = make_inbound()

    assert message.sender_phone == GUEST_PHONE
    assert message.text == GUEST_WORDS
    assert message.received_at == RECEIVED_AT


@pytest.mark.parametrize(
    "field",
    ["sender_phone", "provider_message_id", "text", "business_phone_number"],
)
@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_no_string_field_of_an_inbound_message_may_be_blank(field: str, blank: str) -> None:
    """Whitespace counts as blank, which is the part a `if not value` check would miss.

    `provider_message_id` is the one that matters most: R3.5 deduplicates a provider's
    delivery retry on it, so an empty id would collapse every distinct message onto the same
    key — a missing field turning into silent data loss instead of a loud refusal.
    """
    with pytest.raises(MessagingValidationError):
        make_inbound(**{field: blank})


def test_an_inbound_message_refuses_a_naive_timestamp() -> None:
    """`received_at` is compared against the 24h session window (design D2), where a naive
    datetime is a `TypeError` from inside an adapter rather than an answer. The same guard
    `Incident.eta_at` carries."""
    with pytest.raises(MessagingValidationError):
        make_inbound(received_at=datetime(2023, 11, 14, 22, 13, 19))


def test_an_inbound_message_accepts_an_aware_timestamp_in_any_zone() -> None:
    """Aware is the contract, not UTC specifically: `parse` builds UTC, and a future provider
    adapter may hand over an offset."""
    from datetime import timedelta, timezone

    madrid = timezone(timedelta(hours=2))
    assert make_inbound(received_at=RECEIVED_AT.astimezone(madrid)).received_at == RECEIVED_AT


def test_the_inbound_message_refusals_quote_neither_the_words_nor_the_number() -> None:
    """The module's standing rule, over the field that carries the guest's message.

    `api/errors.py` renders `str(exc)` into a 422 body and every log line, and this value
    object is built from an unauthenticated webhook — so a refusal that interpolated its own
    input would push the guest's text into both.
    """
    for field in ("sender_phone", "provider_message_id", "business_phone_number"):
        with pytest.raises(MessagingValidationError) as raised:
            make_inbound(**{field: " "}, text=GUEST_WORDS)
        assert GUEST_WORDS not in str(raised.value)
        assert GUEST_PHONE not in str(raised.value)

    with pytest.raises(MessagingValidationError) as raised:
        make_inbound(text=" ")
    assert GUEST_PHONE not in str(raised.value)


def test_an_inbound_message_text_over_the_ceiling_is_truncated_not_refused() -> None:
    """4000 mirrors `Message.MAX_MESSAGE_CONTENT_LENGTH`, but unlike that constructor this one
    truncates rather than raises: Meta redelivers on any non-2xx, and a refusal here would
    retry forever without ever becoming the row R3.5 deduplicates on."""
    message = make_inbound(text="a" * 4001)

    assert len(message.text) == 4000
    assert message.text == "a" * 4000


def test_an_inbound_message_text_at_the_ceiling_is_untouched() -> None:
    message = make_inbound(text="a" * 4000)

    assert message.text == "a" * 4000


def test_an_inbound_message_is_frozen() -> None:
    """It crosses a port and is read by the receiving use case, the deduplication check and
    the pipeline; a mutable one lets any of them rewrite what the guest said."""
    message = make_inbound()

    with pytest.raises(Exception):
        message.text = "something else"  # type: ignore[misc]


def test_the_inbound_message_carries_exactly_the_five_fields_of_the_design() -> None:
    """D9 lists them. A sixth would be a provider detail crossing the boundary this value
    object exists to be — `type`, `wa_id`, the contact's profile name, the raw payload."""
    assert set(InboundWhatsAppMessage.__dataclass_fields__) == {
        "sender_phone",
        "provider_message_id",
        "text",
        "received_at",
        "business_phone_number",
    }
