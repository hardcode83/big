"""The two SQLAlchemy adapters, against a real Postgres (R1.1-R1.5, R7.3, R7.4).

Integration and not unit, per `steering/testing.md`: "`infrastructure/`: integration tests
contra Postgres/Redis reales". The ordering guarantees of R7.3/R7.4 in particular are
statements about SQL — `NULLS LAST` under `DESC` is a Postgres behaviour, not a Python one —
so a fake repository could not test them at all.

Tenant isolation has its own file (`test_tenant_isolation.py`, R1.3).
"""

import uuid
from datetime import timedelta

import pytest

from app.core.tenancy import CrossTenantWriteError
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
    ConversationNotFoundError,
    MessagingValidationError,
)
from app.messaging.domain.repositories import ConversationFilters
from app.messaging.domain.value_objects import (
    DELIVERY_STATUS_SENT,
    ChannelErrorCode,
    MessageMetadata,
)
from app.messaging.infrastructure.models import MessageModel
from app.messaging.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
)
from tests.messaging.conftest import (
    NOW,
    seed_conversation,
    seed_message,
    seed_property,
    seed_tenant,
)

ALL = ConversationFilters()


def conversations(db_session) -> SqlAlchemyConversationRepository:
    return SqlAlchemyConversationRepository(db_session)


def messages(db_session) -> SqlAlchemyMessageRepository:
    return SqlAlchemyMessageRepository(db_session)


def build_conversation(tenant_id: uuid.UUID, property_id: uuid.UUID) -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        channel=ConversationChannel.WHATSAPP,
        created_at=NOW,
        updated_at=NOW,
        property_id=property_id,
    )


def build_message(conversation_id: uuid.UUID, **overrides) -> Message:
    kwargs: dict = {
        "id": uuid.uuid4(),
        "conversation_id": conversation_id,
        "sender_type": MessageSenderType.GUEST,
        "content": "El wifi no funciona",
        "created_at": NOW,
    }
    kwargs.update(overrides)
    return Message(**kwargs)


# --- ConversationRepository: the round trip ---------------------------------------------


