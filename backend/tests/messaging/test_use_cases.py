"""The pipeline of D11 and its siblings, against fakes of the ports (R4, R5, R6, R7).

`steering/backend-architecture.md`: "`application/`: unit tests con **fakes** en memoria de
los puertos". The repositories are exercised against a real Postgres in
`test_repositories.py`; what is under test here is the **order** — which is all a use case is
allowed to contain.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.auth.domain.enums import UserRole, UserStatus
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.guests.domain.value_objects import GuestSummary
from app.messaging.application.use_cases import (
    SENDER_TYPE_BY_ROLE,
    CreateConversationUseCase,
    EscalateConversationUseCase,
    GetConversationUseCase,
    ListConversationsUseCase,
    ListMessagesUseCase,
    ProcessInboundGuestMessageUseCase,
    RecordHumanReplyUseCase,
    ResolveConversationUseCase,
)
from app.messaging.domain.entities import Conversation, Message
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    EscalationReason,
    MessageIntent,
    MessageSenderType,
)
from app.messaging.domain.exceptions import (
    ConversationClosedError,
    ConversationNotFoundError,
    InvalidConversationTransitionError,
    MessagingValidationError,
    PMSChannelUnavailableError,
)
from app.messaging.domain.repositories import ConversationFilters
from app.messaging.domain.templates import (
    INCIDENT_TITLES,
    RESPONSE_TEMPLATES,
    RESPONSE_VOCABULARY,
    TEMPLATE_CATALOGUE_VERSION,
)
from app.messaging.domain.value_objects import (
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_SENT,
    ChannelErrorCode,
    ChannelSendResult,
)
from app.notifications.domain.enums import NotificationType
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from tests.messaging.fakes import (
    FakeConversationRepository,
    FakeGuestRepository,
    FakeIncidentReportingPort,
    FakeMessageRepository,
    FakeNotificationRepository,
    FakeOutboundAdapter,
    FakePropertyRepository,
    FakeReservationRepository,
    FakeTenantConfigRepository,
    FakeTimelineRepository,
    FakeUnitOfWork,
    FakeUserRepository,
    StubAIAdapter,
    make_user,
)

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
PROPERTY = uuid.uuid4()
ACTOR = uuid.uuid4()
IP = "203.0.113.10"

GUEST_MESSAGE = "El wifi no funciona"


def make_conversation(
    *,
    channel: ConversationChannel = ConversationChannel.MANUAL,
    status: ConversationStatus = ConversationStatus.OPEN,
    escalation_status: ConversationEscalationStatus = ConversationEscalationStatus.NONE,
    ai_enabled: bool = True,
    guest_id: uuid.UUID | None = None,
    language: str = "es",
) -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        channel=channel,
        created_at=NOW,
        updated_at=NOW,
        property_id=PROPERTY,
        guest_id=guest_id,
        status=status,
        escalation_status=escalation_status,
        ai_enabled=ai_enabled,
        language=language,
    )


class Harness:
    """The pipeline with every port faked, plus the handles a test asserts on."""

    def __init__(
        self,
        conversation: Conversation,
        *,
        ai: StubAIAdapter | None = None,
        adapter: FakeOutboundAdapter | None = None,
        threshold: Decimal = Decimal("0.75"),
        users: FakeUserRepository | None = None,
        guests: FakeGuestRepository | None = None,
        channels: dict | None = None,
        configs: FakeTenantConfigRepository | None = None,
    ) -> None:
        self.conversation = conversation
        self.conversations = FakeConversationRepository(conversation)
        self.messages = FakeMessageRepository()
        self.messages.known_conversations.add(conversation.id)
        self.ai = ai or StubAIAdapter()
        self.adapter = adapter or FakeOutboundAdapter()
        self.channels = (
            channels if channels is not None else {conversation.channel: self.adapter}
        )
        self.incidents = FakeIncidentReportingPort()
        self.timeline = FakeTimelineRepository()
        self.notifications = FakeNotificationRepository()
        self.users = users or FakeUserRepository(make_user(TENANT))
        self.guests = guests or FakeGuestRepository()
        self.uow = FakeUnitOfWork()
        self.use_case = ProcessInboundGuestMessageUseCase(
            conversations=self.conversations,
            messages=self.messages,
            ai=self.ai,
            channels=self.channels,
            incidents=self.incidents,
            timeline=self.timeline,
            notifications=self.notifications,
            users=self.users,
            guests=self.guests,
            configs=configs or FakeTenantConfigRepository(threshold=threshold),
            properties=FakePropertyRepository(),
            reservations=FakeReservationRepository(),
            uow=self.uow,
        )

    async def run(self, content: str = GUEST_MESSAGE, *, now: datetime = NOW) -> Message:
        return await self.use_case.execute(
            tenant_id=TENANT,
            conversation_id=self.conversation.id,
            content=content,
            actor_user_id=ACTOR,
            ip=IP,
            now=now,
        )


# --- Step 1: resolving the conversation (R1.5, D4, D11) ----------------------------------


@pytest.mark.asyncio
async def test_an_unknown_conversation_is_a_not_found_error() -> None:
    harness = Harness(make_conversation())

    with pytest.raises(ConversationNotFoundError):
        await harness.use_case.execute(
            tenant_id=TENANT,
            conversation_id=uuid.uuid4(),
            content=GUEST_MESSAGE,
            actor_user_id=ACTOR,
            ip=IP,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_a_closed_conversation_refuses_the_message() -> None:
    """D4 gives `CLOSED` no writer in this change and no way back out of it."""
    harness = Harness(make_conversation(status=ConversationStatus.CLOSED))

    with pytest.raises(ConversationClosedError):
        await harness.run()

    assert harness.messages.rows == []
    assert harness.uow.commits == 0


@pytest.mark.asyncio
async def test_a_resolved_conversation_is_reopened_by_the_message() -> None:
    """A guest writing again has, by writing, made it unresolved (D11 step 1)."""
    harness = Harness(make_conversation(status=ConversationStatus.RESOLVED))

    await harness.run()

    assert harness.conversation.status is ConversationStatus.OPEN


# --- Steps 2-5: language, classification, persistence, timeline (R4.1, R4.8, R1.4) -------


@pytest.mark.asyncio
async def test_the_guest_message_is_persisted_with_its_language_and_intent() -> None:
    harness = Harness(make_conversation())

    message = await harness.run()

    assert message.sender_type is MessageSenderType.GUEST
    assert message.content == GUEST_MESSAGE
    assert message.language == "es"
    assert message.intent == MessageIntent.WIFI.value
    assert harness.messages.rows[0] is message


@pytest.mark.asyncio
async def test_an_undetectable_language_falls_back_to_the_conversations(
) -> None:
    """R4.8: "IF no puede decidirlo, THEN SHALL usar `Conversation.language`"."""
    harness = Harness(make_conversation(language="en"))

    message = await harness.run("wifi")

    assert message.language == "en"


@pytest.mark.asyncio
async def test_the_inbox_ordering_key_moves_with_the_message() -> None:
    """R1.4, so the inbox can be ordered without walking `messages`."""
    harness = Harness(make_conversation())

    await harness.run(now=NOW + timedelta(minutes=5))

    assert harness.conversation.last_message_at == NOW + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_the_guest_message_produces_its_timeline_event() -> None:
    harness = Harness(make_conversation())

    message = await harness.run()

    events = harness.timeline.of_type(TimelineEventType.GUEST_MESSAGE_RECEIVED)
    assert len(events) == 1
    assert events[0].actor_type is TimelineActorType.GUEST
    assert events[0].actor_user_id is None
    assert events[0].metadata["message_id"] == str(message.id)
    assert events[0].metadata["intent"] == MessageIntent.WIFI.value


@pytest.mark.asyncio
async def test_no_timeline_event_carries_the_guests_words(
) -> None:
    """R3.6: "NEVER SHALL copiar el contenido del mensaje a `timeline_events`"."""
    secret = "mi DNI es 12345678Z"
    harness = Harness(make_conversation())

    await harness.run(f"El wifi no funciona, {secret}")

    for event in harness.timeline.events:
        assert secret not in event.title
        assert secret not in str(event.metadata)
        assert event.description is None


# --- Step 9: one transaction, one commit (R4.7) ------------------------------------------


@pytest.mark.asyncio
async def test_the_whole_pipeline_commits_exactly_once() -> None:
    harness = Harness(make_conversation())

    await harness.run()

    assert harness.uow.commits == 1


@pytest.mark.asyncio
async def test_a_failure_midway_commits_nothing() -> None:
    """R4.7: "un fallo no deje el mensaje persistido sin evento de timeline ni la conversación
    escalada sin notificación".

    The channel is missing from the registry, so the reply raises after the guest's message
    has been recorded in the session. Nothing is committed, so the transaction the caller
    rolls back takes all of it — which is the guarantee, rather than the use case having to
    undo its own work.
    """
    harness = Harness(
        make_conversation(channel=ConversationChannel.AIRBNB_MSG), channels={}
    )

    with pytest.raises(PMSChannelUnavailableError):
        await harness.run()

    assert harness.uow.commits == 0


# --- Step 6: the threshold and `ai_enabled` (R4.2, R4.3) ---------------------------------


@pytest.mark.asyncio
async def test_confidence_below_the_threshold_escalates_and_never_replies() -> None:
    harness = Harness(
        make_conversation(), ai=StubAIAdapter(confidence=Decimal("0.74"))
    )

    await harness.run()

    assert harness.conversation.status is ConversationStatus.ESCALATED
    assert harness.ai.generate_calls == []


@pytest.mark.asyncio
async def test_confidence_equal_to_the_threshold_replies() -> None:
    """R4.2 fixes the comparison as **strictly** less than, the same edge as
    `Incident.classify`, so the two capabilities do not diverge on the boundary."""
    harness = Harness(
        make_conversation(), ai=StubAIAdapter(confidence=Decimal("0.75"))
    )

    await harness.run()

    assert harness.conversation.status is ConversationStatus.OPEN
    assert harness.ai.generate_calls == [MessageIntent.WIFI]


@pytest.mark.asyncio
async def test_confidence_above_the_threshold_replies() -> None:
    harness = Harness(make_conversation(), ai=StubAIAdapter(confidence=Decimal("0.99")))

    await harness.run()

    assert harness.ai.generate_calls == [MessageIntent.WIFI]


@pytest.mark.asyncio
async def test_disabling_the_ai_stops_the_reply_and_nothing_else() -> None:
    """R4.3 and D11: with `ai_enabled = false` steps 1-6 and 8 still run — the message is
    recorded, classified and put on the timeline — and step 7b never does."""
    harness = Harness(make_conversation(ai_enabled=False))

    message = await harness.run()

    assert message.intent == MessageIntent.WIFI.value
    assert harness.timeline.of_type(TimelineEventType.GUEST_MESSAGE_RECEIVED)
    assert harness.ai.generate_calls == []
    assert harness.messages.by_sender(MessageSenderType.AI) == []


@pytest.mark.asyncio
async def test_disabling_the_ai_does_not_disable_the_escalation() -> None:
    """D11 says it in words and this pins it: "apagar la IA apaga la respuesta automática, no
    el aviso de que hay una emergencia"."""
    harness = Harness(
        make_conversation(ai_enabled=False),
        ai=StubAIAdapter(intent=MessageIntent.EMERGENCY),
    )

    await harness.run()

    assert harness.conversation.status is ConversationStatus.ESCALATED
    assert len(harness.notifications.rows) == 1


