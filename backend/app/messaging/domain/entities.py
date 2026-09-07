import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Mapping

from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    MessageIntent,
    MessageSenderType,
)
from app.messaging.domain.exceptions import (
    InvalidConversationTransitionError,
    MessagingValidationError,
)
from app.messaging.domain.value_objects import InboundWhatsAppMessage, MessageMetadata
from app.tenants.domain.value_objects import SUPPORTED_LANGUAGES

#: The longest message body this system accepts (R7.6, design D21).
#:
#: `ASSUMPTION`, confirmed in the design gate of 2026-08-16. WhatsApp admits 4096 and the
#: real limits of Beds24 are not measured; 2000 (the ceiling of `owner_approvals
#: .response_notes`) is short for a phone transcript and 10000 is generous for a rule-11
#: sink with no measured need. `beds24-messaging-adapter` adjusts it with data.
#:
#: It lives in `domain/` because it is applied **twice on purpose** (D21): the Pydantic
#: schema rejects an over-long body before the use case ever runs, and `Message` below is the
#: only ceiling a caller with no HTTP in front of it ever meets. `messages.content` is `TEXT`
#: with no database limit, so there is no migration behind this number.
MAX_MESSAGE_CONTENT_LENGTH = 4000


@dataclass
class Conversation:
    id: uuid.UUID
    tenant_id: uuid.UUID
    channel: ConversationChannel
    created_at: datetime
    updated_at: datetime
    property_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    guest_id: uuid.UUID | None = None
    status: ConversationStatus = ConversationStatus.OPEN
    language: str = "es"
    last_message_at: datetime | None = None
    ai_enabled: bool = True
    escalation_status: ConversationEscalationStatus = ConversationEscalationStatus.NONE

    #: The tenant's own WhatsApp number the guest wrote **to** — Meta's `phone_number_id`,
    #: never the display number (`whatsapp-cloud-adapter` D4 addendum, 2026-09-02).
    #:
    #: Set once, by `ConversationRepository.ensure_whatsapp` at creation time, and never
    #: rewritten: a reply always leaves from the number the thread was opened on, even after
    #: the tenant's configured number changes. That "never rewritten" is structural rather
    #: than documented — no method of this entity touches it, and the field has no setter, so
    #: the only writer is the `INSERT` (`steering/backend-architecture.md`: entities mutate
    #: only through their own methods). Retargeting a live thread to a new number is out of
    #: scope, a follow-up if it ever matters.
    #:
    #: `None` for every other channel, refused in `__post_init__`: the topology is one shared
    #: Meta App with one dedicated number per tenant (D1 addendum), so this column means
    #: nothing on a `PORTAL`, `EMAIL`, `MANUAL` or `PHONE_TRANSCRIPT` row and a value there
    #: would be a number nobody can reply from.
    business_phone_number: str | None = None

    #: The legal moves of the **escalation** axis, as `operation -> (origins, destination)`
    #: (R5.3, design D4).
    #:
    #: `escalate` accepting nothing but `NONE` is the load-bearing row: it is what makes R5.4
    #: true — "NEVER SHALL emitir una segunda notificación de escalación por la misma
    #: conversación mientras siga `PENDING_HUMAN`" — without a single `if` in the pipeline.
    #: D20 chose it deliberately over checking the status in the use case, because the same
    #: check would then have to exist in `POST /escalate` as well, and we know how that ends.
    _ESCALATION_TRANSITIONS: ClassVar[
        Mapping[
            str,
            tuple[frozenset[ConversationEscalationStatus], ConversationEscalationStatus],
        ]
    ] = {
        "escalate": (
            frozenset({ConversationEscalationStatus.NONE}),
            ConversationEscalationStatus.PENDING_HUMAN,
        ),
        "take_over": (
            frozenset({ConversationEscalationStatus.PENDING_HUMAN}),
            ConversationEscalationStatus.HUMAN_HANDLING,
        ),
        # `PENDING_HUMAN` is an origin **directly** (D4): a manager may close without ever
        # having declared she was taking over, and R7.1 gives no route for that step.
        "resolve_escalation": (
            frozenset(
                {
                    ConversationEscalationStatus.PENDING_HUMAN,
                    ConversationEscalationStatus.HUMAN_HANDLING,
                }
            ),
            ConversationEscalationStatus.RESOLVED,
        ),
    }

    #: The legal moves of the **conversation** axis (R5.3, design D4).
    #:
    #: Two tables and not one, because these are two enums PRD §7.14 declares separately and
    #: which move for different reasons: `status` is what the inbox sorts and filters,
    #: `escalation_status` is the state of the handover to a person. A combined table would
    #: have to enumerate the cartesian product and would hide *which* axis refused a move.
    #:
    #: `CLOSED` appears as an origin and never as a destination: D4 records that this change
    #: gives it no writer rather than inventing a route for it.
    _STATUS_TRANSITIONS: ClassVar[
        Mapping[str, tuple[frozenset[ConversationStatus], ConversationStatus]]
    ] = {
        "escalate": (
            frozenset({ConversationStatus.OPEN}),
            ConversationStatus.ESCALATED,
        ),
        "resolve": (
            frozenset({ConversationStatus.OPEN, ConversationStatus.ESCALATED}),
            ConversationStatus.RESOLVED,
        ),
        "reopen": (
            frozenset({ConversationStatus.RESOLVED}),
            ConversationStatus.OPEN,
        ),
    }

    def __post_init__(self) -> None:
        """A conversation is about a stay, and a stay happens in a home (D19).

        Refused here and **not** by a `NOT NULL` migration, which is the whole of D19: the
        restriction belongs to this change, and the column stays nullable so
        `beds24-messaging-adapter` can still decide what to do with a conversation the PMS
        hands over before its property is resolved.

        The reason it is refused at all is hard rather than aesthetic: `TimelineEventFactory`
        requires `property_id` as a non-null UUID, so a conversation without one cannot
        produce any of the four timeline events R4.1, R4.4, R4.5 and R5.2 declare mandatory.
        """
        if self.property_id is None:
            raise MessagingValidationError(
                "A conversation must belong to a property: without one it can produce none "
                "of the timeline events R4.1, R4.4, R4.5 and R5.2 require (design D19)"
            )
        if (
            self.business_phone_number is not None
            and self.channel is not ConversationChannel.WHATSAPP
        ):
            # The field is the WhatsApp number the thread was opened on; on any other channel
            # there is no such number, so a value here describes a reply route that does not
            # exist. Refused at construction rather than only at the one writer, which is what
            # makes it true for `_to_conversation`'s read-back too.
            raise MessagingValidationError(
                "business_phone_number belongs to a WHATSAPP conversation and to no other "
                "channel (whatsapp-cloud-adapter D4)"
            )
        if self.business_phone_number is not None and not self.business_phone_number.strip():
            raise MessagingValidationError(
                "business_phone_number is the Meta phone_number_id the thread was opened "
                "on, never blank"
            )
        if self.language not in SUPPORTED_LANGUAGES:
            # R4.8 makes this field the fallback when detection cannot decide, so an
            # unsupported value here has no template to answer from and would reach an
            # external AI provider inside `ConversationContext`. Checked at the source
            # rather than only where it is read. Raised by the security panel of sections 1-2.
            raise MessagingValidationError(
                f"Conversation language must be one of {', '.join(SUPPORTED_LANGUAGES)}"
            )

    def _check_escalation(self, operation: str) -> ConversationEscalationStatus:
        origins, target = self._ESCALATION_TRANSITIONS[operation]
        if self.escalation_status not in origins:
            raise InvalidConversationTransitionError(
                f"Conversation escalation cannot move from {self.escalation_status.value} "
                f"to {target.value}"
            )
        return target

    def _check_status(self, operation: str) -> ConversationStatus:
        origins, target = self._STATUS_TRANSITIONS[operation]
        if self.status not in origins:
            raise InvalidConversationTransitionError(
                f"Conversation cannot move from {self.status.value} to {target.value}"
            )
        return target

    def escalate(self, *, now: datetime) -> None:
        """Hand the conversation to a person (R5.2, R5.3).

        **Both axes are checked before either is written.** They move together, so a check
        made halfway would be able to leave a conversation `ESCALATED` with
        `escalation_status = NONE` — visibly on fire in the inbox and in nobody's queue.
        """
        escalation_target = self._check_escalation("escalate")
        status_target = self._check_status("escalate")

        self.escalation_status = escalation_target
        self.status = status_target
        self.updated_at = now

    def take_over(self, *, now: datetime) -> None:
        """A person answers, and thereby takes the handover (R4.5, design D4).

        `status` is untouched: the conversation is still `ESCALATED` — what changed is who
        is holding it, which is the whole distinction between the two axes.
        """
        self.escalation_status = self._check_escalation("take_over")
        self.updated_at = now

    def resolve(self, *, now: datetime) -> None:
        """Close the conversation (R7.1), closing its escalation with it if it had one.

        The escalation axis follows rather than being resolved by a route of its own: R7.1
        declares no endpoint for `resolve_escalation` alone, so `POST /resolve` is the only
        thing that could ever move it out of `PENDING_HUMAN`/`HUMAN_HANDLING`. A conversation
        resolved with its escalation left pending would sit for ever in whatever list asks
        for pending handovers.
        """
        status_target = self._check_status("resolve")

        if self.escalation_status in self._ESCALATION_TRANSITIONS["resolve_escalation"][0]:
            self.escalation_status = self._check_escalation("resolve_escalation")
        self.status = status_target
        self.updated_at = now

    def reopen(self, *, now: datetime) -> None:
        """A guest writes again into a resolved conversation (D11 step 1).

        **Reopening clears a resolved escalation**, and that is derived from D4 rather than
        written in it. `escalate` accepts only `NONE` as an origin — the mechanism of R5.4 —
        so a conversation reopened while carrying `escalation_status = RESOLVED` could never
        escalate again: a guest typing "there is smoke" into a reopened thread would raise
        instead of reaching a person. Restarting the escalation lifecycle is what keeps R5.1
        reachable without widening `escalate`'s origins and thereby losing R5.4.
        """
        status_target = self._check_status("reopen")

        if self.escalation_status is ConversationEscalationStatus.RESOLVED:
            self.escalation_status = ConversationEscalationStatus.NONE
        self.status = status_target
        self.updated_at = now

    def is_handed_over(self) -> bool:
        """Whether a person already has this conversation (`PENDING_HUMAN`/`HUMAN_HANDLING`).

        **On the entity so the two readers cannot diverge** (`guest-portal-messaging` D9). The
        pipeline asks it to decide whether the AI should still answer; the portal's thread
        reader asks it to decide whether to tell the guest a person will reply (R2.3). Those
        are the same question about the same axis, and while it was a private helper of
        `application/use_cases.py` the second reader would have had to restate the pair of
        members — the shape in which the two answers drift.

        It is a rule about a `Conversation`, so it belongs here rather than in `application/`,
        by the same reading of `steering/backend-architecture.md` that moved `contact_kind_for`
        into `domain/`.

        **`RESOLVED` is not "handed over"**: the escalation is finished, and a new message
        reopens the conversation with the axis back at `NONE` (D4), so the AI answers again —
        which is right, because that is a new problem.
        """
        return self.escalation_status in (
            ConversationEscalationStatus.PENDING_HUMAN,
            ConversationEscalationStatus.HUMAN_HANDLING,
        )

    def register_message(self, *, now: datetime) -> None:
        """Record that a message landed (R1.4).

        A method of the entity and not a `setattr` from the use case (D11), because
        `last_message_at` is the key the inbox sorts by: the whole point of R1.4 is that the
        listing never has to walk `messages`, and a writer that forgot this would produce an
        inbox that is quietly wrong rather than one that fails.
        """
        self.last_message_at = now
        self.updated_at = now


