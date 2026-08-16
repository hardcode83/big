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
from typing import Protocol

from app.messaging.domain.entities import Conversation, Message
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