# --- Step 7b: the automatic reply (R4.4, R2.7, R3.3) -------------------------------------


@pytest.mark.asyncio
async def test_the_reply_is_persisted_with_everything_r4_4_asks_for() -> None:
    harness = Harness(make_conversation())

    source = await harness.run()

    replies = harness.messages.by_sender(MessageSenderType.AI)
    assert len(replies) == 1
    reply = replies[0]
    assert reply.ai_generated is True
    assert reply.confidence_score == Decimal("0.80")
    assert reply.intent == MessageIntent.WIFI.value
    assert reply.content == RESPONSE_TEMPLATES[(MessageIntent.WIFI, "es")]
    assert reply.metadata.template_key == "WIFI:es"
    assert reply.metadata.template_version == TEMPLATE_CATALOGUE_VERSION
    assert reply.metadata.source_message_id == source.id
    assert reply.metadata.delivery_status == DELIVERY_STATUS_SENT


@pytest.mark.asyncio
async def test_the_reply_produces_its_timeline_event() -> None:
    harness = Harness(make_conversation())

    await harness.run()

    events = harness.timeline.of_type(TimelineEventType.AI_RESPONSE_SENT)
    assert len(events) == 1
    assert events[0].actor_type is TimelineActorType.AI
    assert events[0].metadata["template_key"] == "WIFI:es"


