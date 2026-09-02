"""The messaging use cases (R4, R5, R6, R7; design D11, D12, D14, D18, D20).

`ProcessInboundGuestMessageUseCase` is the one that matters: the ten steps of D11 in **one
transaction with one `commit()`** (R4.7), so there is no state in which a message exists
without its timeline event, or a conversation is escalated without anybody being told.

Orchestration only. Every rule it applies lives in `domain/` — the transition tables on
`Conversation`, the escalation policy in `escalation.py`, the catalogue in `templates.py` —
which is what `steering/backend-architecture.md` means by "No lógica de negocio en
`application/`". What is left here is the order, and the order is D11's.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from app.core.unit_of_work import UnitOfWork
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.ports import UserRepository
from app.auth.domain.repositories import UserFilters
from app.messaging.domain.entities import Conversation, Message
from app.guests.domain.repositories import GuestRepository
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    EscalationReason,
    MessageIntent,
    MessageSenderType,
)
from app.messaging.domain.escalation import evaluate
from app.messaging.domain.exceptions import (
    ConversationClosedError,
    ConversationNotFoundError,
    InvalidConversationTransitionError,
    MessagingValidationError,
    PMSChannelUnavailableError,
)
from app.messaging.domain.language import detect_language
from app.messaging.domain.notifications import guest_escalation_notification
from app.messaging.domain.ports import (
    AIAdapter,
    IncidentReportingPort,
    OutboundMessagePort,
)
from app.messaging.domain.repositories import (
    ConversationFilters,
    ConversationPage,
    ConversationRepository,
    MessagePage,
    MessageRepository,
)
from app.messaging.domain.templates import (
    INCIDENT_TITLES,
    INTENTS_WITHOUT_TEMPLATE,
    TEMPLATE_CATALOGUE_VERSION,
    assert_in_catalogue,
)
from app.messaging.domain.value_objects import (
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_SENT,
    ConversationContext,
    InboundMessageActor,
    MessageClassification,
    MessageMetadata,
    contact_kind_for,
)
from app.notifications.application.channel_dispatch import dispatch_and_persist
from app.notifications.domain.enums import NotificationType
from app.notifications.domain.repositories import NotificationLogRepository
from app.properties.domain.clock_triggers import effective_bounds
from app.properties.domain.repositories import PropertyRepository
from app.reservations.domain.repositories import ReservationRepository
from app.tenants.domain.repositories import TenantConfigRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

logger = logging.getLogger(__name__)

#: What the timeline says at each messaging milestone. Constants, and `metadata` carries
#: identifiers and closed enums only (R3.6): `timeline_events` is append-only, so a word the
#: guest typed could never be redacted from it afterwards.
_TIMELINE_TITLES: dict[TimelineEventType, str] = {
    TimelineEventType.GUEST_MESSAGE_RECEIVED: "Guest sent a message",
    TimelineEventType.AI_RESPONSE_SENT: "Automatic reply sent",
    TimelineEventType.AI_ESCALATED_TO_HUMAN: "Conversation escalated to a person",
    TimelineEventType.HUMAN_RESPONSE_SENT: "A person replied",
}

#: Which intents open a maintenance incident (R4.6), and the closed catalogue of titles that
#: goes with them. Imported from `maintenance` because that module owns what an incident is
#: called; this module owns which conversation intents produce one.
_INCIDENT_INTENTS = (MessageIntent.MAINTENANCE_ISSUE, MessageIntent.ACCESS_PROBLEM)

#: The one role that may write a message today, and the `sender_type` it writes as (D17, D18).
#: A table and not an `if`, so the day `MANAGE_CONVERSATIONS` reaches another role it is one
#: line — which is exactly what D17 promised when it left the owner read-only, leaving
#: `MessageSenderType.OWNER` without a writer in this change.
SENDER_TYPE_BY_ROLE: dict[UserRole, MessageSenderType] = {
    UserRole.PROPERTY_MANAGER: MessageSenderType.MANAGER,
}


def _timeline_event(
    *,
    conversation: Conversation,
    event_type: TimelineEventType,
    actor_type: TimelineActorType,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, str],
    now: datetime,
) -> TimelineEventData:
    """One builder for the four events, so no call site can invent a title or a shape.

    `property_id` is not optional for `TimelineEventFactory`, and `Conversation` refuses to
    exist without one (D19) — which is the whole reason that refusal is there.
    """
    return TimelineEventData(
        id=uuid.uuid4(),
        tenant_id=conversation.tenant_id,
        property_id=conversation.property_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        event_type=event_type,
        title=_TIMELINE_TITLES[event_type],
        created_at=now,
        reservation_id=conversation.reservation_id,
        metadata=metadata,
    )


class ProcessInboundGuestMessageUseCase:
    """The pipeline of D11: one guest message in, one transaction, one commit (R4.1, R4.7).

    The order, and the two places it departs from the literal reading of R4.1/D14, each for a
    reason recorded in `design.md`:

    1. resolve the conversation within the tenant (R1.5), refuse it if `CLOSED`, reopen it if
       `RESOLVED`;
    2. detect the language (R4.8), falling back to `Conversation.language`;
    3. **classify, then persist** the guest's `Message` carrying its intent and language.
       R4.1 lists persistence before classification; `Message` is frozen (the fix for the
       construction-only degradation of R3.4), so its `intent` has to be known when it is
       built. Inside a single transaction the two orders are indistinguishable to everyone
       outside it, and the requirement's substance — that the message is recorded, classified
       and put on the timeline together or not at all — is unchanged;
    4. `register_message`, so the inbox can be ordered without walking `messages` (R1.4);
    5. `TimelineEvent(GUEST_MESSAGE_RECEIVED)`;
    6. evaluate the escalation policy (R5.1);
    7. **either** escalate (R5) **or**, if `ai_enabled`, reply (R4.4) — never both;
    8. open an incident if the intent calls for one (R4.6), which is orthogonal to 7;
    9. `commit()`.

    Step 8 runs whichever branch step 7 took: a guest reporting a broken boiler in a message
    that also trips an emergency keyword needs both the person and the ticket.

    **Synchronous, inside the request**, and the difference from `maintenance` (which moved
    its classification to a Celery job) is deliberate: there the guest is waiting for nothing,
    here the product promise is that they get an answer. With `MockAIAdapter` the cost is
    arithmetic. The risk with a real provider is named in the design's Risks with its remedy.
    """

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
        ai: AIAdapter,
        channels: dict[ConversationChannel, OutboundMessagePort],
        incidents: IncidentReportingPort,
        timeline: TimelineEventRepository,
        notifications: NotificationLogRepository,
        users: UserRepository,
        guests: GuestRepository,
        configs: TenantConfigRepository,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        uow: UnitOfWork,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._ai = ai
        self._channels = channels
        self._incidents = incidents
        self._timeline = timeline
        self._notifications = notifications
        self._users = users
        self._guests = guests
        self._configs = configs
        self._properties = properties
        self._reservations = reservations
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        actor: InboundMessageActor,
        now: datetime,
    ) -> Message:
        conversation = await self._resolve(tenant_id, conversation_id, now)

        language = detect_language(content) or conversation.language
        context = ConversationContext(
            conversation_id=conversation.id,
            property_id=conversation.property_id,
            reservation_id=conversation.reservation_id,
            channel=conversation.channel,
            language=language,
            ai_enabled=conversation.ai_enabled,
            guest_message_count=await self._messages.count_guest_messages(
                tenant_id, conversation.id
            ),
        )
        classification = await self._ai.classify_message(
            content=content, language=language, context=context
        )

        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            sender_type=MessageSenderType.GUEST,
            content=content,
            created_at=now,
            language=language,
            intent=classification.intent,
            confidence_score=classification.confidence,
        )
        await self._messages.add(tenant_id, message)

        conversation.register_message(now=now)
        await self._conversations.save(tenant_id, conversation)

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    conversation=conversation,
                    event_type=TimelineEventType.GUEST_MESSAGE_RECEIVED,
                    actor_type=TimelineActorType.GUEST,
                    actor_user_id=None,
                    metadata={
                        "conversation_id": str(conversation.id),
                        "message_id": str(message.id),
                        "intent": classification.intent.value,
                        "language": language,
                    },
                    now=now,
                )
            ),
        )

        reason = evaluate(
            classification=classification,
            content=content,
            threshold=await self._threshold(tenant_id, now),
            repeated_intent_count=(
                await self._messages.count_unresolved_guest_messages_with_intent(
                    tenant_id, conversation.id, classification.intent
                )
            ),
            hours_to_checkin=await self._hours_to_checkin(tenant_id, conversation, now),
        )

        if reason is not None:
            await self._escalate(tenant_id, conversation, reason, now)
        elif conversation.ai_enabled and not conversation.is_handed_over():
            await self._reply(tenant_id, conversation, message, classification, language, now)

        if classification.intent in _INCIDENT_INTENTS:
            await self._open_incident(
                tenant_id, conversation, message, classification.intent, actor, now
            )

        await self._uow.commit()
        return message

    # --- Step 1 --------------------------------------------------------------------------

    async def _resolve(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID, now: datetime
    ) -> Conversation:
        """Find the conversation in this tenant, and make sure it can take a message.

        `CLOSED` is refused and `RESOLVED` is reopened (D4): a guest writing again into a
        conversation somebody marked resolved has, by writing, made it unresolved.
        """
        conversation = await self._conversations.get(tenant_id, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError()
        if conversation.status is ConversationStatus.CLOSED:
            raise ConversationClosedError(
                "Conversation is closed and accepts no further messages"
            )
        if conversation.status is ConversationStatus.RESOLVED:
            conversation.reopen(now=now)
        return conversation

    # --- Step 6's inputs -----------------------------------------------------------------

    async def _threshold(self, tenant_id: uuid.UUID, now: datetime) -> Decimal:
        """`get_or_create` and not `get`: a tenant that arrived by any route still has a
        configuration to read, which is the reason that port has no plain `get`."""
        config = await self._configs.get_or_create(tenant_id, now)
        return config.ai_confidence_threshold

    async def _recipient_contact(
        self, tenant_id: uuid.UUID, conversation: Conversation
    ) -> str | None:
        """Where to send, for the channels that need an address (D14).

        Resolved from the conversation's guest, per channel: a phone number for `WHATSAPP`, an
        email for `EMAIL`, and nothing for the channels that do not address anybody —
        `MANUAL`, where the row *is* the delivery, and `PHONE_TRANSCRIPT`, which has no
        outbound direction at all.

        `None` when the conversation has no guest or the guest has no contact of that kind,
        and the adapter turns that into `INVALID_RECIPIENT` — a failure by value, which R6.5
        routes to a person rather than losing. That is the right outcome: we genuinely cannot
        deliver, and pretending otherwise would show an operator a message the guest never got.

        `GuestSummary` and not `Guest`: the projection carries the contact fields and
        structurally cannot carry the identity document (rule 4 of `steering/security.md`).
        """
        kind = contact_kind_for(conversation.channel)
        if kind is None or conversation.guest_id is None:
            return None
        guest = await self._guests.get(tenant_id, conversation.guest_id)
        if guest is None:
            return None
        return guest.phone if kind == "phone" else guest.email

    async def _hours_to_checkin(
        self, tenant_id: uuid.UUID, conversation: Conversation, now: datetime
    ) -> Decimal | None:
        """How long until the stay starts, or `None` when the question does not apply (R5.6).

        `None` when the conversation has no reservation, when the reservation or the property
        cannot be resolved, **and when the local check-in time does not exist** — the spring
        DST gap, which `effective_bounds` refuses rather than guessing. R5.6 says the
        condition is then not met and the message is processed anyway, so every one of those
        is `None` and none of them is an exception.

        The instant comes from `effective_bounds` (`app/properties/domain/clock_triggers.py`)
        and never from a subtraction of dates: that function resolves the property's time zone
        and both DST holes, and its own module says it is the one piece of arithmetic that
        must not be reimplemented.
        """
        if conversation.reservation_id is None:
            return None
        reservation = await self._reservations.get(tenant_id, conversation.reservation_id)
        if reservation is None:
            return None
        property_ = await self._properties.get(tenant_id, conversation.property_id)
        if property_ is None:
            return None
        try:
            start, _ = effective_bounds(property_, reservation)
        except Exception:
            # Every failure of `effective_bounds` is a check-in instant that cannot be
            # computed, which R5.6 treats as "condition not met" rather than as a reason to
            # fail a guest's message. Broad on purpose: the alternative is importing another
            # domain's exception hierarchy to re-raise it as the same `None`.
            logger.warning(
                "messaging.checkin_bounds_unavailable",
                extra={
                    "tenant_id": str(tenant_id),
                    "conversation_id": str(conversation.id),
                },
            )
            return None
        return Decimal((start - now).total_seconds()) / Decimal(3600)

    # --- Step 7a: escalation (R5.2, R5.4) ------------------------------------------------

    async def _escalate(
        self,
        tenant_id: uuid.UUID,
        conversation: Conversation,
        reason: EscalationReason,
        now: datetime,
    ) -> None:
        """Hand the conversation to a person, once (R5.2), and never twice (R5.4).

        **The "never twice" is the transition table's, not an `if` here** (D20): `escalate`
        accepts only `NONE` as an origin, so a conversation already `PENDING_HUMAN` cannot
        escalate again and therefore cannot notify again.

        The `except` is **narrowed to the one condition it is entitled to absorb** — a
        conversation whose escalation axis has already left `NONE`. A bare
        `except InvalidConversationTransitionError` was an `if` in disguise: it would silently
        swallow any *other* refusal the table might raise after a future widening, leaving the
        guest's message recorded with no escalation, no notification and no error — which is
        precisely the failure D20 attributes to putting the rule in the use case. Raised by the
        architecture panel of sections 5-6.
        """
        already_handed_over = (
            conversation.escalation_status is not ConversationEscalationStatus.NONE
        )
        try:
            conversation.escalate(now=now)
        except InvalidConversationTransitionError:
            if not already_handed_over:
                # The table refused for a reason this method does not know about. Letting it
                # out is the point: it aborts the transaction rather than half-processing.
                raise
            logger.info(
                "messaging.escalation_already_pending",
                extra={
                    "tenant_id": str(tenant_id),
                    "conversation_id": str(conversation.id),
                    "escalation_reason": reason.value,
                },
            )
            return

        await self._conversations.save(tenant_id, conversation)
        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    conversation=conversation,
                    event_type=TimelineEventType.AI_ESCALATED_TO_HUMAN,
                    actor_type=TimelineActorType.AI,
                    actor_user_id=None,
                    metadata={
                        "conversation_id": str(conversation.id),
                        "escalation_reason": reason.value,
                    },
                    now=now,
                )
            ),
        )
        await self._notify_managers(tenant_id, conversation, now)

    async def _notify_managers(
        self, tenant_id: uuid.UUID, conversation: Conversation, now: datetime
    ) -> None:
        """A `GUEST_ESCALATION` row for each active `PROPERTY_MANAGER` of the tenant (R5.2).

        If the tenant has none there is nobody to address, and **the run is not failed over
        it** (D20): the guest's message is already stored and the conversation is already
        `ESCALATED`, which is the record that matters. Logged rather than swallowed, because a
        tenant in that state has an escalation nobody will see.
        """
        managers = await self._users.list(
            tenant_id,
            UserFilters(role=UserRole.PROPERTY_MANAGER, status=UserStatus.ACTIVE),
            page=1,
            per_page=50,
        )
        if not managers.items:
            logger.warning(
                "messaging.escalation_without_recipient",
                extra={
                    "tenant_id": str(tenant_id),
                    "conversation_id": str(conversation.id),
                },
            )
            return

        config = await self._configs.get_or_create(tenant_id, now)
        for manager in managers.items:
            await dispatch_and_persist(
                notifications=self._notifications,
                tenant_id=tenant_id,
                recipient=manager,
                config=config,
                notification_type=NotificationType.GUEST_ESCALATION.value,
                recipient_role=manager.role.value,
                log_builder=guest_escalation_notification,
                conversation_id=conversation.id,
                property_id=conversation.property_id,
                recipient_user_id=manager.id,
                now=now,
            )

    # --- Step 7b: the automatic reply (R4.4, R6.5) ---------------------------------------

    async def _reply(
        self,
        tenant_id: uuid.UUID,
        conversation: Conversation,
        source: Message,
        classification: MessageClassification,
        language: str,
        now: datetime,
    ) -> None:
        """Generate, send, and record — in that order, and building the row once (D14).

        D14 originally described this as "persist, send, then annotate the failure". Under the
        single transaction of R4.7 both orders have the identical durability guarantee —
        nothing is durable until the one commit — and the annotate-afterwards version would
        require a mutable `Message` plus a `save()` on `MessageRepository` that R1.1 does not
        admit. So the outcome is known before the row is built, and the row is built once.
        """
        if classification.intent in INTENTS_WITHOUT_TEMPLATE:
            # Unreachable while `evaluate` escalates for all three (R2.7), and kept as the
            # first of D7's two nets: the second is the catalogue having no entry at all.
            raise MessagingValidationError(
                f"{classification.intent.value} is never answered automatically (R2.7)"
            )

        adapter = self._channels.get(conversation.channel)
        if adapter is None:
            # R6.3: `AIRBNB_MSG` and `BOOKING_MSG` have no adapter, and there is deliberately
            # no key to fall back to. Raised before anything is written, so a conversation on
            # one of those channels is mute rather than half-answered.
            raise PMSChannelUnavailableError(
                f"Channel {conversation.channel.value} can only send through the PMS, "
                "which has no messaging adapter yet"
            )

        generated = await self._ai.generate_response(
            intent=classification.intent,
            language=language,
            context=ConversationContext(
                conversation_id=conversation.id,
                property_id=conversation.property_id,
                reservation_id=conversation.reservation_id,
                channel=conversation.channel,
                language=language,
                ai_enabled=conversation.ai_enabled,
                guest_message_count=await self._messages.count_guest_messages(
                    tenant_id, conversation.id
                ),
            ),
        )
        # **Against the catalogue, not against `generated.vocabulary`.** An adapter may declare
        # its own output as its vocabulary and satisfy `GeneratedResponse` trivially —
        # `steering/security.md` says so of this exact construction — so this is what makes
        # `messages.content` a closed form for a writer of ours (R3.3), whatever adapter is
        # wired in. Called before the send as well as before the row, so out-of-catalogue prose
        # never reaches the channel either.
        assert_in_catalogue(generated.content)

        result = await adapter.send(
            channel=conversation.channel,
            conversation_id=conversation.id,
            recipient_contact=await self._recipient_contact(tenant_id, conversation),
            content=generated.content,
            language=language,
        )

        reply = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            sender_type=MessageSenderType.AI,
            content=generated.content,
            created_at=now,
            language=language,
            ai_generated=True,
            confidence_score=classification.confidence,
            intent=classification.intent,
            metadata=MessageMetadata(
                template_key=generated.template_key,
                template_version=TEMPLATE_CATALOGUE_VERSION,
                source_message_id=source.id,
                delivery_status=(
                    DELIVERY_STATUS_SENT if result.delivered else DELIVERY_STATUS_FAILED
                ),
                delivery_error_code=result.error_code,
                escalation_reason=(
                    None if result.delivered else EscalationReason.DELIVERY_FAILED
                ),
            ),
        )
        await self._messages.add(tenant_id, reply)
        conversation.register_message(now=now)
        await self._conversations.save(tenant_id, conversation)

        if not result.delivered:
            # R6.5: the message is kept, the failure is recorded in closed form, and the
            # conversation goes to a person who can retry. **No `AI_RESPONSE_SENT`** — it was
            # not sent, and `timeline_events` is append-only, so a wrong event could never be
            # taken back.
            await self._escalate(
                tenant_id, conversation, EscalationReason.DELIVERY_FAILED, now
            )
            return

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    conversation=conversation,
                    event_type=TimelineEventType.AI_RESPONSE_SENT,
                    actor_type=TimelineActorType.AI,
                    actor_user_id=None,
                    metadata={
                        "conversation_id": str(conversation.id),
                        "message_id": str(reply.id),
                        "intent": classification.intent.value,
                        "template_key": generated.template_key,
                    },
                    now=now,
                )
            ),
        )

    # --- Step 8: the derived incident (R4.6) ---------------------------------------------

    async def _open_incident(
        self,
        tenant_id: uuid.UUID,
        conversation: Conversation,
        message: Message,
        intent: MessageIntent,
        actor: InboundMessageActor,
        now: datetime,
    ) -> None:
        """Through the port, never by importing `maintenance` (D12).

        `title` from the closed catalogue in this module's own `domain/`, `description` the
        guest's message **verbatim** — the census is done by who writes the column, and this
        copies a value that is not ours without composing anything (D13).

        `actor` travels whole rather than unpacked into a user id and an ip
        (`guest-portal-messaging` D8): it is the only parameter of this pipeline the portal
        could not satisfy, and the implementer needs all of it — the incident's reporter, the
        audit row's actor and the timeline's actor type are three different derivations of the
        same one answer.
        """
        await self._incidents.report(
            tenant_id=tenant_id,
            property_id=conversation.property_id,
            reservation_id=conversation.reservation_id,
            title=INCIDENT_TITLES[intent],
            description=message.content,
            actor=actor,
            now=now,
        )


class RecordHumanReplyUseCase:
    """A person answers the guest (R4.5, D18).

    Two things happen that the pipeline above does not do, and both come from *who* is
    writing: the `sender_type` is **derived from the caller's role** rather than taken from
    the request, and answering a conversation that is waiting for a person **is** taking it
    over (D4), so `take_over` runs.

    Nothing is classified and nothing is generated: this message is a person's own words, so
    `intent`, `confidence_score` and `ai_generated` stay unset — which is also what keeps this
    path out of `messages.intent`'s closed-form contract.
    """

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
        now: datetime,
    ) -> Message:
        conversation = await self._conversations.get(tenant_id, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError()
        if conversation.status is ConversationStatus.CLOSED:
            raise ConversationClosedError(
                "Conversation is closed and accepts no further messages"
            )

        sender_type = SENDER_TYPE_BY_ROLE.get(actor_role)
        if sender_type is None:
            # A role with no entry is a 403 before it reaches here (D17 gives
            # `MANAGE_CONVERSATIONS` to `PROPERTY_MANAGER` alone), so this is the ceiling for
            # a caller with no HTTP in front of it — and it refuses rather than inventing a
            # `sender_type`, which is the one thing D18 will not do.
            raise MessagingValidationError(
                f"Role {actor_role.value} has no sender type for a conversation message"
            )

        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            sender_type=sender_type,
            content=content,
            created_at=now,
            sender_user_id=actor_user_id,
        )
        await self._messages.add(tenant_id, message)

        conversation.register_message(now=now)
        if conversation.escalation_status is ConversationEscalationStatus.PENDING_HUMAN:
            # Answering *is* taking over (D4). Written as a guarded call rather than a
            # `try/except` because, unlike the escalation of R5.4, there is no invariant being
            # deferred to here: the conversation may legitimately not be waiting for anyone.
            conversation.take_over(now=now)
        await self._conversations.save(tenant_id, conversation)

        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    conversation=conversation,
                    event_type=TimelineEventType.HUMAN_RESPONSE_SENT,
                    actor_type=TimelineActorType.USER,
                    actor_user_id=actor_user_id,
                    metadata={
                        "conversation_id": str(conversation.id),
                        "message_id": str(message.id),
                    },
                    now=now,
                )
            ),
        )

        await self._uow.commit()
        return message


# --- The inbox (R7.1, R7.3, R7.4) ---------------------------------------------------------


class CreateConversationUseCase:
    """Open a conversation, having first proved its anchors belong to the acting tenant.

    **The resolution is the point, and it is not decoration.** `ConversationRepository.add`
    states as a precondition that `property_id` and `reservation_id` "must already have been
    resolved *within* `tenant_id`", because the foreign keys of `conversations` are global
    rather than composite with the tenant: Postgres would happily anchor a conversation of
    tenant A to a property of tenant B, and the adapter cannot detect it without a query of
    its own. This is the only route that takes those ids **from a client**, so this is where
    the precondition has to be honoured — and every `TimelineEvent` the conversation ever
    produces carries `property_id` forward, so getting it wrong is not recoverable by a later
    read. Raised by the tenancy panel of sections 5-6.

    **`PORTAL` is refused outright** (`guest-portal-messaging` R3.7, D14): that thread is
    opened by the guest's first message and by nothing else, so this route — the one place a
    client names the channel — is where the door is closed.
    """

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        guests: GuestRepository,
        uow: UnitOfWork,
    ) -> None:
        self._conversations = conversations
        self._properties = properties
        self._reservations = reservations
        self._guests = guests
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        channel: ConversationChannel,
        reservation_id: uuid.UUID | None,
        guest_id: uuid.UUID | None,
        language: str,
        now: datetime,
    ) -> Conversation:
        """`property_id` is required by the signature, which is where D19 lands at this layer;
        `Conversation.__post_init__` is where it lands for every other caller.

        **All three foreign keys are resolved within the tenant before anything is written**,
        and none of the three checks is decoration. `conversations` references `properties`,
        `reservations` and `guests` with plain global foreign keys rather than keys composite
        with `tenant_id`, so the database will happily accept a conversation of tenant A
        anchored to a row of tenant B. This is the only route that takes all three ids **from
        a client**, which makes it the only place the check can live.

        `guest_id` was missed in the first implementation and the review of 2026-08-16 caught
        it: besides the cross-tenant reference itself, `guests.id` is referenced with
        `ondelete="RESTRICT"`, so a dangling anchor also pins the other tenant's guest row
        against deletion — a failure they cannot explain or clear from their own data.
        """
        if channel is ConversationChannel.PORTAL:
            # D14, R3.7. `PORTAL` became a valid member of the enum in section 1, which is
            # exactly what made this route able to open one without anybody changing it — and
            # the guest would then see, on their own page, a thread they never started. The
            # partial unique index does not help: it forbids the *second* portal thread for a
            # stay, not the first.
            #
            # Refused in the use case and not in the request schema because "who may open a
            # portal thread" is a business rule, and `steering/backend-architecture.md` does
            # not let those live in `api/`. Same shape as `RecordHumanReplyUseCase` refusing a
            # role with no `sender_type` rather than inventing one.
            raise MessagingValidationError(
                "A PORTAL conversation is opened by the guest's first message and by no "
                "other route"
            )
        if await self._properties.get(tenant_id, property_id) is None:
            raise MessagingValidationError("Property does not exist")
        if (
            reservation_id is not None
            and await self._reservations.get(tenant_id, reservation_id) is None
        ):
            raise MessagingValidationError("Reservation does not exist")
        if guest_id is not None and await self._guests.get(tenant_id, guest_id) is None:
            raise MessagingValidationError("Guest does not exist")

        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel=channel,
            created_at=now,
            updated_at=now,
            property_id=property_id,
            reservation_id=reservation_id,
            guest_id=guest_id,
            language=language,
        )
        await self._conversations.add(tenant_id, conversation)
        await self._uow.commit()
        return conversation


class ListConversationsUseCase:
    def __init__(self, *, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: ConversationFilters,
        page: int,
        per_page: int,
    ) -> ConversationPage:
        return await self._conversations.list(
            tenant_id, filters, page=page, per_page=per_page
        )


class GetConversationUseCase:
    def __init__(self, *, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    async def execute(
        self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await self._conversations.get(tenant_id, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation


class ListMessagesUseCase:
    """The thread. Resolves the conversation first so an unknown id and another tenant's id
    both answer 404 rather than an empty page — an empty page would confirm the conversation
    exists and is simply quiet (R1.5)."""

    def __init__(
        self, *, conversations: ConversationRepository, messages: MessageRepository
    ) -> None:
        self._conversations = conversations
        self._messages = messages

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        page: int,
        per_page: int,
    ) -> MessagePage:
        if await self._conversations.get(tenant_id, conversation_id) is None:
            raise ConversationNotFoundError()
        return await self._messages.list_for_conversation(
            tenant_id, conversation_id, page=page, per_page=per_page
        )


class EscalateConversationUseCase:
    """Manual escalation (R7.1). The timeline actor is `USER` and not `AI`, which is the whole
    difference from the pipeline's escalation — and the reason `_timeline_event` takes the
    actor rather than deriving it from the event type."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._conversations = conversations
        self._timeline = timeline
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        now: datetime,
    ) -> Conversation:
        conversation = await self._conversations.get(tenant_id, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError()

        # No `try/except` here: a manual escalation of an already-escalated conversation is a
        # 409 the caller should see, unlike the pipeline's, where the guest's message must
        # still be processed.
        conversation.escalate(now=now)
        await self._conversations.save(tenant_id, conversation)
        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                _timeline_event(
                    conversation=conversation,
                    event_type=TimelineEventType.AI_ESCALATED_TO_HUMAN,
                    actor_type=TimelineActorType.USER,
                    actor_user_id=actor_user_id,
                    metadata={"conversation_id": str(conversation.id)},
                    now=now,
                )
            ),
        )
        await self._uow.commit()
        return conversation


class ResolveConversationUseCase:
    def __init__(
        self, *, conversations: ConversationRepository, uow: UnitOfWork
    ) -> None:
        self._conversations = conversations
        self._uow = uow

    async def execute(
        self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, now: datetime
    ) -> Conversation:
        """`resolve` closes the escalation with it when there is one (D4), so there is no
        second call to make and no order to get wrong."""
        conversation = await self._conversations.get(tenant_id, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError()

        conversation.resolve(now=now)
        await self._conversations.save(tenant_id, conversation)
        await self._uow.commit()
        return conversation
