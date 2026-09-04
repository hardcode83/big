"""The persistence ports of `messaging` (R1.1, R1.2; design D2, D3).

**Only the methods this change consumes.** No `delete`, no `search`, no `get(message_id)` —
the discipline `sdd/specs/domain-foundation-ops.md` records as a bet that paid off:
`IncidentRepository` was born with `add` alone and `maintenance` widened it when its own flow
needed `get`/`save`. A one-method port is cheaper to widen than a speculative ten-method one
is to narrow.

Two ports and not one, per `steering/backend-architecture.md`: "No repositorio 'Dios' con
métodos de varios agregados — un repositorio por agregado raíz."

Every method takes `tenant_id` explicitly and returns nothing outside it. For `Conversation`
that parameter is the mechanism and the global loader criteria of `app/core/db.py` are the
net; **for `Message` there is no net at all** — `messages` has no `tenant_id` column, so
`tenant_scoped_classes()` does not select it and `with_loader_criteria` does not cover it.
See `MessageRepository` below.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.messaging.domain.entities import (
    Conversation,
    InboundWhatsAppEvent,
    Message,
    WhatsAppPhoneNumberAssociation,
)
from app.messaging.domain.enums import (
    ConversationEscalationStatus,
    ConversationStatus,
    MessageIntent,
)


@dataclass(frozen=True)
class ConversationFilters:
    """The filters of `GET /conversations`, combined with AND (R7.3, design D17)."""

    status: ConversationStatus | None = None
    escalation_status: ConversationEscalationStatus | None = None
    property_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ConversationPage:
    """One page plus the total the client needs for `total_pages` (PRD §23)."""

    items: tuple[Conversation, ...]
    total: int


@dataclass(frozen=True)
class MessagePage:
    items: tuple[Message, ...]
    total: int


class ConversationRepository(Protocol):
    async def add(self, tenant_id: uuid.UUID, conversation: Conversation) -> None:
        """Append a conversation for the acting tenant. Never commits — the use case owns the
        transaction (R4.7).

        **Precondition the caller must honour**: `property_id` and `reservation_id` must
        already have been resolved *within* `tenant_id`. The foreign keys of `conversations`
        are global rather than composite with `tenant_id`, so the database would accept a
        conversation of tenant A anchored to a property of tenant B, and this port cannot
        detect it without a query of its own. The same precondition `IncidentRepository.add`
        and `TimelineEventRepository` state, for the same schema reason.
        """
        ...

    async def get(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        """The conversation, or `None` when it does not exist **within this tenant**.

        Returning `None` rather than raising keeps the 404 decision in the use case. R1.5
        requires "does not exist" and "belongs to someone else" to be indistinguishable, and
        here that is not a discipline but an consequence of the query: both are the same
        `WHERE tenant_id = :tenant_id AND id = :id` returning zero rows.
        """
        ...

    async def save(self, tenant_id: uuid.UUID, conversation: Conversation) -> None:
        """Persist the mutations the entity's own methods made. Never commits.

        Escalating, taking over, resolving and reopening all come through here, so this is
        the write path that has to stay atomic with the message, the timeline event and the
        notification of R4.7.
        """
        ...

    async def ensure_portal(
        self,
        tenant_id: uuid.UUID,
        *,
        reservation_id: uuid.UUID,
        property_id: uuid.UUID,
        guest_id: uuid.UUID | None,
        language: str,
        now: datetime,
    ) -> Conversation:
        """The stay's one `PORTAL` conversation, creating it if this is the first message.

        `guest-portal-messaging` R3.3, R3.4, design D6. **Never commits** — the portal's write
        path runs inside the pipeline's single transaction (R1.4), so this shares its session
        and leaves the commit to it.

        **Idempotent under concurrency, and not by a read-then-write.** Two messages from the
        same guest can arrive at once; an implementation that looked first and inserted second
        would open two threads for one stay under exactly the load a double tap produces. The
        contract is therefore stronger than "returns the conversation": the loser of the race
        must **not** abort its transaction — it blocks until the winner commits, inserts
        nothing, and reads the winner's row back. Both messages then land in the same thread,
        which is what R3.4 asks for.

        `reservation_id` is **mandatory, not `uuid.UUID | None`**, and that is the requirement
        rather than a convenience. The partial unique index behind this method is
        `(tenant_id, reservation_id) WHERE channel = 'PORTAL'`, and PostgreSQL treats NULLs as
        distinct in a unique index — so rows with a null reservation do not collide with each
        other and R3.4 would hold only for stays that happen to carry one. Typing it here is
        what makes the guarantee independent of which caller shows up. Measured on 2026-08-29
        (two such rows both insert); recorded in D6 by the security panel of section 1.

        `language` applies **only when the row is created**. On the `DO NOTHING` branch the
        existing conversation keeps its own, which is what R3.3 asks for: the language was
        decided by the first message and a later one in another language does not restate it.

        **Precondition the caller must honour**, the same one `add` states and for the same
        schema reason: `property_id`, `reservation_id` and `guest_id` must already have been
        resolved *within* `tenant_id`. The foreign keys of `conversations` are global rather
        than composite with the tenant. On the portal path they come from the `GuestSession`,
        which the authoriser resolved from the token's own row, so the precondition is met by
        construction rather than by a check here.
        """
        ...

    async def find_portal(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> Conversation | None:
        """The stay's `PORTAL` conversation, or `None`. **Creates nothing.**

        R2.5: "leer no abre conversación" — a guest opening the page before they have ever
        written must not leave a row behind, so the read path cannot go through
        `ensure_portal`. That is the whole reason these are two methods and not one with a
        flag.

        `None` rather than an exception, like `get` above: the portal turns every failure into
        one constant `404` and an empty thread is a `200`, so the decision belongs to the use
        case.

        Filters on `channel = PORTAL` as well as the tenant, so a stay's `WHATSAPP` or
        `MANUAL` threads are neither returned here nor reachable from the portal (R3.5).
        """
        ...

    async def ensure_whatsapp(
        self,
        tenant_id: uuid.UUID,
        *,
        guest_id: uuid.UUID | None,
        property_id: uuid.UUID,
        reservation_id: uuid.UUID | None,
        language: str,
        business_phone_number: str,
        now: datetime,
    ) -> Conversation:
        """The guest's one `WHATSAPP` thread **for that property**, creating it if new.

        `whatsapp-cloud-adapter` R4.5, design D4. **Never commits**, like `ensure_portal`:
        the inbound WhatsApp path runs inside the same single transaction as the message, the
        timeline event and the notification.

        **Idempotent under concurrency by the same mechanism and not by a read-then-write**:
        `INSERT ... ON CONFLICT DO NOTHING` against the partial unique index
        `uq_conversations_whatsapp_guest_property` — `(tenant_id, guest_id, property_id)
        WHERE channel = 'WHATSAPP'` — so two messages arriving at once land in one thread
        rather than opening two. The loser inserts nothing, is **not** aborted, and reads the
        winner's row back.

        **Keyed by guest *and* property, not by guest alone** (D4, confirmed with the user): a
        returning guest who writes about a second property of the same tenant gets a second
        thread, because a message about property B must not surface property A's unrelated
        history. And not by `reservation_id` like `ensure_portal`, because on this path the
        reservation is frequently unknown (R4.3, R4.4) while the thread must exist anyway.

        **`guest_id` and `reservation_id` are nullable for a requirement each**, not for
        convenience: `guest_id` is `None` when the sender's phone matches no guest (R4.3),
        `reservation_id` when no single active reservation resolves (R4.4). A `NULL` never
        equals another `NULL` in a unique index, so those rows do not dedupe against each
        other and an unresolved sender opens a new row per message — accepted in D4 and in
        the design's Risks rather than papered over with a second index shape. `property_id`
        is **not** among them: it is always resolved, either to the matched stay's property or
        to the tenant's `default_property_id` fallback, so the caller guarantees it non-null
        (design's amended D4/D5).

        `language` applies **only when the row is created**, exactly as in `ensure_portal`:
        the thread's language was decided by its first message.

        `business_phone_number` is Meta's `phone_number_id` for the tenant's own number, the
        one the guest wrote **to** (`InboundWhatsAppMessage.business_phone_number`, D4
        addendum). Written once here and never again — on the conflict branch the existing
        row keeps the number it was opened on, so a reply always leaves from the number the
        conversation started on. It is **required** rather than `str | None`: every caller of
        this method comes from an inbound webhook, which always names the number it arrived
        on, and typing it makes that independent of which caller shows up.

        **Precondition the caller must honour**, the same one `add` and `ensure_portal` state
        and for the same schema reason (the foreign keys of `conversations` are global rather
        than composite with the tenant): `guest_id`, `property_id` and `reservation_id` must
        already have been resolved *within* `tenant_id`. On this path that means resolved
        from `find_by_phone(tenant_id, ...)` and `find_active_for_guest(tenant_id, ...)`,
        both of which take the tenant as a required parameter — and `tenant_id` itself comes
        from the `phone_number_id` association and never from the message body (R4.1).
        """
        ...

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: ConversationFilters,
        *,
        page: int,
        per_page: int,
    ) -> ConversationPage:
        """The inbox listing (R7.3), ordered `last_message_at DESC NULLS LAST, id`.

        `NULLS LAST` is D17's decision and not a default: a conversation just created has no
        `last_message_at`, and letting it sort to the top would push down whatever is on fire.
        The tie-break on `id` is what makes the page boundaries stable — without it two rows
        sharing a timestamp can swap between page 1 and page 2 on consecutive requests.
        """
        ...


class MessageRepository(Protocol):
    """The messages of a conversation, and **never a query over `messages` alone** (R1.2, D3).

    `messages` has no `tenant_id` column — `sdd/specs/domain-foundation-ops.md` fixed that
    schema from PRD §7.15 — so `tenant_scoped_classes()` does not select it and the global
    `with_loader_criteria` of `app/core/db.py` **does not cover it**. Every read here starts
    from a `JOIN` with `conversations` filtered by `tenant_id`, and the write resolves the
    parent within the tenant first. That `JOIN` is not defence in depth: it is the **only**
    isolation mechanism this table has. The literal precedent is
    `SqlAlchemyCleaningPhotoRepository` (`app/cleaning/infrastructure/repositories.py`).
    """

    async def add(self, tenant_id: uuid.UUID, message: Message) -> None:
        """Append a message to a conversation of this tenant. Never commits.

        **Raises `ConversationNotFoundError` when the parent does not resolve within the
        tenant** — the one place a repository of this module raises rather than returning
        `None`, because there is no half-written message to hand back. The adapter inserts
        against **the id it resolved**, not the one the entity carried, so a caller that
        built a `Message` pointing at another tenant's conversation cannot smuggle it in.

        `Message.metadata` is a `MessageMetadata`, never a `dict` (D15), and the adapter
        calls `to_dict()` at the boundary — so `messages.metadata`, a rule-11 sink, has no
        writer through which the guest's words could reach it.
        """
        ...

    async def list_for_conversation(
        self,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        page: int,
        per_page: int,
    ) -> MessagePage:
        """The thread, oldest first, paginated (R7.4).

        Ascending because this is a conversation and people read those forwards — unlike the
        timeline, which is a feed and reads newest-first.
        """
        ...

    async def count_guest_messages(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> int:
        """How many messages the guest has sent in this conversation.

        **A fourth method, added while implementing section 6 and not speculative**: it is the
        only way to fill `ConversationContext.guest_message_count`, which R2.1 and D6 declare
        as part of what an `AIAdapter` is told — and which has to be true, because the object
        goes to something that tomorrow is an external provider. The alternatives were passing
        a number that is not the guest's message count, or dropping a field the design fixes.

        D2 blesses exactly this shape of widening: "`IncidentRepository` nació con `add` y
        `maintenance` lo ensanchó cuando le tocó". What R1.1 forbids is a method with no
        consumer, and this one has its consumer in the same commit.

        Every message, not only the unresolved ones — unlike its sibling below, which answers
        an escalation question. This one answers "how long has this conversation been going",
        which does not reset.
        """
        ...

    async def count_unresolved_guest_messages_with_intent(
        self,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        intent: MessageIntent,
    ) -> int:
        """How many guest messages of this conversation carry that intent (R5.1, D2).

        **The method's name is the question, not "give me the messages"**, and that is
        deliberate: the fifth escalation condition of PRD §13 ("más de 2 mensajes del huésped
        con el mismo intent sin resolución") cannot be answered without it, and a port that
        returned rows would invite the rule to be re-implemented in the use case — where
        `steering/backend-architecture.md` says business rules do not live.

        **"Unresolved" means the conversation is not currently in a terminal status — it does
        not mean "since the last time it was resolved", and the difference is worth stating
        because the obvious reading is the second one.** A message has no resolution of its
        own, and `Conversation` has no `resolved_at`/`reopened_at`: every transition touches
        the same `updated_at`, and giving it one would be a migration this change does not
        make (design "Data & interfaces": no schema change at all). So an implementation with
        these three arguments can only count **every** guest message of the conversation
        carrying that intent, gated on the conversation not being `RESOLVED` or `CLOSED`.

        The consequence, assumed rather than discovered: a conversation resolved once and
        later reopened carries its old count forward, so the third message about anything
        previously discussed escalates sooner than a strict per-episode reading would. That is
        the safe direction — a guest raising the same thing again after we said it was sorted
        is exactly who the AI is failing — and it is the reading this change ships. A future
        change that wants per-episode counting brings the timestamp and a `since` parameter
        with it. Raised by the architecture panel of sections 3-4.
        """
        ...

    async def last_guest_message_at(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> datetime | None:
        """When the guest last wrote — `None` if they never have (`whatsapp-cloud-adapter`
        R2.4, design D2).

        **A fifth method, and the reason `Conversation.last_message_at` does not answer this**:
        that column is touched by every message of the conversation — the guest's, the AI's own
        reply, a manager's — because nothing on `Conversation` distinguishes who wrote last.
        Meta's real WhatsApp customer-service window is strictly "since the customer's last
        message", so reading `last_message_at` would let the AI's own previous reply, or a
        manager's manual one, silently reopen the free-text window without the guest having
        said anything — resolved with the user 2026-09-02.

        Same `sender_type == MessageSenderType.GUEST` filter as `count_guest_messages` and
        `count_unresolved_guest_messages_with_intent` above — mirrors that precedent rather
        than inventing a second way to ask "which messages are the guest's".

        `None` when the guest has never written in this conversation — which
        `DelegatingOutboundAdapter` treats as OUTSIDE the session window, the same as any
        timestamp older than `WHATSAPP_SESSION_WINDOW` (D2, unchanged from section 1).
        """
        ...

class WhatsAppPhoneNumberRepository(Protocol):
    """The number-to-tenant association of section 6 (`whatsapp-cloud-adapter` R6.1-R6.3, D3/D8).

    Its own port and not folded into `ConversationRepository`: this is a different aggregate
    root (`whatsapp_phone_numbers`, not `conversations`), and `steering/backend-architecture.md`
    puts one repository per aggregate root.

    **`find_by_phone_number_id` is the only read that runs without a tenant**, for the same
    reason `WebhookEndpointRepository.find_by_token_hash` does (`app/integrations/domain/
    repositories.py`): section 7's inbound webhook carries no JWT, so `phone_number_id` is what
    resolves the tenant, not something the tenant scopes. Its implementation therefore runs on
    a session that was never marked, enforced by `require_unmarked_session`
    (`tests/test_unscoped_reads.py` holds the census). Every other method here takes
    `tenant_id` explicitly, like the rest of this module's ports.
    """

    async def upsert(
        self, tenant_id: uuid.UUID, association: WhatsAppPhoneNumberAssociation
    ) -> None:
        """Store or replace this tenant's association. Never commits.

        Create-or-replace, unlike `WebhookEndpointRepository.upsert`'s create-refuses/rotate
        pair: there is no secret here whose lifetime a separate "rotate" verb needs to protect
        (R6.3), so one call expresses both "this tenant has no number yet" and "this tenant's
        number changed".

        **Raises `WhatsAppPhoneNumberAlreadyAssociatedError` when `phone_number_id` already
        belongs to a DIFFERENT tenant.** That is a database-level check on the column's own
        unique index, not a prior read: `phone_number_id` is genuinely unique across the whole
        table, not per tenant, so a read-then-write here would leave a real TOCTOU race two
        concurrent tenants could both win (design D8,
        `steering/backend-architecture.md`). The existing association — of the tenant that
        legitimately holds the number — is never touched by a losing call.
        """
        ...

    async def find_for_tenant(
        self, tenant_id: uuid.UUID
    ) -> WhatsAppPhoneNumberAssociation | None:
        """This tenant's association, or `None` if it has never associated one."""
        ...

    async def delete_for_tenant(self, tenant_id: uuid.UUID) -> bool:
        """Remove this tenant's association. `True` if a row existed and was removed.

        Never touches `conversations` — releasing a number does not retroactively unlink the
        threads already opened under it (R6.3's own words: "no toca las conversaciones ya
        creadas bajo él").
        """
        ...

    async def find_by_phone_number_id(
        self, phone_number_id: str
    ) -> WhatsAppPhoneNumberAssociation | None:
        """The association that owns this number, or `None` — section 7's tenant resolution.

        `None` rather than raising, the same reason `WebhookEndpointRepository
        .find_by_token_hash` returns it: absence is an answer, and the caller turns every
        negative into whatever indistinguishable outcome its own design requires.
        """
        ...


class WhatsAppInboundEventRepository(Protocol):
    """The inbound delivery queue of section 7 (R3.3, R3.4, R3.5; design D7).

    Its own port, not folded into `WhatsAppPhoneNumberRepository`: that one holds a tenant's
    configuration and this one holds traffic, which is a different aggregate root
    (`whatsapp_inbound_events`, not `whatsapp_phone_numbers`) and a different lifetime.

    **Two of its three methods run without a tenant, and for two different reasons**, so the
    requirement is stated per method rather than per class — the mistake
    `SqlAlchemyWebhookEventRepository`'s docstring records having made once:

    - `add` writes a row whose `tenant_id` may legitimately be `NULL` (a validly signed
      delivery for an unprovisioned number, R3.3 as amended). It is an `INSERT` by primary
      key, never a scan, so the global filter has nothing to narrow — but the receiving route
      is anonymous and its session is unmarked anyway;
    - `locate_without_tenant_scoping` is a **read**, and the one that cannot be scoped: the
      dispatched task is handed an event id and the row is what tells it which tenant the
      message belongs to. `require_unmarked_session` enforces that rather than letting a
      marked session silently answer `None`;
    - `mark_processed` takes `tenant_id` explicitly, like the rest of this module's ports,
      because by then the tenant is known and the worker is running on a marked session.
    """

    async def add(self, event: InboundWhatsAppEvent) -> bool:
        """Record the delivery, unless its `provider_message_id` is already here. No commit.

        Returns `True` when this call inserted the row and `False` when an identical
        `provider_message_id` already existed — which is R3.5's answer to a provider
        redelivery, and it is the **database** that decides: an `INSERT ... ON CONFLICT DO
        NOTHING` against the unique index, never a prior `SELECT`. Meta redelivers
        concurrently often enough that a read-then-write race here is not theoretical, and
        both winners would post the guest's message twice.

        A `False` return is not an error. The delivery has already been accepted once, so the
        caller answers `202` and dispatches nothing.
        """
        ...

    async def locate_without_tenant_scoping(
        self, event_id: uuid.UUID
    ) -> InboundWhatsAppEvent | None:
        """The event a dispatched task was handed, or `None`.

        **The one read of this port that runs on a session that was never marked.** The task
        receives an id and nothing else (design D7), so the row is what resolves the tenant —
        structurally the same class of read as `WhatsAppPhoneNumberRepository
        .find_by_phone_number_id` and `WebhookEndpointRepository.find_by_token_hash`, and
        declared in the same census (`tests/test_unscoped_reads.py`).

        `None` rather than raising: a task whose row has gone is not a failure worth retrying
        for ever, and the caller decides what to log.
        """
        ...

    async def mark_processed(
        self, tenant_id: uuid.UUID, event_id: uuid.UUID, *, now: datetime
    ) -> bool:
        """Claim the event for this run. `True` only for the run that claimed it. No commit.

        A single conditional `UPDATE ... WHERE processed_at IS NULL`, so two concurrent runs
        of the same task cannot both proceed — Celery's delivery is at-least-once, and the
        outcome of a double run is the guest's message appearing twice in their thread, which
        is precisely what R3.5 exists to prevent by the other route.

        Called **before** the work and inside the same transaction, so a failure rolls the
        claim back with it and the task is retryable.
        """
        ...