@pytest.mark.asyncio
async def test_what_reaches_the_content_column_is_a_catalogue_constant() -> None:
    """R3.3: the closed form of `messages.content` when the writer is ours."""
    harness = Harness(make_conversation())

    await harness.run()

    assert harness.messages.by_sender(MessageSenderType.AI)[0].content in RESPONSE_VOCABULARY


@pytest.mark.asyncio
async def test_a_reply_outside_the_catalogue_is_refused_however_the_adapter_declares_it(
) -> None:
    """**The check that makes R3.3 hold for an adapter we did not write.**

    `GeneratedResponse` only refuses content outside the vocabulary *the adapter declares*,
    and `steering/security.md` records that an adapter can satisfy that trivially by declaring
    its own output. So the pipeline compares against the catalogue itself. Here the stub does
    exactly what a paraphrasing provider would do — returns model prose and declares it — and
    the pipeline refuses to persist it.
    """
    leak = "Claro, le devolvemos los 250 EUR. Su DNI 12345678Z queda registrado."
    harness = Harness(make_conversation(), ai=StubAIAdapter(generated_content=leak))

    with pytest.raises(MessagingValidationError):
        await harness.run()

    assert harness.messages.by_sender(MessageSenderType.AI) == []
    assert harness.uow.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent",
    [
        MessageIntent.REFUND_OR_COMPENSATION,
        MessageIntent.EMERGENCY,
        MessageIntent.UNKNOWN,
    ],
)
async def test_generate_response_is_never_invoked_for_the_three_forbidden_intents(
    intent: MessageIntent,
) -> None:
    """R2.7 verbatim: "NEVER SHALL invocar `generate_response` para ellos".

    Asserted on the adapter rather than on the absence of a reply, because those are different
    claims: a pipeline that called the adapter and discarded the answer would satisfy the
    second and violate the first — and with a real provider that call is a request that leaves
    the building.
    """
    harness = Harness(
        make_conversation(), ai=StubAIAdapter(intent=intent, confidence=Decimal("0.99"))
    )

    await harness.run()

    assert harness.ai.generate_calls == []
    assert harness.conversation.status is ConversationStatus.ESCALATED