@dataclass(frozen=True)
class Message:
    """One row of `messages`, and **frozen**, unlike `Conversation` above.

    The asymmetry is the point. A conversation has a lifecycle — it escalates, is taken
    over, resolves and reopens — while a message is a thing that was said: `messages` is
    append-only and nothing in this change edits a row after writing it. Freezing turns that
    from a convention into a property, and it is what makes the three rule-11 closures below
    total rather than construction-only: `message.intent = <raw model output>` is the natural
    way to write "record the classification we just got", it would put free text into a
    `VARCHAR(100)` the census calls closed, and on a mutable dataclass nothing would stop it.
    The security panel of sections 1-2 found exactly that gap.

    The one place it bites is the delivery outcome of R6.5, which used to be described as
    "persist the message, then send, then annotate the failure". Under the single transaction
    of R4.7 those are the same durability guarantee — nothing is durable until the one commit
    — so the pipeline sends first and builds the row once, with its outcome already in it.
    """

    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: MessageSenderType
    content: str
    created_at: datetime
    sender_user_id: uuid.UUID | None = None
    language: str | None = None
    ai_generated: bool = False
    confidence_score: Decimal | None = None
    intent: str | None = None
    metadata: MessageMetadata | None = None

    def __post_init__(self) -> None:
        """The three contracts `messages` inherits from rule 11 of `steering/security.md`.

        **`intent` degrades to `UNKNOWN` and is never stored as given** (R3.4, D16). The
        column is a `VARCHAR(100)` that *looks* like an enum and is not one — the same
        appearance that got `webhook_events.event_type` left out of the census — so the
        closed form is enforced where the value is built rather than by trusting every caller
        to pass a member. `None` is not an unrecognised value: a human reply is never
        classified, and it stays unclassified.

        **`metadata` is a `MessageMetadata`, never a `dict`** (R3.5, D15). D15 puts that
        obligation on the repository signature; carrying a bare `dict` on the aggregate would
        have left the closed key set true of the value object and false of the column.

        **`content` is refused above `MAX_MESSAGE_CONTENT_LENGTH`** (R7.6, D21). This is not
        "rejecting before reading the body" — only `MaxBodySizeMiddleware` does that, and
        rule 14 of `steering/security.md` is explicit about not presenting one as the other.
        It is the ceiling for a caller with no HTTP in front of it. Characters, not bytes:
        the column is `TEXT` with no byte limit, and the number is a product decision about
        how long a message may be (D21), not a storage constraint.
        """
        if len(self.content) > MAX_MESSAGE_CONTENT_LENGTH:
            raise MessagingValidationError(
                f"Message content exceeds {MAX_MESSAGE_CONTENT_LENGTH} characters"
            )
        if self.metadata is not None and not isinstance(self.metadata, MessageMetadata):
            raise MessagingValidationError(
                "metadata must be a MessageMetadata: messages.metadata is a rule-11 sink "
                "with a closed key set (design D15)"
            )
        # The third carrier of a language code, after `Conversation.language` and
        # `ConversationContext.language`. Closed here too because *we* write it — from the
        # outcome of `detect_language` (R4.8) — into a `String(5)` column whose name promises
        # a code, which is the `webhook_events.event_type` shape the census preamble of rule
        # 11 exists for. `None` is a real value: a message nobody detected a language for.
        if self.language is not None and self.language not in SUPPORTED_LANGUAGES:
            raise MessagingValidationError(
                f"Message language must be one of {', '.join(SUPPORTED_LANGUAGES)}, or unset"
            )
        object.__setattr__(self, "intent", _closed_intent(self.intent))


