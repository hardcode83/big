"""The guest portal's two use cases, implemented where the behaviour belongs (D2, D3, D5, D9).

**The ports are declared in `guests`, the implementers live here.** That is the shape
`IncidentReportingPort` already uses between `messaging` and `maintenance`: the port in the
`domain/` of the **consumer**, the implementer in the `application/` of the **owner**, and the
wiring in the one layer entitled to know both modules (`guests/api/portal_dependencies.py`).
D2 rejects the alternative — a router of its own in `messaging/api/` — because it would have
to copy the portal's four-step authorisation sequence, and that sequence being in exactly one
place is the contract R1.2 states.

**Why the projection is built here and not in `guests`.** `PortalMessage` exists to *exclude*
`sender_user_id`, `ai_generated`, `confidence_score`, `intent` and `metadata` (R2.2, R2.4), and
those are fields of `messaging.domain.entities.Message`. A module that does not own the entity
cannot be trusted to keep excluding fields it never sees; here the mapping is visible next to
what it drops.
"""

import math
import uuid
from datetime import datetime

from app.guests.domain.portal_ports import (
    GuestSession,
    PortalMessage,
    PortalMessageSender,
    PortalThread,
    PortalThreadState,
)
from app.messaging.application.use_cases import ProcessInboundGuestMessageUseCase
from app.messaging.domain.entities import Conversation, Message
from app.messaging.domain.enums import MessageSenderType
from app.messaging.domain.language import detect_language
from app.messaging.domain.repositories import ConversationRepository, MessageRepository
from app.messaging.domain.value_objects import InboundMessageActor

#: The language a portal conversation is born in when the first message does not say (R3.3).
DEFAULT_PORTAL_LANGUAGE = "es"

#: How the five `MessageSenderType` members collapse into the two the guest sees (R2.2, D4).
#:
#: **Total on purpose, and a test asserts `set(_SENDER) == set(MessageSenderType)`.** A
#: `.get(..., PROPERTY)` would be one line shorter and would silently publish any member added
#: later as "the accommodation" — including one that ought never to reach a guest at all. With
#: a total map, a new member breaks the test instead of leaking through a default.
#:
#: `AI` and `MANAGER` both map to `PROPERTY`, which **is** the requirement rather than a
#: simplification: R2.2 forbids publishing whether a reply was written by the AI or a person,
#: and mapping them to the same value is what removes the distinction from the payload. What it
#: does not do is make it unguessable — see the residual recorded in `design.md` under R2.2.
_SENDER: dict[MessageSenderType, PortalMessageSender] = {
    MessageSenderType.GUEST: PortalMessageSender.GUEST,
    MessageSenderType.AI: PortalMessageSender.PROPERTY,
    MessageSenderType.MANAGER: PortalMessageSender.PROPERTY,
    MessageSenderType.OWNER: PortalMessageSender.PROPERTY,
    MessageSenderType.SYSTEM: PortalMessageSender.PROPERTY,
}


def _project(message: Message) -> PortalMessage:
    """One `Message` as the guest may see it. Four fields in, everything else dropped."""
    return PortalMessage(
        id=message.id,
        sender=_SENDER[message.sender_type],
        content=message.content,
        created_at=message.created_at,
    )


def _state(conversation: Conversation | None) -> PortalThreadState:
    """`AWAITING_HUMAN` while a person holds the conversation (R2.3).

    Delegates to `Conversation.is_handed_over`, which is the same predicate the pipeline uses
    to decide whether the AI should still answer (D9). Two readers, one rule: while it was a
    private helper of `use_cases.py` this one would have had to restate the pair of members,
    which is the shape in which the two answers drift.
    """
    if conversation is None:
        return PortalThreadState.AUTOMATIC
    return (
        PortalThreadState.AWAITING_HUMAN
        if conversation.is_handed_over()
        else PortalThreadState.AUTOMATIC
    )