# --- Step 7a: escalation (R5.2, R5.4) ----------------------------------------------------


@pytest.mark.asyncio
async def test_escalating_sets_both_axes_and_emits_the_event() -> None:
    harness = Harness(make_conversation(), ai=StubAIAdapter(intent=MessageIntent.EMERGENCY))

    await harness.run()

    assert harness.conversation.status is ConversationStatus.ESCALATED
    assert harness.conversation.escalation_status is ConversationEscalationStatus.PENDING_HUMAN
    events = harness.timeline.of_type(TimelineEventType.AI_ESCALATED_TO_HUMAN)
    assert len(events) == 1
    assert events[0].actor_type is TimelineActorType.AI
    assert events[0].metadata["escalation_reason"] == EscalationReason.EMERGENCY_INTENT.value


@pytest.mark.asyncio
async def test_escalating_notifies_every_active_property_manager() -> None:
    harness = Harness(
        make_conversation(),
        ai=StubAIAdapter(intent=MessageIntent.EMERGENCY),
        users=FakeUserRepository(
            make_user(TENANT, email="one@example.com"),
            make_user(TENANT, email="two@example.com"),
        ),
    )

    await harness.run()

    assert len(harness.notifications.rows) == 2
    assert all(
        row.notification_type == NotificationType.GUEST_ESCALATION.value
        for row in harness.notifications.rows
    )


@pytest.mark.asyncio
async def test_escalation_fans_out_across_the_tenants_enabled_channels() -> None:
    """notification-channel-routing R1, R2 — the guest-escalation writer, exercised
    through the real use case → resolver → `dispatch_and_persist` path, not just the
    pure `channel_dispatch.py` unit tests."""
    from app.notifications.domain.enums import NotificationChannel

    manager = make_user(TENANT, email="manager@example.com", phone="+34600000002")
    harness = Harness(
        make_conversation(),
        ai=StubAIAdapter(intent=MessageIntent.EMERGENCY),
        users=FakeUserRepository(manager),
        configs=FakeTenantConfigRepository(
            notification_email_enabled=True, notification_whatsapp_enabled=True
        ),
    )

    await harness.run()

    by_channel = {row.channel: row for row in harness.notifications.rows}
    assert set(by_channel) == {
        NotificationChannel.IN_APP,
        NotificationChannel.EMAIL,
        NotificationChannel.WHATSAPP,
    }
    assert by_channel[NotificationChannel.EMAIL].recipient_contact == manager.email
    assert by_channel[NotificationChannel.WHATSAPP].recipient_contact == manager.phone
    assert all(
        row.notification_type == NotificationType.GUEST_ESCALATION.value
        for row in harness.notifications.rows
    )


@pytest.mark.asyncio
async def test_an_inactive_or_wrongly_rolled_user_is_not_notified() -> None:
    harness = Harness(
        make_conversation(),
        ai=StubAIAdapter(intent=MessageIntent.EMERGENCY),
        users=FakeUserRepository(
            make_user(TENANT, role=UserRole.CLEANER),
            make_user(TENANT, status=UserStatus.INACTIVE),
        ),
    )

    await harness.run()

    assert harness.notifications.rows == []


@pytest.mark.asyncio
async def test_a_tenant_with_no_manager_still_records_the_escalation() -> None:
    """D20: the guest's message is stored and the conversation is `ESCALATED`, which is the
    record that matters. Failing the run would lose the message over a missing account."""
    harness = Harness(
        make_conversation(),
        ai=StubAIAdapter(intent=MessageIntent.EMERGENCY),
        users=FakeUserRepository(),
    )

    await harness.run()

    assert harness.conversation.status is ConversationStatus.ESCALATED
    assert harness.notifications.rows == []
    assert harness.uow.commits == 1


