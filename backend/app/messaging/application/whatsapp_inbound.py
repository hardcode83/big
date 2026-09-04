"""The inbound WhatsApp message's identity resolution and its one entry into the pipeline.

`whatsapp-cloud-adapter` R4.1-R4.5, R5.1, R5.2; design D4, D5, D6.

**Shaped after `PostPortalGuestMessageUseCase`** (`application/portal.py`) and for the same
reason: it does two things and neither of them is persisting a message. It resolves *which*
conversation the message belongs to, and it hands the content to
`ProcessInboundGuestMessageUseCase`, which stays the owner of the nine steps and of the single
`commit()`. There is no `Message(` in this module and a test asserts it — that is what makes
R5.2's "respetar, **sin duplicarlas**, las reglas ya existentes de esa ingesta" structural
rather than a promise, and it keeps the rule-11 census of use cases that write
`messages.content` at the two in `messaging/application/use_cases.py`.

**R5.1's "`sender_type`/canal marcados como `WHATSAPP`" is satisfied structurally, not by a
parameter.** `MessageSenderType` has no WhatsApp member — it names *who* wrote (the pipeline
writes `GUEST`) — and the channel is a property of the conversation, which
`ensure_whatsapp` creates as `ConversationChannel.WHATSAPP` and nothing here can override.

**What this module does not do**, so section 7 knows what is still its own:

- it does not resolve the tenant. `tenant_id` and `default_property_id` arrive already
  resolved from the `WhatsAppPhoneNumberModel` row that the message's `phone_number_id`
  matched (R4.1, D3, D8). Nothing here reads any field of the message to decide either — R4.1
  forbids it, and the parameters are the enforcement: there is no repository in this class
  through which a body could name a tenant;
- it does not verify the signature, deduplicate by `provider_message_id`, or decide the HTTP
  status (section 7, R3.2-R3.5);
- it does not commit. It shares the caller's `AsyncSession`, so the conversation resolved here
  and the message, timeline event and notification written there land in one transaction,
  committed by the pipeline's own `UnitOfWork`.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.guests.domain.repositories import GuestRepository
from app.guests.domain.value_objects import normalize_phone_e164
from app.messaging.application.use_cases import ProcessInboundGuestMessageUseCase
from app.messaging.domain.entities import Conversation, Message
from app.messaging.domain.exceptions import InvalidConversationTransitionError
from app.messaging.domain.language import detect_language
from app.messaging.domain.repositories import ConversationRepository
from app.messaging.domain.value_objects import InboundMessageActor, InboundWhatsAppMessage
from app.reservations.domain.repositories import ReservationRepository

logger = logging.getLogger(__name__)

#: The language a WhatsApp thread is born in when its first message does not say.
#:
#: The portal's `DEFAULT_PORTAL_LANGUAGE` for the same reason and by the same route
#: (`detect_language` over the same text the pipeline will detect again, so the thread and its
#: first message agree by construction rather than by a second criterion).
#:
#: **Not `GuestSummary.preferred_language`**, tempting as it is: that field is not validated
#: against `SUPPORTED_LANGUAGES` anywhere, and `Conversation.__post_init__` refuses a language
#: outside it — so a guest row carrying `"fr"` would turn a guest's message into a refused
#: conversation. It is also unavailable in three of the four resolution branches below, where
#: there is no single guest.
DEFAULT_WHATSAPP_LANGUAGE = "es"


@dataclass(frozen=True)
class _Anchors:
    """What one inbound message resolved to: the three anchors, and whether a person is needed.

    A value object rather than a 4-tuple so the call site cannot silently swap `property_id`
    and `reservation_id` — both are `uuid.UUID`, and the mistake would be invisible.

    `property_id` is **not** optional: `Conversation.__post_init__` refuses a conversation
    without a property (`guest-portal-messaging` D19, because `TimelineEventFactory` cannot
    build any of the four mandatory timeline events without one), so every branch resolves a
    real property — the stay's when there is exactly one stay, and the tenant's
    `default_property_id` otherwise (D4 supersession of 2026-09-02).
    """

    guest_id: uuid.UUID | None
    property_id: uuid.UUID
    reservation_id: uuid.UUID | None
    needs_human: bool


class PostWhatsAppInboundMessageUseCase:
    """One authenticated WhatsApp message in, one message through the existing pipeline out.

    The order, and why each step is where it is:

    1. **normalise the sender's number** (R4.2, section 3's `normalize_phone_e164`). Meta's
       `from` is bare digits with no `+` — a full E.164 number with the country code baked in
       — and the normaliser's bare-number branch recognises only a 9-digit *national* number,
       so the `+` is prepended here. Without it every real message would fail to normalise and
       every guest would look unknown;
    2. **look the guest up by that number, within the tenant** (R4.2, D5). Plural on purpose:
       `find_by_phone` returns every match because R4.4 needs the count;
    3. **resolve the stay** when there is exactly one guest (R4.2, D5), through
       `find_active_for_guest` with the *message's* date;
    4. **`ensure_whatsapp`** with whatever the three anchors resolved to (R4.5, D4). The
       existing thread for that guest and property is reused rather than duplicated, by the
       partial unique index behind that method rather than by a read here;
    5. **escalate to a person when the match was ambiguous** (R4.4), directly on the entity;
    6. **hand the content to `ProcessInboundGuestMessageUseCase`** (R5.1), naming the actor by
       the number the webhook resolved (R4.2, D6).

    **Nothing is ever discarded.** R4.3 forbids it, and there is no branch here that returns
    without a message: an unrecognised number, an unparseable number, no active stay and an
    ambiguous match all still produce a conversation on the tenant's default property and a
    message in it, which is what "visible a un operador" means once the manager's inbox is the
    surface (R7.3's filters read the two axes step 5 writes).
    """

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        guests: GuestRepository,
        reservations: ReservationRepository,
        pipeline: ProcessInboundGuestMessageUseCase,
    ) -> None:
        self._conversations = conversations
        self._guests = guests
        self._reservations = reservations
        self._pipeline = pipeline

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        default_property_id: uuid.UUID,
        inbound_message: InboundWhatsAppMessage,
        now: datetime,
    ) -> Message:
        """Resolve, open or reuse the thread, and run the pipeline. Never commits.

        `tenant_id` and `default_property_id` are both **already resolved** from the
        `phone_number_id` association (R4.1, D3, D8) — never from `inbound_message`, whose
        every field except `business_phone_number` is content the sender controls.

        `now` is the clock for what is written (timestamps, transitions);
        `inbound_message.received_at` is what the stay window is asked about, because a
        webhook redelivered or a Celery task retried hours later must still ask "was there a
        stay when the guest wrote", not "…when we got round to it".
        """
        # The `+` is not cosmetic — see step 1 of the class docstring. `sender_phone` is
        # refused blank by `InboundWhatsAppMessage`, so this is never a bare `"+"`.
        presented_phone = f"+{inbound_message.sender_phone}"
        resolved_phone = normalize_phone_e164(presented_phone)

        anchors = await self._resolve(
            tenant_id,
            default_property_id=default_property_id,
            resolved_phone=resolved_phone,
            inbound_message=inbound_message,
        )

        conversation = await self._conversations.ensure_whatsapp(
            tenant_id,
            guest_id=anchors.guest_id,
            property_id=anchors.property_id,
            reservation_id=anchors.reservation_id,
            # Applied only when the row is created; on the `DO NOTHING` branch the thread
            # keeps the language its first message decided, exactly as `ensure_portal`.
            language=detect_language(inbound_message.text) or DEFAULT_WHATSAPP_LANGUAGE,
            # D4's addendum: the number the guest wrote **to**, fixed for the life of the
            # thread so a reply always leaves from where the conversation started.
            business_phone_number=inbound_message.business_phone_number,
            now=now,
        )

        if anchors.needs_human:
            await self._escalate_for_ambiguity(tenant_id, conversation, now)

        return await self._pipeline.execute(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            content=inbound_message.text,
            # D6's third identity. The normalised number when it normalised, and otherwise
            # the number as it arrived: the actor names **what the webhook authenticated
            # by**, and an unparseable number is still that. `resolved_phone` is `None` only
            # on the branch where no guest was looked up at all, so this never disagrees with
            # the number the lookup used.
            actor=InboundMessageActor(resolved_phone=resolved_phone or presented_phone),
            now=now,
        )

    # --- Steps 1-3: who wrote, and about which stay (R4.2, R4.3, R4.4, D5) ----------------

    async def _resolve(
        self,
        tenant_id: uuid.UUID,
        *,
        default_property_id: uuid.UUID,
        resolved_phone: str | None,
        inbound_message: InboundWhatsAppMessage,
    ) -> _Anchors:
        """The four branches of R4.3/R4.4, and the one that resolves a real stay.

        | guests matched | active stays | guest_id | property_id | escalates |
        |---|---|---|---|---|
        | 0 (or no usable number) | — | `None` | default | no |
        | 2+ | — | `None` | default | **yes** |
        | 1 | 0 | the guest | default | no |
        | 1 | 1 | the guest | the stay's | no |
        | 1 | 2+ | the guest | default | **yes** |

        **`guest_id` stays `None` on both ambiguous branches**, and that is R4.4's "en vez de
        adivinar": with two guests sharing a number, naming either one is the guess the
        requirement forbids, and `conversations.guest_id` is what a manager, the outbound
        adapter and `_recipient_contact` all read to decide who they are talking to.

        **A number that does not normalise is treated as no match** rather than looked up
        raw. `find_by_phone` compares for equality against the E.164 form `guests.phone` is
        stored in, so a raw lookup could only ever match by accident; failing closed to R4.3
        is what the normaliser's own contract asks for ("fails closed — returns `None`, never
        a guess").
        """
        matches = (
            await self._guests.find_by_phone(tenant_id, resolved_phone)
            if resolved_phone is not None
            else []
        )

        if len(matches) != 1:
            # R4.3 (nobody) and R4.4 (more than one) land on the same anchors and differ only
            # in whether a person is called — written as one branch because inventing an
            # association is forbidden in both, and the tenant's default property is what
            # makes the row constructible at all (D4 supersession).
            return _Anchors(
                guest_id=None,
                property_id=default_property_id,
                reservation_id=None,
                needs_human=len(matches) > 1,
            )

        guest = matches[0]
        stays = await self._reservations.find_active_for_guest(
            tenant_id, guest.id, on_date=inbound_message.received_at.date()
        )
        if len(stays) == 1:
            stay = stays[0]
            return _Anchors(
                guest_id=guest.id,
                property_id=stay.property_id,
                reservation_id=stay.id,
                needs_human=False,
            )

        # No active stay (R4.3: the guest is known, the stay is not) or several (R4.4). Either
        # way there is no single stay to attach, so `reservation_id` stays `None` and the
        # thread hangs off the tenant's default property.
        return _Anchors(
            guest_id=guest.id,
            property_id=default_property_id,
            reservation_id=None,
            needs_human=len(stays) > 1,
        )

    # --- Step 5: R4.4's escalation ---------------------------------------------------------

    async def _escalate_for_ambiguity(
        self, tenant_id: uuid.UUID, conversation: Conversation, now: datetime
    ) -> None:
        """Hand the thread to a person **before** the pipeline runs (R4.4, D5).

        `Conversation.escalate` and not a status the AI classifier derived: D5 says it
        outright — "surfaced as a `ConversationEscalationStatus` set directly rather than run
        through the AI classifier, since there is nothing to classify yet". The ambiguity is
        about *whose* message this is, which no classifier of the text can answer.

        **Before, not after, and that ordering is the requirement.** `escalate` moves the
        escalation axis to `PENDING_HUMAN`, which is what `Conversation.is_handed_over`
        answers `True` to — and the pipeline asks exactly that before letting the AI reply.
        Escalating afterwards would let the AI answer a sender we just declared unidentified.

        **It does not notify, and does not duplicate the pipeline's escalation.** The
        notification lives in `ProcessInboundGuestMessageUseCase._escalate`, whose own policy
        may fire on this same message; when it does, it finds the conversation already handed
        over, logs `messaging.escalation_already_pending` and sends nothing — which is R5.4's
        "NEVER SHALL emitir una segunda notificación… mientras siga `PENDING_HUMAN`" holding
        by itself. Copying `_notify_managers` here would be the duplication R5.2 forbids; what
        an ambiguity escalation does surface is the two inbox axes R7.3 filters on. A
        notification of its own would be a new requirement, and it is recorded as such in the
        change's Implementation Notes rather than invented here.

        **The refusal is absorbed, and there is exactly one path.** The transition table
        refuses `escalate` for the two states in which this method has nothing left to do: a
        thread a person already holds (`PENDING_HUMAN`/`HUMAN_HANDLING` — already escalated,
        and R5.4 forbids a second handover while it lasts) and a `RESOLVED` one (the table
        admits `OPEN` alone as an origin, and the pipeline is about to reopen it and re-run
        its own policy). Neither is worth costing the guest their message: R4.3 forbids losing
        it and Meta redelivers on any non-2xx, so raising here would retry the same message
        forever. An `if conversation.is_handed_over()` before the call would be a third
        spelling of the same table — and an unreachable branch, since the `except` below
        already covers it — so the table is the only thing that decides.
        """
        try:
            conversation.escalate(now=now)
        except InvalidConversationTransitionError:
            logger.info(
                "messaging.whatsapp_ambiguous_match_not_escalated",
                # No phone number and no message text: rule 11 of `steering/security.md`, and
                # this line is written on a route the open internet can reach.
                extra={
                    "tenant_id": str(tenant_id),
                    "conversation_id": str(conversation.id),
                    "conversation_status": conversation.status.value,
                },
            )
            return
        await self._conversations.save(tenant_id, conversation)