@pytest.mark.asyncio
async def test_a_conversation_survives_the_round_trip(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = build_conversation(tenant.id, prop.id)

    await conversations(db_session).add(tenant.id, conversation)
    stored = await conversations(db_session).get(tenant.id, conversation.id)

    assert stored == conversation


@pytest.mark.asyncio
async def test_an_unknown_conversation_reads_as_none(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")

    assert await conversations(db_session).get(tenant.id, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_adding_a_conversation_of_another_tenant_is_refused(db_session) -> None:
    """`app/core/db.py`'s third limit: the session's global filter does not cover INSERTs, so
    this check is the only thing between a wiring mistake and a row of another tenant."""
    tenant = await seed_tenant(db_session, "TenantA")
    other = await seed_tenant(db_session, "TenantB")
    prop = await seed_property(db_session, other, "PAJARITOS8")

    with pytest.raises(CrossTenantWriteError):
        await conversations(db_session).add(tenant.id, build_conversation(other.id, prop.id))


@pytest.mark.asyncio
async def test_save_persists_what_the_entity_methods_changed(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = build_conversation(tenant.id, prop.id)
    await conversations(db_session).add(tenant.id, conversation)

    conversation.escalate(now=NOW + timedelta(minutes=1))
    conversation.register_message(now=NOW + timedelta(minutes=2))
    await conversations(db_session).save(tenant.id, conversation)

    stored = await conversations(db_session).get(tenant.id, conversation.id)
    assert stored.status is ConversationStatus.ESCALATED
    assert stored.escalation_status is ConversationEscalationStatus.PENDING_HUMAN
    assert stored.last_message_at == NOW + timedelta(minutes=2)


@pytest.mark.asyncio
async def test_save_never_moves_a_conversation_between_tenants(db_session) -> None:
    """`_MUTABLE_CONVERSATION_COLUMNS` names what a method may change, so an UPDATE cannot
    also set `tenant_id` or `property_id` through a call whose name says it only saves."""
    tenant = await seed_tenant(db_session, "TenantA")
    other = await seed_tenant(db_session, "TenantB")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = build_conversation(tenant.id, prop.id)
    await conversations(db_session).add(tenant.id, conversation)

    conversation.tenant_id = other.id
    with pytest.raises(CrossTenantWriteError):
        await conversations(db_session).save(tenant.id, conversation)

    stored = await conversations(db_session).get(tenant.id, conversation.id)
    assert stored is not None


# --- ConversationRepository.list: the inbox order (R7.3, D17) ----------------------------


@pytest.mark.asyncio
async def test_the_inbox_is_ordered_by_last_message_descending(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    old = await seed_conversation(db_session, tenant, prop, last_message_at=NOW)
    recent = await seed_conversation(
        db_session, tenant, prop, last_message_at=NOW + timedelta(hours=1)
    )

    page = await conversations(db_session).list(tenant.id, ALL, page=1, per_page=10)

    assert [item.id for item in page.items] == [recent.id, old.id]
    assert page.total == 2


@pytest.mark.asyncio
async def test_a_conversation_with_no_messages_sorts_last(db_session) -> None:
    """`NULLS LAST` explicitly (D17): Postgres puts nulls **first** under `DESC`, so without
    it a conversation created a second ago and never written to would sit above whatever is
    actually on fire."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    silent = await seed_conversation(db_session, tenant, prop, last_message_at=None)
    active = await seed_conversation(db_session, tenant, prop, last_message_at=NOW)

    page = await conversations(db_session).list(tenant.id, ALL, page=1, per_page=10)

    assert [item.id for item in page.items] == [active.id, silent.id]


@pytest.mark.asyncio
async def test_conversations_sharing_an_instant_have_a_total_order(db_session) -> None:
    """The tie-break on `id`. Without it two rows with the same `last_message_at` can swap
    between page 1 and page 2 on consecutive requests, so a client paginating misses one and
    sees another twice."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    for _ in range(4):
        await seed_conversation(db_session, tenant, prop, last_message_at=NOW)

    first = await conversations(db_session).list(tenant.id, ALL, page=1, per_page=2)
    second = await conversations(db_session).list(tenant.id, ALL, page=2, per_page=2)

    ids = [item.id for item in first.items] + [item.id for item in second.items]
    assert len(set(ids)) == 4
    assert ids == sorted(ids)


@pytest.mark.asyncio
async def test_the_inbox_filters_combine_with_and(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    one = await seed_property(db_session, tenant, "REDES11")
    two = await seed_property(db_session, tenant, "PAJARITOS8")
    wanted = await seed_conversation(
        db_session,
        tenant,
        one,
        status=ConversationStatus.ESCALATED,
        escalation_status=ConversationEscalationStatus.PENDING_HUMAN,
    )
    await seed_conversation(db_session, tenant, two, status=ConversationStatus.ESCALATED)
    await seed_conversation(db_session, tenant, one, status=ConversationStatus.OPEN)

    page = await conversations(db_session).list(
        tenant.id,
        ConversationFilters(
            status=ConversationStatus.ESCALATED,
            escalation_status=ConversationEscalationStatus.PENDING_HUMAN,
            property_id=one.id,
        ),
        page=1,
        per_page=10,
    )

    assert [item.id for item in page.items] == [wanted.id]
    assert page.total == 1


@pytest.mark.asyncio
async def test_the_total_counts_the_filtered_set_and_not_the_page(db_session) -> None:
    """PRD §23 wants `total_pages`, which is wrong if `total` counts the page."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    for index in range(5):
        await seed_conversation(
            db_session, tenant, prop, last_message_at=NOW + timedelta(minutes=index)
        )

    page = await conversations(db_session).list(tenant.id, ALL, page=1, per_page=2)

    assert len(page.items) == 2
    assert page.total == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(("page", "per_page"), [(0, 10), (1, 0), (-1, 10), (1, -5)])
async def test_a_non_positive_page_is_a_domain_error_and_not_a_database_one(
    db_session, page: int, per_page: int
) -> None:
    """`offset((page - 1) * per_page)` goes negative for `page = 0` and Postgres answers with
    a `DBAPIError` the caller sees as 500. The routes declare `ge=1`; this is the ceiling for
    a caller that is not a route."""
    tenant = await seed_tenant(db_session, "TenantA")

    with pytest.raises(MessagingValidationError):
        await conversations(db_session).list(tenant.id, ALL, page=page, per_page=per_page)


# --- MessageRepository (R1.2, R7.4) ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_message_survives_the_round_trip(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    message = build_message(conversation.id, intent=MessageIntent.WIFI, language="es")

    await messages(db_session).add(tenant.id, message)
    page = await messages(db_session).list_for_conversation(
        tenant.id, conversation.id, page=1, per_page=10
    )

    assert [item.id for item in page.items] == [message.id]
    assert page.items[0].intent == MessageIntent.WIFI.value
    assert page.items[0].language == "es"


@pytest.mark.asyncio
async def test_adding_a_message_to_an_unknown_conversation_is_refused(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")

    with pytest.raises(ConversationNotFoundError):
        await messages(db_session).add(tenant.id, build_message(uuid.uuid4()))


@pytest.mark.asyncio
async def test_the_thread_is_ordered_oldest_first(db_session) -> None:
    """R7.4: a conversation is read forwards, unlike the timeline, which is a feed."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    second = await seed_message(db_session, conversation, created_at=NOW + timedelta(minutes=1))
    first = await seed_message(db_session, conversation, created_at=NOW)

    page = await messages(db_session).list_for_conversation(
        tenant.id, conversation.id, page=1, per_page=10
    )

    assert [item.id for item in page.items] == [first.id, second.id]


@pytest.mark.asyncio
async def test_two_messages_of_one_transaction_do_not_share_an_instant(db_session) -> None:
    """`created_at` is written by the adapter and not left to `server_default`.

    Postgres `now()` is the **transaction** timestamp, and this change writes the guest's
    message and the AI's reply in one transaction (R4.7) — so with a server default the two
    would share an instant and the thread's order would fall through to a random `uuid4`.
    """
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    guest = build_message(conversation.id, created_at=NOW)
    reply = build_message(
        conversation.id,
        created_at=NOW + timedelta(seconds=1),
        sender_type=MessageSenderType.AI,
        ai_generated=True,
        content="We have registered your question about the internet connection. "
        "We will reply here as soon as possible.",
    )

    await messages(db_session).add(tenant.id, guest)
    await messages(db_session).add(tenant.id, reply)

    page = await messages(db_session).list_for_conversation(
        tenant.id, conversation.id, page=1, per_page=10
    )
    assert [item.id for item in page.items] == [guest.id, reply.id]
    assert page.items[0].created_at != page.items[1].created_at


@pytest.mark.asyncio
async def test_the_thread_paginates(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    for index in range(5):
        await seed_message(db_session, conversation, created_at=NOW + timedelta(minutes=index))

    page = await messages(db_session).list_for_conversation(
        tenant.id, conversation.id, page=2, per_page=2
    )

    assert len(page.items) == 2
    assert page.total == 5


# --- messages.metadata across the boundary (R3.5, D15) -----------------------------------


@pytest.mark.asyncio
async def test_metadata_goes_out_as_json_and_comes_back_as_the_value_object(
    db_session,
) -> None:
    """The adapter calls `to_dict()` at the boundary, so the column takes a plain JSON object
    while the aggregate takes the closed value object — which is what leaves
    `messages.metadata` with no writer that could put the guest's words in it."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    metadata = MessageMetadata(
        escalation_reason=EscalationReason.DELIVERY_FAILED,
        template_key="WIFI:es",
        template_version="2026-08-16.1",
        delivery_status=DELIVERY_STATUS_SENT,
        delivery_error_code=ChannelErrorCode.INVALID_RECIPIENT,
        source_message_id=uuid.uuid4(),
    )
    message = build_message(conversation.id, metadata=metadata)

    await messages(db_session).add(tenant.id, message)
    page = await messages(db_session).list_for_conversation(
        tenant.id, conversation.id, page=1, per_page=10
    )

    assert page.items[0].metadata == metadata


@pytest.mark.asyncio
async def test_a_metadata_key_outside_the_closed_set_is_refused_on_read(db_session) -> None:
    """The read-side half of D15. If a key outside the declared set could be read back and
    silently dropped, the column would have a writer the rule-11 census does not know about
    and nothing would ever say so."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    db_session.add(
        MessageModel(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            sender_type=MessageSenderType.GUEST,
            content="hola",
            metadata_={"guest_said": "mi DNI es 12345678Z"},
            created_at=NOW,
        )
    )
    await db_session.flush()

    with pytest.raises(MessagingValidationError):
        await messages(db_session).list_for_conversation(
            tenant.id, conversation.id, page=1, per_page=10
        )


# --- count_unresolved_guest_messages_with_intent (R5.1, D2) ------------------------------


@pytest.mark.asyncio
async def test_the_count_sees_only_guest_messages_of_that_intent(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    await seed_message(db_session, conversation, intent=MessageIntent.WIFI.value)
    await seed_message(db_session, conversation, intent=MessageIntent.WIFI.value)
    await seed_message(db_session, conversation, intent=MessageIntent.PARKING.value)
    await seed_message(
        db_session,
        conversation,
        intent=MessageIntent.WIFI.value,
        sender_type=MessageSenderType.AI,
    )

    count = await messages(db_session).count_unresolved_guest_messages_with_intent(
        tenant.id, conversation.id, MessageIntent.WIFI
    )

    assert count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [ConversationStatus.RESOLVED, ConversationStatus.CLOSED]
)
async def test_a_finished_conversation_counts_nothing(
    db_session, status: ConversationStatus
) -> None:
    """"Unresolved" is the conversation's current status (D2, as amended): a finished
    conversation has no run in progress to escalate."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop, status=status)
    await seed_message(db_session, conversation, intent=MessageIntent.WIFI.value)

    count = await messages(db_session).count_unresolved_guest_messages_with_intent(
        tenant.id, conversation.id, MessageIntent.WIFI
    )

    assert count == 0


@pytest.mark.asyncio
async def test_the_guest_message_count_sees_only_the_guests_messages(db_session) -> None:
    """Fills `ConversationContext.guest_message_count`, which is handed to an `AIAdapter` —
    so it has to be true, not approximately true."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    await seed_message(db_session, conversation)
    await seed_message(db_session, conversation)
    await seed_message(db_session, conversation, sender_type=MessageSenderType.AI)
    await seed_message(db_session, conversation, sender_type=MessageSenderType.MANAGER)

    count = await messages(db_session).count_guest_messages(tenant.id, conversation.id)

    assert count == 2


@pytest.mark.asyncio
async def test_the_guest_message_count_is_zero_on_an_empty_conversation(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)

    assert await messages(db_session).count_guest_messages(tenant.id, conversation.id) == 0


@pytest.mark.asyncio
async def test_the_guest_message_count_ignores_the_conversations_status(db_session) -> None:
    """Unlike its sibling: this one answers "how long has this been going", which a
    resolution does not reset."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(
        db_session, tenant, prop, status=ConversationStatus.RESOLVED
    )
    await seed_message(db_session, conversation)

    assert await messages(db_session).count_guest_messages(tenant.id, conversation.id) == 1


@pytest.mark.asyncio
async def test_an_escalated_conversation_still_counts(db_session) -> None:
    """`ESCALATED` is not a finished state — the guest is still waiting."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(
        db_session, tenant, prop, status=ConversationStatus.ESCALATED
    )
    await seed_message(db_session, conversation, intent=MessageIntent.WIFI.value)

    count = await messages(db_session).count_unresolved_guest_messages_with_intent(
        tenant.id, conversation.id, MessageIntent.WIFI
    )

    assert count == 1