@pytest.mark.asyncio
async def test_a_second_message_on_an_escalated_conversation_notifies_nobody() -> None:
    """**R5.4, and the mechanism is the transition table, not an `if` here** (D20).

    `escalate` accepts only `NONE` as an origin, so a conversation already `PENDING_HUMAN`
    cannot escalate again and therefore cannot notify again. The second message is still
    recorded and classified.
    """
    harness = Harness(
        make_conversation(), ai=StubAIAdapter(intent=MessageIntent.EMERGENCY)
    )

    await harness.run()
    await harness.run(now=NOW + timedelta(minutes=1))

    assert len(harness.notifications.rows) == 1
    assert len(harness.timeline.of_type(TimelineEventType.AI_ESCALATED_TO_HUMAN)) == 1
    assert len(harness.messages.by_sender(MessageSenderType.GUEST)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "escalation_status",
    [
        ConversationEscalationStatus.PENDING_HUMAN,
        ConversationEscalationStatus.HUMAN_HANDLING,
    ],
)
async def test_the_ai_stops_answering_once_a_person_has_the_conversation(
    escalation_status: ConversationEscalationStatus,
) -> None:
    """**The bug the QA panel of sections 5-6 constructed, pinned so it cannot come back.**

    R5.4 only says a second notification must not be sent, and the pipeline as first written
    kept answering with templates every later message on a conversation a manager was already
    holding — so the guest could receive the manager's reply and a template contradicting it.
    The message here classifies confidently to an intent that does **not** escalate, which is
    exactly the case that used to slip through.
    """
    harness = Harness(
        make_conversation(
            status=ConversationStatus.ESCALATED, escalation_status=escalation_status
        ),
        ai=StubAIAdapter(intent=MessageIntent.WIFI, confidence=Decimal("0.99")),
    )

    await harness.run()

    assert harness.ai.generate_calls == []
    assert harness.messages.by_sender(MessageSenderType.AI) == []
    # The message is still recorded and classified — silence is not the same as ignoring.
    assert len(harness.messages.by_sender(MessageSenderType.GUEST)) == 1
    assert harness.timeline.of_type(TimelineEventType.GUEST_MESSAGE_RECEIVED)


@pytest.mark.asyncio
async def test_a_resolved_conversation_gets_the_ai_back() -> None:
    """`RESOLVED` is deliberately **not** "handed over": the escalation finished, a new message
    reopens the conversation with the axis back at `NONE` (D4), and answering is right again —
    because that is a new problem."""
    harness = Harness(
        make_conversation(
            status=ConversationStatus.RESOLVED,
            escalation_status=ConversationEscalationStatus.RESOLVED,
        )
    )

    await harness.run()

    assert harness.conversation.status is ConversationStatus.OPEN
    assert harness.conversation.escalation_status is ConversationEscalationStatus.NONE
    assert harness.ai.generate_calls == [MessageIntent.WIFI]


# --- Step 7b's failure path (R6.5) -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_send_keeps_the_message_and_escalates() -> None:
    harness = Harness(
        make_conversation(),
        adapter=FakeOutboundAdapter(
            result=ChannelSendResult.failure(ChannelErrorCode.INVALID_RECIPIENT)
        ),
    )

    await harness.run()

    replies = harness.messages.by_sender(MessageSenderType.AI)
    assert len(replies) == 1
    assert replies[0].metadata.delivery_status == DELIVERY_STATUS_FAILED
    assert replies[0].metadata.delivery_error_code is ChannelErrorCode.INVALID_RECIPIENT
    assert replies[0].metadata.escalation_reason is EscalationReason.DELIVERY_FAILED
    assert harness.conversation.status is ConversationStatus.ESCALATED


@pytest.mark.asyncio
async def test_a_failed_send_emits_no_response_event() -> None:
    """It was not sent, and `timeline_events` is append-only — a wrong event could never be
    taken back (R6.5, D14)."""
    harness = Harness(
        make_conversation(),
        adapter=FakeOutboundAdapter(
            result=ChannelSendResult.failure(ChannelErrorCode.ADAPTER_UNAVAILABLE)
        ),
    )

    await harness.run()

    assert harness.timeline.of_type(TimelineEventType.AI_RESPONSE_SENT) == []
    assert len(harness.timeline.of_type(TimelineEventType.AI_ESCALATED_TO_HUMAN)) == 1


@pytest.mark.asyncio
async def test_the_recorded_failure_carries_no_message_body() -> None:
    """R6.5: "código y campo, nunca el cuerpo"."""
    harness = Harness(
        make_conversation(),
        adapter=FakeOutboundAdapter(
            result=ChannelSendResult.failure(ChannelErrorCode.INVALID_RECIPIENT)
        ),
    )

    await harness.run()

    metadata = harness.messages.by_sender(MessageSenderType.AI)[0].metadata.to_dict()
    assert GUEST_MESSAGE not in str(metadata)
    assert all(isinstance(value, str) for value in metadata.values())


@pytest.mark.asyncio
async def test_an_ota_channel_refuses_the_send_instead_of_falling_back(
) -> None:
    """R6.3. The registry has no key for it (`test_channels.py` pins that half); here the
    caller's half: a named error, never a silent console delivery."""
    harness = Harness(
        make_conversation(channel=ConversationChannel.BOOKING_MSG), channels={}
    )

    with pytest.raises(PMSChannelUnavailableError):
        await harness.run()