class PostPortalGuestMessageUseCase:
    """`GuestPortalMessageSubmitter` — the guest writes, and the whole pipeline runs (R1.4, D5).

    **It does two things and neither of them is persisting a message**: it resolves or creates
    the stay's `PORTAL` conversation, and it hands the content to
    `ProcessInboundGuestMessageUseCase`, which stays the owner of the nine steps and of the
    single `commit()`. There is no `Message(` in this module, and a test asserts it.

    That makes R1.4's "entero y sin duplicarlo" structural rather than a promise, and it has a
    consequence worth saying out loud: the rule-11 census counts *use cases that write
    `messages.content`*, and that number **does not move** — it is still the two in
    `messaging/application/use_cases.py`.

    Both use cases share the request's `AsyncSession`, so the conversation created here and the
    message written there land in the same transaction with no extra `UnitOfWork`.

    **Every identifier comes from the `GuestSession`** (R1.3). The three anchors this passes to
    `ensure_portal` — property, stay and guest — are the ones the authoriser resolved from the
    token's own row, and there is no parameter through which a route could supply another.
    `ensure_portal` states that as a precondition it does not enforce (its foreign keys are
    global rather than composite with `tenant_id`), so this class is what makes it true; the
    unenforced gap is pinned in
    `tests/messaging/test_tenant_isolation.py::test_ensure_portal_does_not_verify_the_stay_belongs_to_the_tenant`
    and its structural fix is a roadmap candidate.
    """

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        pipeline: ProcessInboundGuestMessageUseCase,
    ) -> None:
        self._conversations = conversations
        self._pipeline = pipeline

    async def submit(
        self,
        session: GuestSession,
        *,
        content: str,
        client_ip: str | None,
        now: datetime,
    ) -> PortalMessage:
        conversation = await self._conversations.ensure_portal(
            session.tenant_id,
            reservation_id=session.reservation_id,
            property_id=session.property_id,
            guest_id=session.guest_id,
            # Only applied when the row is created; on the `DO NOTHING` branch the conversation
            # keeps the language its first message decided (R3.3). The pipeline detects the
            # language again for the message itself — the same pure function over the same
            # text, so the two agree by construction rather than by a second criterion.
            language=detect_language(content) or DEFAULT_PORTAL_LANGUAGE,
            now=now,
        )

        message = await self._pipeline.execute(
            tenant_id=session.tenant_id,
            conversation_id=conversation.id,
            content=content,
            # The actor R4.1 opened this pipeline to: named by the digest the authoriser
            # already resolved, never by the token. `ip` travels with it because the pipeline
            # derives the audit row's actor **solely** from this object — an earlier version of
            # this comment claimed the address belonged to the route instead, which left every
            # portal `INCIDENT_CREATED` row with `actor_ip` NULL while its sibling anonymous
            # route recorded one. Rule 9 wants it; none of its exceptions covers a path that
            # has a request to take it from.
            actor=InboundMessageActor(token_hash=session.token_hash, ip=client_ip),
            now=now,
        )
        return _project(message)


class ReadPortalThreadUseCase:
    """`GuestPortalThreadReader` — the guest reads their own thread (R2.1, R2.5, D9).

    **Reading never creates.** It resolves the conversation with `find_portal`, and a stay whose
    guest has not written yet answers with an empty thread rather than a `404` and rather than a
    freshly minted row (R2.5). That is why the repository has two methods and not one with a
    flag.

    **Without `page`, the last window** (D9). The convention elsewhere in this API is
    `page=1` = oldest first, which for a chat opens a long thread at the wrong end and would
    cost the front end a second round trip on every poll — against a budget of 60 requests a
    minute shared by six routes. `total`, `page` and `per_page` travel in the response, so a
    client always knows which window it holds and can page backwards from it.
    """

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
    ) -> None:
        self._conversations = conversations
        self._messages = messages

    async def read(
        self, session: GuestSession, *, page: int | None, per_page: int
    ) -> PortalThread:
        conversation = await self._conversations.find_portal(
            session.tenant_id, session.reservation_id
        )
        if conversation is None:
            return PortalThread(
                items=(),
                total=0,
                page=1,
                per_page=per_page,
                state=PortalThreadState.AUTOMATIC,
            )

        resolved = page if page is not None else await self._last_page(
            session.tenant_id, conversation.id, per_page
        )
        window = await self._messages.list_for_conversation(
            session.tenant_id, conversation.id, page=resolved, per_page=per_page
        )
        return PortalThread(
            items=tuple(_project(message) for message in window.items),
            total=window.total,
            page=resolved,
            per_page=per_page,
            state=_state(conversation),
        )

    async def _last_page(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID, per_page: int
    ) -> int:
        """`ceil(total / per_page)`, and never below 1 (D9).

        Counted with the repository's own paginated read rather than a count method of its own:
        `list_for_conversation` already returns `total`, so asking for one row is one query and
        no new port method. An empty thread yields page 1, which is what a client with nothing
        to show should be told it is holding.

        The count and the window are two statements, so a message can land between them and
        leave the returned page one short of being the last. D9 accepts that: the next poll
        brings it, and serialising an anonymous read-only request buys nothing polling does not
        fix in fifteen seconds.
        """
        first = await self._messages.list_for_conversation(
            tenant_id, conversation_id, page=1, per_page=per_page
        )
        return max(1, math.ceil(first.total / per_page))