def _closed_intent(intent: object) -> str | None:
    """The value that may reach `messages.intent`: a member's value, or `UNKNOWN`, or nothing.

    `TypeError` is caught alongside `ValueError` because an unhashable payload — a list that
    came off a provider's JSON — must degrade like everything else rather than crash the
    pipeline. Degrading is the behaviour R3.4 asks for; raising would be a second outcome
    nobody declared.
    """
    if intent is None:
        return None
    if isinstance(intent, MessageIntent):
        return intent.value
    try:
        return MessageIntent(intent).value
    except (ValueError, TypeError):
        return MessageIntent.UNKNOWN.value


@dataclass(frozen=True)
class WhatsAppPhoneNumberAssociation:
    """One tenant's `phone_number_id` under the platform's single shared Meta App (section 6).

    `whatsapp-cloud-adapter` R6.1-R6.3, design D3/D8 (mid-run rewrite: Meta admits one
    App/WABA for the whole platform, so this holds an association, not minted material —
    unlike `WebhookEndpoint`, its structural sibling in `app/integrations/domain/entities.py`,
    it carries no secret and no `EncryptedSecret` field at all).

    Frozen, like `WebhookEndpoint`: `AssociateWhatsAppPhoneNumberUseCase` replaces the row
    wholesale rather than mutating it in place, so there is no partially-associated state for
    anything to observe.

    `phone_number_id` is always operator-supplied (R6.1) — never generated here, unlike
    `WebhookEndpoint.token_hash`. `default_property_id` is required rather than
    `uuid.UUID | None`: `ConversationRepository.ensure_whatsapp` (section 5) needs it for the
    branch where a sender resolves to no stay, because `Conversation.property_id` can never be
    `None` (`guest-portal-messaging` D19).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    phone_number_id: str
    display_phone_number: str | None
    default_property_id: uuid.UUID


@dataclass(frozen=True)
class InboundWhatsAppEvent:
    """One authenticated inbound WhatsApp delivery, persisted so a worker can pick it up.

    `whatsapp-cloud-adapter` R3.3, R3.4, R3.5; design D7. The row that survives the queue
    boundary: the receiving route commits it and dispatches `process_inbound_whatsapp_message
    .delay(event_id)`, and the worker reads it back to learn both *who* the message is for and
    *what* it said. Its structural sibling is `app/integrations/domain/entities.py`'s
    `WebhookEvent` — same job, one provider over.

    **Why the row exists at all**, since R3.4 could in principle be satisfied by putting the
    message in the task's arguments: `provider_message_id` has to be persisted anyway for
    R3.5's deduplication, and once the row exists, carrying the message on it instead of
    through the broker keeps the guest's words out of Redis and gives the operator something
    to look at when a delivery goes wrong. `tenant_id` and `default_property_id` ride along so
    the worker never re-reads `whatsapp_phone_numbers` (task 7.2's own instruction).

    **`tenant_id` and `default_property_id` are both `None` or both set, never one of each**,
    and the pair is the schema's record of the R3.3-amended case: a validly signed delivery
    for a `phone_number_id` no tenant has provisioned. That is not an attack and not a
    signature failure — it is an operator's unfinished setup — so the delivery is recorded
    rather than discarded (the same criterion as R4.3) and simply never dispatched. The
    nullable `tenant_id` is deliberate and has exactly one precedent, `webhook_events`, for
    exactly this reason; see `WhatsAppInboundEventModel` for what that costs.

    `processed_at` is what keeps Celery's at-least-once delivery from posting the guest's
    message into the conversation twice. R3.5 is written about the *provider* retrying, and
    the unique index on `provider_message_id` answers that; a redelivered *task* is the same
    outcome by another route, so it is closed here rather than left to be discovered.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    default_property_id: uuid.UUID | None
    message: InboundWhatsAppMessage
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.tenant_id is None) != (self.default_property_id is None):
            # Refused rather than coerced: a row naming a tenant but no property would reach
            # `PostWhatsAppInboundMessageUseCase`, which cannot build a `Conversation` without
            # one (`guest-portal-messaging` D19), and the failure would surface as a worker
            # traceback about a property instead of about this row.
            raise MessagingValidationError(
                "an inbound WhatsApp event names both its tenant and that tenant's default "
                "property, or neither"
            )

    @property
    def is_resolved(self) -> bool:
        """Whether this delivery resolved to a tenant, and is therefore dispatchable.

        A property rather than a second field: the pair above is the fact, and a stored flag
        would be a third thing to keep in step with it.
        """
        return self.tenant_id is not None
