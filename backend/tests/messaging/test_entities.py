"""The invariants of `Conversation` and `Message` (R1.4, R3.4, R4.1, R5.2, R5.3, R7.6).

Written before the entity, per `steering/testing.md`: `domain/` is pure Python with a real
invariant to protect, which is exactly where that document asks for test-first.

**Every transition of both tables, valid and invalid** — DoD §28.19 requires the invalid ones,
and they are the half that matters here: R5.4 ("never a second escalation notification while
the conversation is `PENDING_HUMAN`") is enforced by `escalate` refusing any origin but
`NONE`, so a table that quietly accepted a second escalation would break a security-adjacent
promise without any test going red.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.messaging.domain.entities import MAX_MESSAGE_CONTENT_LENGTH, Conversation, Message
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    EscalationReason,
    MessageIntent,
    MessageSenderType,
)
from app.messaging.domain.exceptions import (
    CONVERSATION_NOT_FOUND_MESSAGE,
    ConversationNotFoundError,
    InvalidConversationTransitionError,
    MessagingValidationError,
)
from app.messaging.domain.value_objects import MessageMetadata
from app.messaging.infrastructure.models import ConversationModel

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=5)


def make_conversation(
    *,
    status: ConversationStatus = ConversationStatus.OPEN,
    escalation_status: ConversationEscalationStatus = ConversationEscalationStatus.NONE,
    property_id: uuid.UUID | None = None,
    language: str = "es",
) -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        channel=ConversationChannel.WHATSAPP,
        created_at=NOW,
        updated_at=NOW,
        property_id=property_id or uuid.uuid4(),
        status=status,
        escalation_status=escalation_status,
        language=language,
    )


def make_message(**overrides: object) -> Message:
    kwargs: dict = {
        "id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "sender_type": MessageSenderType.GUEST,
        "content": "What time is check-in?",
        "created_at": NOW,
    }
    kwargs.update(overrides)
    return Message(**kwargs)


# --- Construction (R5.2, D19) -----------------------------------------------------------


def test_conversation_instantiates_with_defaults() -> None:
    conversation = make_conversation()

    assert conversation.status is ConversationStatus.OPEN
    assert conversation.language == "es"
    assert conversation.ai_enabled is True
    assert conversation.escalation_status is ConversationEscalationStatus.NONE


def test_a_conversation_without_a_property_is_refused(
) -> None:
    """D19, and the reason is not tidiness: `TimelineEventFactory` requires `property_id` as
    a non-null UUID, so a conversation without one cannot produce **any** of the four
    timeline events R4.1, R4.4, R4.5 and R5.2 declare mandatory. Refusing the conversation
    is what keeps those four SHALLs from becoming "almost always"."""
    with pytest.raises(MessagingValidationError):
        Conversation(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            channel=ConversationChannel.MANUAL,
            created_at=NOW,
            updated_at=NOW,
        )


def test_the_property_column_stays_nullable() -> None:
    """The other half of D19: the restriction is this change's, not the schema's.

    No migration here. Leaving the column nullable is what does not decide, on behalf of
    `beds24-messaging-adapter`, what to do with a conversation the PMS hands over before its
    property is resolved.
    """
    assert ConversationModel.__table__.c.property_id.nullable is True


# --- escalation_status axis (R5.3, D4) --------------------------------------------------


def test_escalate_moves_both_axes_at_once() -> None:
    conversation = make_conversation()

    conversation.escalate(now=LATER)

    assert conversation.status is ConversationStatus.ESCALATED
    assert conversation.escalation_status is ConversationEscalationStatus.PENDING_HUMAN
    assert conversation.updated_at == LATER


@pytest.mark.parametrize(
    "escalation_status",
    [
        ConversationEscalationStatus.PENDING_HUMAN,
        ConversationEscalationStatus.HUMAN_HANDLING,
        ConversationEscalationStatus.RESOLVED,
    ],
)
def test_escalate_accepts_no_origin_but_none(
    escalation_status: ConversationEscalationStatus,
) -> None:
    """**This is what makes R5.4 true**, and it is why the rule lives here rather than as an
    `if` in the pipeline: a conversation that cannot escalate twice cannot notify twice (D20).
    """
    conversation = make_conversation(
        status=ConversationStatus.ESCALATED, escalation_status=escalation_status
    )

    with pytest.raises(InvalidConversationTransitionError):
        conversation.escalate(now=LATER)


def test_a_refused_escalation_leaves_the_entity_untouched() -> None:
    """R5.3: "comprobarlas **antes** de escribir ningún campo". Both axes move in `escalate`,
    so a check made halfway would leave a conversation `ESCALATED` with no escalation."""
    conversation = make_conversation(
        status=ConversationStatus.ESCALATED,
        escalation_status=ConversationEscalationStatus.PENDING_HUMAN,
    )

    with pytest.raises(InvalidConversationTransitionError):
        conversation.escalate(now=LATER)

    assert conversation.escalation_status is ConversationEscalationStatus.PENDING_HUMAN
    assert conversation.updated_at == NOW


def test_take_over_moves_pending_human_to_human_handling() -> None:
    """D4: answering *is* taking over, which is what gives `HUMAN_HANDLING` a writer at all."""
    conversation = make_conversation(
        status=ConversationStatus.ESCALATED,
        escalation_status=ConversationEscalationStatus.PENDING_HUMAN,
    )

    conversation.take_over(now=LATER)

    assert conversation.escalation_status is ConversationEscalationStatus.HUMAN_HANDLING
    assert conversation.status is ConversationStatus.ESCALATED


@pytest.mark.parametrize(
    "escalation_status",
    [
        ConversationEscalationStatus.NONE,
        ConversationEscalationStatus.HUMAN_HANDLING,
        ConversationEscalationStatus.RESOLVED,
    ],
)
def test_take_over_refuses_every_other_origin(
    escalation_status: ConversationEscalationStatus,
) -> None:
    conversation = make_conversation(escalation_status=escalation_status)

    with pytest.raises(InvalidConversationTransitionError):
        conversation.take_over(now=LATER)


@pytest.mark.parametrize(
    "escalation_status",
    [
        ConversationEscalationStatus.PENDING_HUMAN,
        ConversationEscalationStatus.HUMAN_HANDLING,
    ],
)
def test_resolving_an_escalated_conversation_closes_the_escalation(
    escalation_status: ConversationEscalationStatus,
) -> None:
    """`resolve_escalation` accepts `PENDING_HUMAN` **directly** (D4): a manager may close
    without ever having formally declared she was taking over, and R7.1 gives no route for
    that intermediate step."""
    conversation = make_conversation(
        status=ConversationStatus.ESCALATED, escalation_status=escalation_status
    )

    conversation.resolve(now=LATER)

    assert conversation.status is ConversationStatus.RESOLVED
    assert conversation.escalation_status is ConversationEscalationStatus.RESOLVED


# --- status axis (R5.3, D4) -------------------------------------------------------------


def test_resolve_from_open_leaves_the_escalation_axis_alone() -> None:
    """A conversation that was never escalated has no escalation to resolve."""
    conversation = make_conversation()

    conversation.resolve(now=LATER)

    assert conversation.status is ConversationStatus.RESOLVED
    assert conversation.escalation_status is ConversationEscalationStatus.NONE


@pytest.mark.parametrize(
    "status", [ConversationStatus.RESOLVED, ConversationStatus.CLOSED]
)
def test_resolve_refuses_a_conversation_that_is_already_finished(
    status: ConversationStatus,
) -> None:
    conversation = make_conversation(status=status)

    with pytest.raises(InvalidConversationTransitionError):
        conversation.resolve(now=LATER)


def test_reopen_returns_a_resolved_conversation_to_open() -> None:
    conversation = make_conversation(status=ConversationStatus.RESOLVED)

    conversation.reopen(now=LATER)

    assert conversation.status is ConversationStatus.OPEN


def test_reopening_clears_a_resolved_escalation() -> None:
    """Not in D4's table, and derived from it: `escalate` accepts only `NONE`, so a
    conversation reopened with `escalation_status = RESOLVED` could never be escalated
    again — a guest writing "there is smoke" into a reopened thread would raise instead of
    reaching a human. Reopening restarts the escalation lifecycle, which is the reading that
    keeps R5.1 reachable without widening `escalate`'s origins and thereby breaking R5.4.
    """
    conversation = make_conversation(
        status=ConversationStatus.ESCALATED,
        escalation_status=ConversationEscalationStatus.HUMAN_HANDLING,
    )
    conversation.resolve(now=LATER)

    conversation.reopen(now=LATER)

    assert conversation.escalation_status is ConversationEscalationStatus.NONE
    conversation.escalate(now=LATER)
    assert conversation.escalation_status is ConversationEscalationStatus.PENDING_HUMAN


@pytest.mark.parametrize(
    "status",
    [ConversationStatus.OPEN, ConversationStatus.ESCALATED, ConversationStatus.CLOSED],
)
def test_reopen_refuses_every_origin_but_resolved(status: ConversationStatus) -> None:
    conversation = make_conversation(status=status)

    with pytest.raises(InvalidConversationTransitionError):
        conversation.reopen(now=LATER)


@pytest.mark.parametrize(
    "status", [ConversationStatus.RESOLVED, ConversationStatus.CLOSED]
)
def test_escalate_refuses_a_bad_status_origin_even_when_the_escalation_axis_allows_it(
    status: ConversationStatus,
) -> None:
    """The second half of `escalate`'s guard, which the escalation-axis tests never reach.

    Every other invalid-escalate test supplies a bad `escalation_status`, so the status check
    is unreachable from the suite and a refactor that dropped it would go unnoticed. This is
    a state production reaches: a conversation that was never escalated (`NONE`) and has been
    resolved. DoD §28.19 asks for the invalid transitions of **both** tables.
    """
    conversation = make_conversation(
        status=status, escalation_status=ConversationEscalationStatus.NONE
    )

    with pytest.raises(InvalidConversationTransitionError):
        conversation.escalate(now=LATER)

    assert conversation.escalation_status is ConversationEscalationStatus.NONE
    assert conversation.status is status


def test_closed_is_the_destination_of_no_transition_in_this_change() -> None:
    """D4 states it rather than inventing a route: no operation here produces `CLOSED`.

    Asserted against the table itself rather than by guessing method names — a `finish()`
    that set `CLOSED` would have passed a `hasattr` check while breaking the guarantee.
    """
    destinations = {
        target for _, target in Conversation._STATUS_TRANSITIONS.values()
    }

    assert ConversationStatus.CLOSED not in destinations
    assert destinations == {
        ConversationStatus.ESCALATED,
        ConversationStatus.RESOLVED,
        ConversationStatus.OPEN,
    }


def test_no_operation_can_drive_a_conversation_into_closed() -> None:
    """The behavioural half: drive every operation from every origin and watch the field.

    A method that wrote `status` outside the tables would not show up above.
    """
    operations = ("escalate", "take_over", "resolve", "reopen", "register_message")

    for status in ConversationStatus:
        # A conversation that is already `CLOSED` is not evidence about who *writes* it, and
        # an escape clause inside the assertion would waive more than this line does.
        if status is ConversationStatus.CLOSED:
            continue
        for escalation_status in ConversationEscalationStatus:
            for operation in operations:
                conversation = make_conversation(
                    status=status, escalation_status=escalation_status
                )
                try:
                    getattr(conversation, operation)(now=LATER)
                except InvalidConversationTransitionError:
                    continue
                assert (
                    conversation.status is not ConversationStatus.CLOSED
                ), f"{operation} from {status.value} produced CLOSED"


# --- register_message (R1.4) ------------------------------------------------------------


def test_register_message_updates_the_inbox_ordering_key() -> None:
    """R1.4 exists so the inbox can be ordered without walking `messages`, and D11 puts it
    on the entity rather than a `setattr` from the use case."""
    conversation = make_conversation()

    conversation.register_message(now=LATER)

    assert conversation.last_message_at == LATER
    assert conversation.updated_at == LATER


def test_register_message_moves_the_key_forward_on_every_message() -> None:
    conversation = make_conversation()
    conversation.register_message(now=LATER)

    even_later = LATER + timedelta(minutes=1)
    conversation.register_message(now=even_later)

    assert conversation.last_message_at == even_later


# --- Message (R3.4, R7.6, D21) ----------------------------------------------------------


def test_a_message_keeps_an_intent_that_is_a_member_of_the_enum() -> None:
    message = make_message(intent=MessageIntent.WIFI)

    assert message.intent == MessageIntent.WIFI.value


def test_a_message_keeps_an_intent_given_as_its_own_value() -> None:
    message = make_message(intent="WIFI")

    assert message.intent == MessageIntent.WIFI.value


@pytest.mark.parametrize(
    "intent",
    [
        "REEMBOLSO",
        "wifi",
        "",
        "DROP TABLE messages",
        123,
        # Unhashable, which is what a provider's JSON array arrives as. It must degrade like
        # everything else: raising here would be a second outcome R3.4 never declared.
        ["MAINTENANCE_ISSUE"],
        {"intent": "WIFI"},
    ],
)
def test_an_unrecognised_intent_degrades_to_unknown_and_is_never_stored_as_given(
    intent: object,
) -> None:
    """R3.4. The column is a `VARCHAR(100)` that *looks* like an enum — the same appearance
    that got `webhook_events.event_type` left out of the rule-11 census — so the closed form
    is enforced where the value is built, not where the caller is trusted."""
    message = make_message(intent=intent)

    assert message.intent == MessageIntent.UNKNOWN.value


def test_a_message_without_an_intent_stays_without_one() -> None:
    """A human reply is never classified; `None` is not an unrecognised value."""
    assert make_message(intent=None).intent is None


def test_content_at_the_ceiling_is_accepted() -> None:
    message = make_message(content="a" * MAX_MESSAGE_CONTENT_LENGTH)

    assert len(message.content) == MAX_MESSAGE_CONTENT_LENGTH


def test_content_above_the_ceiling_is_refused() -> None:
    """R7.6 and D21. The Pydantic schema rejects it earlier over HTTP; this is the only
    ceiling a caller without HTTP in front of it — a test, a worker, the pipeline — meets."""
    with pytest.raises(MessagingValidationError):
        make_message(content="a" * (MAX_MESSAGE_CONTENT_LENGTH + 1))


def test_the_ceiling_counts_characters_and_not_bytes() -> None:
    """Pinned because ASCII test data cannot tell the two implementations apart.

    D21's 4000 is a decision about how long a message may be, not a storage limit —
    `messages.content` is `TEXT` with no byte ceiling — so a guest writing accented Spanish
    or an emoji must not get a shorter allowance than one writing ASCII.
    """
    content = "€" * MAX_MESSAGE_CONTENT_LENGTH

    assert len(content.encode("utf-8")) > MAX_MESSAGE_CONTENT_LENGTH
    assert len(make_message(content=content).content) == MAX_MESSAGE_CONTENT_LENGTH


def test_message_instantiates_with_defaults() -> None:
    message = make_message()

    assert message.ai_generated is False
    assert message.sender_user_id is None
    assert message.metadata is None


def test_a_message_is_frozen_so_the_closed_forms_survive_construction() -> None:
    """`messages` is append-only, and freezing is what makes R3.4 total rather than
    construction-only: `message.intent = <raw model output>` is the natural way to write
    "record the classification we just got", and on a mutable dataclass nothing would stop
    free text reaching a `VARCHAR(100)` the census calls closed."""
    message = make_message(intent=MessageIntent.WIFI)

    with pytest.raises(Exception):
        message.intent = "REEMBOLSO"  # type: ignore[misc]
    with pytest.raises(Exception):
        message.content = "a" * (MAX_MESSAGE_CONTENT_LENGTH + 1)  # type: ignore[misc]

    assert message.intent == MessageIntent.WIFI.value


def test_a_message_refuses_a_bare_dict_as_metadata() -> None:
    """R3.5 and D15. The closed key set has to be true of the column, not only of the value
    object nobody is obliged to use."""
    with pytest.raises(MessagingValidationError):
        make_message(metadata={"guest_said": "mi DNI es 12345678Z"})


def test_a_message_accepts_the_metadata_value_object() -> None:
    metadata = MessageMetadata(escalation_reason=EscalationReason.EMERGENCY_KEYWORD)

    assert make_message(metadata=metadata).metadata is metadata


# --- Conversation.language (R4.8) -------------------------------------------------------


@pytest.mark.parametrize("language", ["fr", "ES", "", "es-ES"])
def test_a_message_in_an_unsupported_language_is_refused(language: str) -> None:
    """The third carrier of a language code, and one *we* write — from the outcome of
    `detect_language` (R4.8) — into a `String(5)` column whose name promises a code."""
    with pytest.raises(MessagingValidationError):
        make_message(language=language)


def test_a_message_with_no_detected_language_is_accepted() -> None:
    """`None` is a real value: detection returned nothing and nobody guessed."""
    assert make_message(language=None).language is None


@pytest.mark.parametrize("language", ["fr", "ES", "", "es-ES"])
def test_a_conversation_in_an_unsupported_language_is_refused(language: str) -> None:
    """R4.8 makes this field the fallback when detection cannot decide, so an unsupported
    value has no template to answer from — and it travels to an external AI provider inside
    `ConversationContext`."""
    with pytest.raises(MessagingValidationError):
        make_conversation(language=language)


# --- The not-found error (R1.5) ---------------------------------------------------------


def test_the_not_found_error_has_exactly_one_message() -> None:
    """R1.5 is a promise no call site may break, so it is a property of the type.

    `IncidentNotFoundError` in `maintenance` defaults to a constant and asks callers not to
    override it; a convention is one line away from being broken, and a distinguishable body
    ("belongs to another tenant") is exactly the probe R1.5 closes.
    """
    assert str(ConversationNotFoundError()) == CONVERSATION_NOT_FOUND_MESSAGE

    with pytest.raises(TypeError):
        ConversationNotFoundError("Conversation belongs to another tenant")  # type: ignore[call-arg]