# --- Step 8: the derived incident (R4.6) -------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent", [MessageIntent.MAINTENANCE_ISSUE, MessageIntent.ACCESS_PROBLEM]
)
async def test_the_two_incident_intents_open_one(intent: MessageIntent) -> None:
    harness = Harness(make_conversation(), ai=StubAIAdapter(intent=intent))

    await harness.run()

    assert len(harness.incidents.reports) == 1
    report = harness.incidents.reports[0]
    assert report["title"] == INCIDENT_TITLES[intent]
    assert report["description"] == GUEST_MESSAGE
    assert report["actor_user_id"] == ACTOR
    assert report["ip"] == IP


@pytest.mark.asyncio
async def test_any_other_intent_opens_no_incident() -> None:
    harness = Harness(make_conversation(), ai=StubAIAdapter(intent=MessageIntent.WIFI))

    await harness.run()

    assert harness.incidents.reports == []


@pytest.mark.asyncio
async def test_the_incident_is_opened_even_when_the_conversation_escalates() -> None:
    """Step 8 is orthogonal to step 7 (D11): a broken boiler reported in a message that also
    trips an emergency keyword needs both the person and the ticket."""
    harness = Harness(
        make_conversation(),
        ai=StubAIAdapter(intent=MessageIntent.MAINTENANCE_ISSUE),
    )

    await harness.run("Hay humo y la caldera esta rota")

    assert harness.conversation.status is ConversationStatus.ESCALATED
    assert len(harness.incidents.reports) == 1


@pytest.mark.asyncio
async def test_the_incident_description_is_the_guests_words_verbatim() -> None:
    """D13: the copy of a column to another does not make us the writer of what the guest
    typed — but only while it is bit-for-bit what they typed."""
    typed = "No puedo entrar. Mi DNI es 12345678Z y el codigo 4471 no va."
    harness = Harness(
        make_conversation(), ai=StubAIAdapter(intent=MessageIntent.ACCESS_PROBLEM)
    )

    await harness.run(typed)

    assert harness.incidents.reports[0]["description"] == typed


# --- The recipient of a reply (D14) ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_whatsapp_reply_is_addressed_to_the_guests_phone() -> None:
    guest = GuestSummary(
        id=uuid.uuid4(),
        full_name="Ada",
        email="ada@example.com",
        phone="+34600123456",
        preferred_language="es",
        document_status=GuestDocumentStatus.NOT_PROVIDED,
        legal_registration_status=LegalRegistrationStatus.NOT_REQUIRED,
    )
    harness = Harness(
        make_conversation(channel=ConversationChannel.WHATSAPP, guest_id=guest.id),
        guests=FakeGuestRepository(guest),
    )

    await harness.run()

    assert harness.adapter.sends[0]["recipient_contact"] == "+34600123456"


@pytest.mark.asyncio
async def test_a_panel_conversation_addresses_nobody() -> None:
    """`MANUAL` has no address: the row **is** the delivery."""
    harness = Harness(make_conversation(channel=ConversationChannel.MANUAL))

    await harness.run()

    assert harness.adapter.sends[0]["recipient_contact"] is None


# --- RecordHumanReplyUseCase (R4.5, D18) -------------------------------------------------


def human_reply_use_case(harness: Harness) -> RecordHumanReplyUseCase:
    return RecordHumanReplyUseCase(
        conversations=harness.conversations,
        messages=harness.messages,
        timeline=harness.timeline,
        uow=harness.uow,
    )


@pytest.mark.asyncio
async def test_a_human_reply_derives_its_sender_type_from_the_role() -> None:
    """D18: a client cannot declare who wrote a message. The mapping has one entry today,
    because D17 left the owner read-only — and it is a table so the second is one line."""
    harness = Harness(make_conversation())

    message = await human_reply_use_case(harness).execute(
        tenant_id=TENANT,
        conversation_id=harness.conversation.id,
        content="Vamos a mirarlo ahora mismo",
        actor_user_id=ACTOR,
        actor_role=UserRole.PROPERTY_MANAGER,
        now=NOW,
    )

    assert message.sender_type is MessageSenderType.MANAGER
    assert message.sender_user_id == ACTOR
    assert message.ai_generated is False
    assert message.intent is None


