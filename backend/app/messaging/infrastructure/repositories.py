"""SQLAlchemy adapters for the two messaging ports (R1.1-R1.5; design D2, D3).

**`conversations` and `messages` are not the same problem, and the difference is the whole
file.** `conversations` carries `TenantScopedMixin`, so `tenant_scoped_classes()` selects it
and the global `with_loader_criteria` of `app/core/db.py` covers its ORM reads — the explicit
`tenant_id` in every statement here is the mechanism and that listener is the net.
`messages` has **no `tenant_id` column** (PRD §7.15, fixed by `domain-foundation-ops`), so the
listener does not cover it at all: the `JOIN` with `conversations` is not defence in depth, it
is the only isolation this table has. The literal precedent is
`SqlAlchemyCleaningPhotoRepository` (`app/cleaning/infrastructure/repositories.py:409-518`),
and the rule it states applies here word for word: **no statement in `SqlAlchemyMessageRepository`
touches `messages` on its own.**

Neither adapter commits. The use case owns the transaction (R4.7), which is what keeps the
message, its timeline event, the conversation's new state and the escalation notification
atomic.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import require_unmarked_session
from app.core.tenancy import CrossTenantWriteError
from app.messaging.domain.entities import (
    Conversation,
    InboundWhatsAppEvent,
    Message,
    WhatsAppPhoneNumberAssociation,
)
from app.messaging.domain.enums import (
    ConversationChannel,
    ConversationEscalationStatus,
    ConversationStatus,
    EscalationReason,
    MessageIntent,
    MessageSenderType,
)
from app.messaging.domain.exceptions import (
    ConversationNotFoundError,
    MessagingValidationError,
    WhatsAppPhoneNumberAlreadyAssociatedError,
)
from app.messaging.domain.repositories import (
    ConversationFilters,
    ConversationPage,
    MessagePage,
)
from app.messaging.domain.value_objects import (
    ChannelErrorCode,
    InboundWhatsAppMessage,
    MessageMetadata,
)
from app.messaging.infrastructure.models import (
    ConversationModel,
    MessageModel,
    WhatsAppInboundEventModel,
    WhatsAppPhoneNumberModel,
)

#: The name of `WhatsAppPhoneNumberModel.phone_number_id`'s unique index, matched against
#: `IntegrityError.orig` — the same `str(error.orig)` substring match
#: `SqlAlchemyWebhookEndpointRepository.upsert` uses for `WEBHOOK_ENDPOINT_CONSTRAINT`.
WHATSAPP_PHONE_NUMBER_ID_CONSTRAINT = "ix_whatsapp_phone_numbers_phone_number_id"

#: The columns `Conversation`'s own methods may change. Named rather than writing the whole
#: row, for the reason `maintenance` gives its `_MUTABLE_INCIDENT_COLUMNS`: an UPDATE that also
#: set `tenant_id` or `property_id` would let a wiring mistake move a conversation between
#: tenants through a method whose name says it only saves.
_MUTABLE_CONVERSATION_COLUMNS = (
    "status",
    "escalation_status",
    "language",
    "last_message_at",
    "ai_enabled",
    "updated_at",
)

#: The statuses in which a conversation's problem is still open, for
#: `count_unresolved_guest_messages_with_intent` (R5.1). By enumeration and not by exclusion,
#: unlike `OPEN_INCIDENT_STATUSES`, because here the safe direction is the opposite one: a
#: status added later should not silently start feeding the repeated-intent escalation.
_UNRESOLVED_CONVERSATION_STATUSES = (
    ConversationStatus.OPEN,
    ConversationStatus.ESCALATED,
)


def _to_metadata(raw: dict[str, Any] | None) -> MessageMetadata | None:
    """Rebuild the value object from the JSONB column, refusing anything it does not declare.

    Raising on an unknown key is deliberate and is the read-side half of D15. `messages
    .metadata` is a rule-11 sink whose census row says "conjunto cerrado de claves"; if a key
    outside that set could be read back and silently dropped, the column would have a writer
    the census does not know about and nothing would ever say so. There is no legacy data to
    protect: `messages` had no writer at all before this change.
    """
    if raw is None:
        return None
    known = set(MessageMetadata.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise MessagingValidationError(
            f"messages.metadata carries {len(unknown)} key(s) outside the closed set of "
            "design D15; it has a writer the rule-11 census does not declare"
        )
    return MessageMetadata(
        escalation_reason=(
            EscalationReason(raw["escalation_reason"])
            if "escalation_reason" in raw
            else None
        ),
        template_key=raw.get("template_key"),
        template_version=raw.get("template_version"),
        delivery_status=raw.get("delivery_status"),
        delivery_error_code=(
            ChannelErrorCode(raw["delivery_error_code"])
            if "delivery_error_code" in raw
            else None
        ),
        source_message_id=(
            uuid.UUID(raw["source_message_id"]) if "source_message_id" in raw else None
        ),
    )


def _to_conversation(model: ConversationModel) -> Conversation:
    return Conversation(
        id=model.id,
        tenant_id=model.tenant_id,
        channel=model.channel,
        created_at=model.created_at,
        updated_at=model.updated_at,
        property_id=model.property_id,
        reservation_id=model.reservation_id,
        guest_id=model.guest_id,
        status=model.status,
        language=model.language,
        last_message_at=model.last_message_at,
        ai_enabled=model.ai_enabled,
        escalation_status=model.escalation_status,
        business_phone_number=model.business_phone_number,
    )


def _to_message(model: MessageModel) -> Message:
    return Message(
        id=model.id,
        conversation_id=model.conversation_id,
        sender_type=model.sender_type,
        content=model.content,
        created_at=model.created_at,
        sender_user_id=model.sender_user_id,
        language=model.language,
        ai_generated=model.ai_generated,
        confidence_score=model.confidence_score,
        intent=model.intent,
        metadata=_to_metadata(model.metadata_),
    )


def _conversation_conditions(tenant_id: uuid.UUID, filters: ConversationFilters) -> list:
    conditions = [ConversationModel.tenant_id == tenant_id]
    if filters.status is not None:
        conditions.append(ConversationModel.status == filters.status)
    if filters.escalation_status is not None:
        conditions.append(ConversationModel.escalation_status == filters.escalation_status)
    if filters.property_id is not None:
        conditions.append(ConversationModel.property_id == filters.property_id)
    return conditions


def _require_positive_page(page: int, per_page: int) -> None:
    """`offset((page - 1) * per_page)` goes negative for `page = 0`, and Postgres answers that
    with `OFFSET must not be negative` — a `DBAPIError` the caller sees as a 500 instead of the
    422 a bad query parameter deserves. The routes of D17 declare `ge=1` on both, so this is the
    second line and the only one that holds for a caller that is not a route."""
    if page < 1 or per_page < 1:
        raise MessagingValidationError(
            f"page and per_page must be positive, got page={page}, per_page={per_page}"
        )


class SqlAlchemyConversationRepository:
    """`ConversationRepository` — the first writer `conversations` has ever had."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, conversation: Conversation) -> None:
        if conversation.tenant_id != tenant_id:
            # `app/core/db.py`'s third limit: the session's global filter does not cover
            # INSERTs, so this check is the only thing between a wiring mistake and a row of
            # another tenant — exactly as `SqlAlchemyIncidentRepository.add` documents.
            raise CrossTenantWriteError(
                entity="conversation",
                entity_tenant_id=conversation.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            ConversationModel(
                id=conversation.id,
                tenant_id=conversation.tenant_id,
                property_id=conversation.property_id,
                reservation_id=conversation.reservation_id,
                guest_id=conversation.guest_id,
                channel=conversation.channel,
                status=conversation.status,
                language=conversation.language,
                last_message_at=conversation.last_message_at,
                ai_enabled=conversation.ai_enabled,
                escalation_status=conversation.escalation_status,
                business_phone_number=conversation.business_phone_number,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
        await self._session.flush()

    async def get(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        """One query, and both R1.5 outcomes are the same zero rows (D3).

        There is no branch here that could tell "unknown id" from "another tenant's id",
        which is what makes the indistinguishability a property of the query rather than a
        discipline of the caller.
        """
        result = await self._session.execute(
            select(ConversationModel).where(
                ConversationModel.tenant_id == tenant_id,
                ConversationModel.id == conversation_id,
            )
        )
        model = result.scalar_one_or_none()
        return _to_conversation(model) if model is not None else None

    async def save(self, tenant_id: uuid.UUID, conversation: Conversation) -> None:
        if conversation.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="conversation",
                entity_tenant_id=conversation.tenant_id,
                acting_tenant_id=tenant_id,
            )
        await self._session.execute(
            update(ConversationModel)
            .where(
                ConversationModel.tenant_id == conversation.tenant_id,
                ConversationModel.id == conversation.id,
            )
            .values(
                **{
                    column: getattr(conversation, column)
                    for column in _MUTABLE_CONVERSATION_COLUMNS
                }
            )
        )
        await self._session.flush()

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
        """`INSERT … ON CONFLICT DO NOTHING`, then `SELECT` (D6).

        **Not a `SELECT`-then-`add`.** Under two simultaneous messages from one guest that is
        a check-then-insert, and the second caller opens a second thread for the same stay.
        Here the database decides: the winner inserts, the loser's INSERT matches
        `uq_conversations_portal_reservation` and does nothing, and — the property the design
        depends on — the loser's transaction is **not** aborted, because `ON CONFLICT DO
        NOTHING` is not an error. It blocks until the winner commits, then its `SELECT` reads
        the winner's row under `READ COMMITTED`, PostgreSQL's default. Both messages land in
        the same thread.

        A `SELECT`-then-`add` could only be made safe with a `SAVEPOINT`, which has no
        precedent in this tree; `on_conflict_do_nothing` has two
        (`cleaning/infrastructure/repositories.py`, `pricing/infrastructure/repositories.py`).

        The `SELECT` runs unconditionally rather than only on conflict, and reads back what
        actually landed rather than returning the entity we tried to insert. On the winning
        path they are the same row; on the losing path only the read is true, and branching on
        `rowcount` to skip it would make the correct path the exceptional one.
        """
        await self._session.execute(
            pg_insert(ConversationModel)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=property_id,
                reservation_id=reservation_id,
                guest_id=guest_id,
                channel=ConversationChannel.PORTAL,
                status=ConversationStatus.OPEN,
                language=language,
                last_message_at=None,
                ai_enabled=True,
                escalation_status=ConversationEscalationStatus.NONE,
                created_at=now,
                updated_at=now,
            )
            # Named by the index rather than by a constraint: a partial unique index is not a
            # constraint object, so `constraint=` cannot address it. The column list plus the
            # predicate is what makes the inference match `uq_conversations_portal_reservation`
            # and not some other unique index over the same columns.
            .on_conflict_do_nothing(
                index_elements=[ConversationModel.tenant_id, ConversationModel.reservation_id],
                index_where=ConversationModel.channel == ConversationChannel.PORTAL,
            )
        )
        await self._session.flush()

        conversation = await self.find_portal(tenant_id, reservation_id)
        if conversation is None:
            # Unreachable while the index exists: the INSERT either wrote the row or found one
            # to conflict with. It is `raise` rather than `assert` because a silent `None`
            # here would surface as a `500` two frames away, with nothing naming the cause.
            raise ConversationNotFoundError()
        return conversation

    async def find_portal(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> Conversation | None:
        """The stay's portal thread, or `None`. Creates nothing (R2.5).

        Filtered on `channel` as well as the tenant and the stay, so the other channels' rows
        are not merely excluded from the answer — they are unreachable through this method,
        which is what R3.5 asks of the portal's read path.
        """
        result = await self._session.execute(
            select(ConversationModel).where(
                ConversationModel.tenant_id == tenant_id,
                ConversationModel.reservation_id == reservation_id,
                ConversationModel.channel == ConversationChannel.PORTAL,
            )
        )
        model = result.scalar_one_or_none()
        return _to_conversation(model) if model is not None else None

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
        """`INSERT … ON CONFLICT DO NOTHING`, then read back what landed (D4).

        Structurally `ensure_portal`, with two differences that are both forced by the keys
        rather than chosen:

        **The index inferred is `uq_conversations_whatsapp_guest_property`** —
        `(tenant_id, guest_id, property_id) WHERE channel = 'WHATSAPP'` — so the column list
        *plus* the predicate is what makes the inference match this index and not the portal's
        over other columns of the same table.

        **The read-back goes through `RETURNING` and not through a second lookup by the key.**
        `ensure_portal` can look its row up by `(tenant_id, reservation_id)` because that key
        is `NOT NULL` by signature; here `guest_id` is nullable for R4.3's sake (`property_id`
        is always resolved — the matched stay's property or the tenant's
        `default_property_id` fallback, per the design's amended D4/D5), a `NULL` never
        conflicts with another `NULL`, and an unresolved sender therefore has *several* rows
        matching `guest_id IS NULL AND property_id = :property_id`. A key lookup would be
        ambiguous exactly where the requirement is weakest, so the `INSERT` names the row it
        wrote: `RETURNING id` yields the id on the winning path and nothing at all on the
        conflicting one, which is also how this method knows which path it took without
        reading `rowcount`.

        On the conflicting path the keys cannot contain a `NULL` — a `NULL` key never
        conflicts — so the fallback lookup below is over three real values, and it reads the
        winner's row rather than the entity we tried to insert. That is the property D4 needs:
        the loser of the race keeps the thread's original `language` and its original
        `business_phone_number`, so a reply leaves from the number the thread was opened on.
        """
        inserted = await self._session.execute(
            pg_insert(ConversationModel)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=property_id,
                reservation_id=reservation_id,
                guest_id=guest_id,
                channel=ConversationChannel.WHATSAPP,
                status=ConversationStatus.OPEN,
                language=language,
                last_message_at=None,
                ai_enabled=True,
                escalation_status=ConversationEscalationStatus.NONE,
                business_phone_number=business_phone_number,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ConversationModel.tenant_id,
                    ConversationModel.guest_id,
                    ConversationModel.property_id,
                ],
                index_where=ConversationModel.channel == ConversationChannel.WHATSAPP,
            )
            .returning(ConversationModel.id)
        )
        await self._session.flush()
        inserted_id = inserted.scalar_one_or_none()

        criteria = (
            (ConversationModel.id == inserted_id,)
            if inserted_id is not None
            else (
                ConversationModel.guest_id == guest_id,
                ConversationModel.property_id == property_id,
                ConversationModel.channel == ConversationChannel.WHATSAPP,
            )
        )
        result = await self._session.execute(
            select(ConversationModel).where(
                # The tenant filter is on both branches, including the one that already has a
                # primary key: `app/core/db.py`'s global filter does not cover this read, and
                # an id resolved from an `INSERT` of this tenant is still worth constraining
                # rather than trusting.
                ConversationModel.tenant_id == tenant_id,
                *criteria,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            # Unreachable while the index exists: the INSERT either wrote the row (and named
            # it) or found one to conflict with. `raise` rather than `assert` for the same
            # reason `ensure_portal` gives — a silent `None` would surface as a `500` two
            # frames away with nothing naming the cause.
            raise ConversationNotFoundError()
        return _to_conversation(model)

    async def list(
        self,
        tenant_id: uuid.UUID,
        filters: ConversationFilters,
        *,
        page: int,
        per_page: int,
    ) -> ConversationPage:
        """The inbox (R7.3), ordered `last_message_at DESC NULLS LAST, id`.

        `NULLS LAST` explicitly, because Postgres puts nulls **first** under `DESC`: a
        conversation created a second ago with no message yet would otherwise sit above
        everything that is actually happening (D17). The tie-break on `id` is what makes the
        order total, so two conversations sharing a `last_message_at` cannot swap between
        page 1 and page 2 on consecutive requests.
        """
        _require_positive_page(page, per_page)

        conditions = _conversation_conditions(tenant_id, filters)
        total = await self._session.scalar(
            select(func.count()).select_from(ConversationModel).where(*conditions)
        )
        rows = await self._session.execute(
            select(ConversationModel)
            .where(*conditions)
            .order_by(
                ConversationModel.last_message_at.desc().nullslast(),
                ConversationModel.id,
            )
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return ConversationPage(
            items=tuple(_to_conversation(model) for model in rows.scalars()),
            total=int(total or 0),
        )


class SqlAlchemyMessageRepository:
    """`MessageRepository`, and **no statement here touches `messages` alone** (R1.2, D3).

    `messages` has no `tenant_id`, so `tenant_scoped_classes()` does not select it and the
    global `with_loader_criteria` does not cover it. A plain `SELECT ... WHERE
    conversation_id = :id` would answer, and would answer for every tenant — which is what
    makes the omission dangerous rather than noisy. Every read starts from the `JOIN`; the
    write resolves the parent within the tenant first and inserts against **the id that
    resolved**.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _scoped(self, tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> list:
        """The `WHERE` every read of this class shares, so no method can be written without it."""
        return [
            ConversationModel.tenant_id == tenant_id,
            MessageModel.conversation_id == conversation_id,
        ]

    @staticmethod
    def _joined(statement: Select) -> Select:
        return statement.join(
            ConversationModel, ConversationModel.id == MessageModel.conversation_id
        )

    async def add(self, tenant_id: uuid.UUID, message: Message) -> None:
        """Resolve the parent inside the tenant, then insert against the id that resolved.

        Raises `ConversationNotFoundError` — the same error, with the same constant message,
        that an unknown conversation raises. R1.5 requires the two to be indistinguishable,
        and here that is not a courtesy: this is one query returning zero rows, so there is no
        branch that could distinguish them even deliberately.

        `conversation_id=owner` and not `message.conversation_id`: the same value, but the one
        this transaction proved belongs to the tenant. Writing the entity's copy would mean
        validating one identifier and persisting another, against a table with no `tenant_id`
        underneath to catch the difference.
        """
        owner = await self._session.scalar(
            select(ConversationModel.id).where(
                ConversationModel.tenant_id == tenant_id,
                ConversationModel.id == message.conversation_id,
            )
        )
        if owner is None:
            raise ConversationNotFoundError()

        self._session.add(
            MessageModel(
                id=message.id,
                conversation_id=owner,
                sender_type=message.sender_type,
                sender_user_id=message.sender_user_id,
                content=message.content,
                language=message.language,
                ai_generated=message.ai_generated,
                confidence_score=message.confidence_score,
                intent=message.intent,
                # `to_dict()` at the boundary: the column takes a plain JSON object and the
                # aggregate takes the value object, so `messages.metadata` has no writer
                # through which the guest's words could reach it (D15).
                metadata_=message.metadata.to_dict() if message.metadata is not None else None,
                # Written rather than left to `server_default`. Postgres `now()` is the
                # *transaction* timestamp, so the guest's message and the AI's reply — which
                # this change writes in one transaction — would share an instant and the
                # thread's order would fall through to a random `uuid4`.
                created_at=message.created_at,
            )
        )
        await self._session.flush()

    async def list_for_conversation(
        self,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        page: int,
        per_page: int,
    ) -> MessagePage:
        """The thread, oldest first, paginated (R7.4).

        Ascending because a conversation is read forwards, unlike the timeline, which is a
        feed. `id` breaks a shared instant so the order is total and the pages do not overlap.
        """
        _require_positive_page(page, per_page)

        conditions = self._scoped(tenant_id, conversation_id)
        total = await self._session.scalar(
            self._joined(select(func.count()).select_from(MessageModel)).where(*conditions)
        )
        rows = await self._session.execute(
            self._joined(select(MessageModel))
            .where(*conditions)
            .order_by(MessageModel.created_at, MessageModel.id)
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return MessagePage(
            items=tuple(_to_message(model) for model in rows.scalars()),
            total=int(total or 0),
        )

    async def count_guest_messages(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> int:
        """Every guest message of the conversation, through the same `JOIN` as its siblings."""
        total = await self._session.scalar(
            self._joined(select(func.count()).select_from(MessageModel)).where(
                *self._scoped(tenant_id, conversation_id),
                MessageModel.sender_type == MessageSenderType.GUEST,
            )
        )
        return int(total or 0)

    async def count_unresolved_guest_messages_with_intent(
        self,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        intent: MessageIntent,
    ) -> int:
        """The fifth escalation condition of PRD §13, as one query (R5.1, D2).

        "Unresolved" is the **conversation's current status**, not "since it was last
        resolved" — see the port's docstring for why the second reading is not implementable
        without a timestamp this change does not add. A resolved or closed conversation counts
        zero; a reopened one carries its earlier messages forward, which escalates sooner
        rather than later.
        """
        total = await self._session.scalar(
            self._joined(select(func.count()).select_from(MessageModel)).where(
                *self._scoped(tenant_id, conversation_id),
                ConversationModel.status.in_(_UNRESOLVED_CONVERSATION_STATUSES),
                MessageModel.sender_type == MessageSenderType.GUEST,
                MessageModel.intent == intent.value,
            )
        )
        return int(total or 0)

    async def last_guest_message_at(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> datetime | None:
        """The `created_at` of the guest's most recent message, `None` if they never wrote.

        Same `sender_type == MessageSenderType.GUEST` filter as `count_guest_messages` just
        above, `func.max(created_at)` instead of a count — one row either way, no `LIMIT`
        needed.
        """
        return await self._session.scalar(
            self._joined(select(func.max(MessageModel.created_at))).where(
                *self._scoped(tenant_id, conversation_id),
                MessageModel.sender_type == MessageSenderType.GUEST,
            )
        )


def _to_association(model: WhatsAppPhoneNumberModel) -> WhatsAppPhoneNumberAssociation:
    return WhatsAppPhoneNumberAssociation(
        id=model.id,
        tenant_id=model.tenant_id,
        phone_number_id=model.phone_number_id,
        display_phone_number=model.display_phone_number,
        default_property_id=model.default_property_id,
    )


class SqlAlchemyWhatsAppPhoneNumberRepository:
    """`WhatsAppPhoneNumberRepository` (section 6, `whatsapp-cloud-adapter` R6.1-R6.3, D3/D8).

    `WhatsAppPhoneNumberModel` carries `TenantScopedMixin`, so `tenant_scoped_classes()`
    selects it and the global `with_loader_criteria` of `app/core/db.py` covers `find_for_tenant`
    on a marked session — the explicit `tenant_id` in every statement here is the mechanism and
    that listener is the net, same as `ConversationModel` above. `find_by_phone_number_id` is
    the one method that must run unmarked; see its own docstring.

    Never commits. The use case owns the transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, tenant_id: uuid.UUID, association: WhatsAppPhoneNumberAssociation
    ) -> None:
        """`INSERT ... ON CONFLICT (tenant_id) DO UPDATE`, a real upsert (design D8).

        The `tenant_id` race is resolved by the database in one statement rather than by a
        prior `SELECT` deciding insert-vs-update — the same "let the database decide" the
        port's docstring asks for, applied to the constraint this method is itself keyed on.
        That leaves exactly one constraint this call can still violate:
        `ix_whatsapp_phone_numbers_phone_number_id`, the one `ON CONFLICT` does not name — a
        second tenant's row (or this tenant's own row, colliding with a number someone else
        already holds) claiming a `phone_number_id` already in use elsewhere. That failure
        surfaces as a plain `IntegrityError`, translated below into
        `WhatsAppPhoneNumberAlreadyAssociatedError` rather than silently overwriting the
        tenant that legitimately holds the number (R6.2).
        """
        if association.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="WhatsApp phone number association",
                entity_tenant_id=association.tenant_id,
                acting_tenant_id=tenant_id,
            )

        stmt = (
            pg_insert(WhatsAppPhoneNumberModel)
            .values(
                id=association.id,
                tenant_id=tenant_id,
                phone_number_id=association.phone_number_id,
                display_phone_number=association.display_phone_number,
                default_property_id=association.default_property_id,
            )
            .on_conflict_do_update(
                index_elements=[WhatsAppPhoneNumberModel.tenant_id],
                set_={
                    "phone_number_id": association.phone_number_id,
                    "display_phone_number": association.display_phone_number,
                    "default_property_id": association.default_property_id,
                },
            )
        )
        try:
            await self._session.execute(stmt)
        except IntegrityError as error:
            if WHATSAPP_PHONE_NUMBER_ID_CONSTRAINT in str(error.orig):
                raise WhatsAppPhoneNumberAlreadyAssociatedError(
                    "that phone_number_id is already associated with another tenant; "
                    "release it there before associating it here"
                ) from error
            # Anything else is re-raised untranslated: a 409 blamed on a constraint the
            # client cannot see would be a lie it has no way to act on.
            raise

    async def find_for_tenant(
        self, tenant_id: uuid.UUID
    ) -> WhatsAppPhoneNumberAssociation | None:
        result = await self._session.execute(
            select(WhatsAppPhoneNumberModel).where(
                WhatsAppPhoneNumberModel.tenant_id == tenant_id
            )
        )
        model = result.scalar_one_or_none()
        return None if model is None else _to_association(model)

    async def delete_for_tenant(self, tenant_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(WhatsAppPhoneNumberModel).where(
                WhatsAppPhoneNumberModel.tenant_id == tenant_id
            )
        )
        return result.rowcount > 0

    async def find_by_phone_number_id(
        self, phone_number_id: str
    ) -> WhatsAppPhoneNumberAssociation | None:
        """Section 7's tenant resolution. Runs on an unmarked session, and that is enforced.

        Mirrors `SqlAlchemyWebhookEndpointRepository.find_by_token_hash` exactly: an incoming
        WhatsApp webhook carries no JWT, so there is no tenant to scope this read by until it
        answers. `require_unmarked_session` refuses a marked session outright rather than
        letting the global filter silently narrow it — `tests/test_unscoped_reads.py` holds
        the census this call is declared in.
        """
        require_unmarked_session(self._session, read="find_by_phone_number_id")
        result = await self._session.execute(
            select(WhatsAppPhoneNumberModel).where(
                WhatsAppPhoneNumberModel.phone_number_id == phone_number_id
            )
        )
        model = result.scalar_one_or_none()
        return None if model is None else _to_association(model)


def _to_inbound_event(model: WhatsAppInboundEventModel) -> InboundWhatsAppEvent:
    """The row as the entity, message value object rebuilt from its five columns.

    `InboundWhatsAppMessage.__post_init__` revalidates every field on the way back, which is
    the point of storing the parts rather than a blob: a row that somehow lost its text or
    grew a naive `received_at` is refused here instead of reaching the pipeline.
    """
    return InboundWhatsAppEvent(
        id=model.id,
        tenant_id=model.tenant_id,
        default_property_id=model.default_property_id,
        message=InboundWhatsAppMessage(
            sender_phone=model.sender_phone,
            provider_message_id=model.provider_message_id,
            text=model.message_text,
            received_at=model.received_at,
            business_phone_number=model.phone_number_id,
        ),
        processed_at=model.processed_at,
    )


class SqlAlchemyWhatsAppInboundEventRepository:
    """`WhatsAppInboundEventRepository` (section 7, R3.3-R3.5, design D7).

    The session requirement is **per method**, and the port's docstring is where it is stated;
    what is worth repeating here is only the one thing this class does differently from its
    sibling `SqlAlchemyWhatsAppPhoneNumberRepository`: it never takes `tenant_id` on the write
    path, because the tenant is what the row itself records and may legitimately be `NULL`.

    Never commits. The use case owns the transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: InboundWhatsAppEvent) -> bool:
        """`INSERT ... ON CONFLICT (provider_message_id) DO NOTHING`, and `RETURNING id`.

        R3.5 decided by the database rather than by a prior read (design D8's rule, applied
        one table over): `provider_message_id` is globally unique, so a read-then-write leaves
        a TOCTOU race that two concurrent redeliveries of the same message both win — and the
        loser's row is a second message in the guest's thread.

        `RETURNING` is what tells the two paths apart: it yields the id on the inserting call
        and nothing on the conflicting one. `rowcount` would answer the same question less
        clearly and is the shape `ensure_whatsapp` deliberately avoided for the same reason.
        """
        stmt = (
            pg_insert(WhatsAppInboundEventModel)
            .values(
                id=event.id,
                tenant_id=event.tenant_id,
                default_property_id=event.default_property_id,
                phone_number_id=event.message.business_phone_number,
                provider_message_id=event.message.provider_message_id,
                sender_phone=event.message.sender_phone,
                message_text=event.message.text,
                received_at=event.message.received_at,
                processed_at=event.processed_at,
            )
            .on_conflict_do_nothing(index_elements=["provider_message_id"])
            .returning(WhatsAppInboundEventModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def locate_without_tenant_scoping(
        self, event_id: uuid.UUID
    ) -> InboundWhatsAppEvent | None:
        """The dispatched task's one read. Runs on an unmarked session, and that is enforced.

        Mirrors `find_by_phone_number_id` above: the task carries an id and no tenant, so the
        row is what resolves the tenant. `require_unmarked_session` refuses a marked session
        outright rather than letting the global filter narrow the query to a tenant the task
        has not learned yet — and, for the rows whose `tenant_id` is `NULL`, narrow it to
        nothing at all without erroring. `tests/test_unscoped_reads.py` holds the census this
        call is declared in.
        """
        require_unmarked_session(self._session, read="locate_without_tenant_scoping")
        result = await self._session.execute(
            select(WhatsAppInboundEventModel).where(WhatsAppInboundEventModel.id == event_id)
        )
        model = result.scalar_one_or_none()
        return None if model is None else _to_inbound_event(model)

    async def mark_processed(
        self, tenant_id: uuid.UUID, event_id: uuid.UUID, *, now: datetime
    ) -> bool:
        """One conditional UPDATE, so exactly one run of the task can proceed.

        `WHERE processed_at IS NULL` is the claim; `tenant_id` is the ordinary scoping every
        other write in this module carries. `rowcount` is what the two outcomes differ by, and
        the pattern is the one `SqlAlchemyPropertyRepository.update_details` already uses.
        """
        result = await self._session.execute(
            update(WhatsAppInboundEventModel)
            .where(
                WhatsAppInboundEventModel.id == event_id,
                WhatsAppInboundEventModel.tenant_id == tenant_id,
                WhatsAppInboundEventModel.processed_at.is_(None),
            )
            .values(processed_at=now)
        )
        return result.rowcount == 1