@pytest.mark.asyncio
async def test_a_role_with_no_sender_type_is_refused() -> None:
    """A 403 stops this before it arrives; this is the ceiling for a caller with no HTTP in
    front of it, and it refuses rather than inventing a `sender_type`."""
    harness = Harness(make_conversation())

    with pytest.raises(MessagingValidationError):
        await human_reply_use_case(harness).execute(
            tenant_id=TENANT,
            conversation_id=harness.conversation.id,
            content="hola",
            actor_user_id=ACTOR,
            actor_role=UserRole.CLEANER,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_answering_a_pending_conversation_takes_it_over() -> None:
    """D4: contestar *es* tomar el mando. Without this, `HUMAN_HANDLING` would have no
    writer at all."""
    harness = Harness(
        make_conversation(
            status=ConversationStatus.ESCALATED,
            escalation_status=ConversationEscalationStatus.PENDING_HUMAN,
        )
    )

    await human_reply_use_case(harness).execute(
        tenant_id=TENANT,
        conversation_id=harness.conversation.id,
        content="Ya lo estoy mirando",
        actor_user_id=ACTOR,
        actor_role=UserRole.PROPERTY_MANAGER,
        now=NOW,
    )

    assert harness.conversation.escalation_status is ConversationEscalationStatus.HUMAN_HANDLING


@pytest.mark.asyncio
async def test_answering_a_conversation_nobody_escalated_changes_no_axis() -> None:
    harness = Harness(make_conversation())

    await human_reply_use_case(harness).execute(
        tenant_id=TENANT,
        conversation_id=harness.conversation.id,
        content="Buenos dias",
        actor_user_id=ACTOR,
        actor_role=UserRole.PROPERTY_MANAGER,
        now=NOW,
    )

    assert harness.conversation.escalation_status is ConversationEscalationStatus.NONE
    assert harness.conversation.status is ConversationStatus.OPEN


@pytest.mark.asyncio
async def test_a_human_reply_emits_its_timeline_event_with_a_user_actor() -> None:
    harness = Harness(make_conversation())

    await human_reply_use_case(harness).execute(
        tenant_id=TENANT,
        conversation_id=harness.conversation.id,
        content="Buenos dias",
        actor_user_id=ACTOR,
        actor_role=UserRole.PROPERTY_MANAGER,
        now=NOW,
    )

    events = harness.timeline.of_type(TimelineEventType.HUMAN_RESPONSE_SENT)
    assert len(events) == 1
    assert events[0].actor_type is TimelineActorType.USER
    assert events[0].actor_user_id == ACTOR


def test_the_role_mapping_has_one_entry_and_it_is_the_manager() -> None:
    """D17's declared consequence: `MessageSenderType.OWNER` has no writer in this change."""
    assert SENDER_TYPE_BY_ROLE == {UserRole.PROPERTY_MANAGER: MessageSenderType.MANAGER}


# --- The inbox use cases (R7.1, R7.3, R7.4) ----------------------------------------------


class StubProperty:
    def __init__(self, id: uuid.UUID) -> None:
        self.id = id


def create_conversation_use_case(
    *, properties=(), reservations=(), guests=()
) -> tuple[CreateConversationUseCase, FakeConversationRepository, FakeUnitOfWork]:
    conversations = FakeConversationRepository()
    uow = FakeUnitOfWork()
    return (
        CreateConversationUseCase(
            conversations=conversations,
            properties=FakePropertyRepository(*properties),
            reservations=FakeReservationRepository(*reservations),
            guests=FakeGuestRepository(*guests),
            uow=uow,
        ),
        conversations,
        uow,
    )


@pytest.mark.asyncio
async def test_creating_a_conversation_persists_and_commits() -> None:
    use_case, conversations, uow = create_conversation_use_case(
        properties=(StubProperty(PROPERTY),)
    )

    conversation = await use_case.execute(
        tenant_id=TENANT,
        property_id=PROPERTY,
        channel=ConversationChannel.WHATSAPP,
        reservation_id=None,
        guest_id=None,
        language="es",
        now=NOW,
    )

    assert conversations.rows[conversation.id] is conversation
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_a_property_of_another_tenant_cannot_anchor_a_conversation() -> None:
    """**The precondition `ConversationRepository.add` states and cannot enforce.**

    The foreign keys of `conversations` are global rather than composite with `tenant_id`, so
    Postgres would accept a conversation of tenant A anchored to a property of tenant B — and
    every `TimelineEvent` it ever produces would carry that `property_id` forward, where no
    later read could undo it. This is the only route that takes the id from a client, so this
    is where it has to be resolved. Raised by the tenancy panel of sections 5-6.
    """
    use_case, conversations, uow = create_conversation_use_case(properties=())

    with pytest.raises(MessagingValidationError):
        await use_case.execute(
            tenant_id=TENANT,
            property_id=uuid.uuid4(),
            channel=ConversationChannel.MANUAL,
            reservation_id=None,
            guest_id=None,
            language="es",
            now=NOW,
        )

    assert conversations.rows == {}
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_guest_of_another_tenant_cannot_anchor_a_conversation() -> None:
    """The same precondition, on the **third** foreign key — the one the first implementation
    left unchecked, found by the review panel of 2026-08-16.

    It is the worst of the three to get wrong, and not because of the conversation. `guests.id`
    is referenced with `ondelete="RESTRICT"`, so an anchor pointing into another tenant does
    not merely mislabel a row: it pins that tenant's guest against deletion, and they cannot
    see why or clear it from any data of their own. Only checked when one is supplied — a
    conversation without a guest is legitimate.
    """
    use_case, conversations, uow = create_conversation_use_case(
        properties=(StubProperty(PROPERTY),)
    )

    with pytest.raises(MessagingValidationError):
        await use_case.execute(
            tenant_id=TENANT,
            property_id=PROPERTY,
            channel=ConversationChannel.MANUAL,
            reservation_id=None,
            guest_id=uuid.uuid4(),
            language="es",
            now=NOW,
        )

    assert conversations.rows == {}
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_reservation_of_another_tenant_cannot_anchor_a_conversation() -> None:
    """The same precondition, on the second foreign key. Only checked when one is supplied:
    a conversation without a reservation is legitimate (R5.6)."""
    use_case, conversations, uow = create_conversation_use_case(
        properties=(StubProperty(PROPERTY),)
    )

    with pytest.raises(MessagingValidationError):
        await use_case.execute(
            tenant_id=TENANT,
            property_id=PROPERTY,
            channel=ConversationChannel.MANUAL,
            reservation_id=uuid.uuid4(),
            guest_id=None,
            language="es",
            now=NOW,
        )

    assert conversations.rows == {}
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_listing_conversations_passes_the_filters_through() -> None:
    wanted = make_conversation(status=ConversationStatus.ESCALATED)
    other = make_conversation(status=ConversationStatus.OPEN)
    conversations = FakeConversationRepository(wanted, other)

    page = await ListConversationsUseCase(conversations=conversations).execute(
        tenant_id=TENANT,
        filters=ConversationFilters(status=ConversationStatus.ESCALATED),
        page=1,
        per_page=10,
    )

    assert [item.id for item in page.items] == [wanted.id]


@pytest.mark.asyncio
async def test_getting_an_unknown_conversation_is_a_not_found_error() -> None:
    with pytest.raises(ConversationNotFoundError):
        await GetConversationUseCase(
            conversations=FakeConversationRepository()
        ).execute(tenant_id=TENANT, conversation_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_listing_the_messages_of_an_unknown_conversation_is_a_404_not_an_empty_page(
) -> None:
    """An empty page would confirm the conversation exists and is simply quiet, which is the
    distinction R1.5 closes."""
    harness = Harness(make_conversation())

    with pytest.raises(ConversationNotFoundError):
        await ListMessagesUseCase(
            conversations=harness.conversations, messages=harness.messages
        ).execute(
            tenant_id=TENANT, conversation_id=uuid.uuid4(), page=1, per_page=10
        )


@pytest.mark.asyncio
async def test_escalating_manually_records_a_user_actor() -> None:
    """The difference from the pipeline's escalation, and the reason the timeline builder
    takes the actor instead of deriving it from the event type."""
    harness = Harness(make_conversation())

    await EscalateConversationUseCase(
        conversations=harness.conversations,
        timeline=harness.timeline,
        uow=harness.uow,
    ).execute(
        tenant_id=TENANT,
        conversation_id=harness.conversation.id,
        actor_user_id=ACTOR,
        now=NOW,
    )

    events = harness.timeline.of_type(TimelineEventType.AI_ESCALATED_TO_HUMAN)
    assert events[0].actor_type is TimelineActorType.USER
    assert events[0].actor_user_id == ACTOR


@pytest.mark.asyncio
async def test_escalating_an_already_escalated_conversation_manually_is_a_conflict() -> None:
    """Unlike the pipeline's, which swallows it: there the guest's message must still be
    processed, here the caller asked for something that cannot happen."""
    harness = Harness(
        make_conversation(
            status=ConversationStatus.ESCALATED,
            escalation_status=ConversationEscalationStatus.PENDING_HUMAN,
        )
    )

    with pytest.raises(InvalidConversationTransitionError):
        await EscalateConversationUseCase(
            conversations=harness.conversations,
            timeline=harness.timeline,
            uow=harness.uow,
        ).execute(
            tenant_id=TENANT,
            conversation_id=harness.conversation.id,
            actor_user_id=ACTOR,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_resolving_closes_the_escalation_with_it() -> None:
    """D4's cross-axis effect: R7.1 gives no route for `resolve_escalation` alone, so a
    conversation resolved with its escalation left pending would sit for ever in whatever
    list asks for pending handovers."""
    harness = Harness(
        make_conversation(
            status=ConversationStatus.ESCALATED,
            escalation_status=ConversationEscalationStatus.PENDING_HUMAN,
        )
    )

    conversation = await ResolveConversationUseCase(
        conversations=harness.conversations, uow=harness.uow
    ).execute(tenant_id=TENANT, conversation_id=harness.conversation.id, now=NOW)

    assert conversation.status is ConversationStatus.RESOLVED
    assert conversation.escalation_status is ConversationEscalationStatus.RESOLVED
