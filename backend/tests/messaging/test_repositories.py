"""The two SQLAlchemy adapters, against a real Postgres (R1.1-R1.5, R7.3, R7.4).

Integration and not unit, per `steering/testing.md`: "`infrastructure/`: integration tests
contra Postgres/Redis reales". The ordering guarantees of R7.3/R7.4 in particular are
statements about SQL — `NULLS LAST` under `DESC` is a Postgres behaviour, not a Python one —
so a fake repository could not test them at all.

Tenant isolation has its own file (`test_tenant_isolation.py`, R1.3).
"""

import asyncio
import contextlib
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select, text

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.messaging.infrastructure.models import ConversationModel, MessageModel
from app.messaging.infrastructure.repositories import (
    _MUTABLE_CONVERSATION_COLUMNS,
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
)
from tests.messaging.conftest import (
    NOW,
    seed_conversation,
    seed_guest,
    seed_message,
    seed_property,
    seed_reservation,
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


# --- last_guest_message_at (`whatsapp-cloud-adapter` R2.4, design D2) ---------------------


@pytest.mark.asyncio
async def test_the_guests_last_message_time_is_none_when_the_guest_never_wrote(
    db_session,
) -> None:
    """D2's binding reading: no guest message ever means OUTSIDE the session window, not an
    invitation to guess at one."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    await seed_message(db_session, conversation, sender_type=MessageSenderType.AI)

    result = await messages(db_session).last_guest_message_at(tenant.id, conversation.id)

    assert result is None


@pytest.mark.asyncio
async def test_the_guests_last_message_time_with_a_single_guest_message(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    written = await seed_message(db_session, conversation, created_at=NOW)

    result = await messages(db_session).last_guest_message_at(tenant.id, conversation.id)

    assert result == written.created_at


@pytest.mark.asyncio
async def test_the_guests_last_message_time_is_the_most_recent_of_several(db_session) -> None:
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    await seed_message(db_session, conversation, created_at=NOW)
    latest = await seed_message(
        db_session, conversation, created_at=NOW + timedelta(minutes=5)
    )
    await seed_message(db_session, conversation, created_at=NOW + timedelta(minutes=2))

    result = await messages(db_session).last_guest_message_at(tenant.id, conversation.id)

    assert result == latest.created_at


@pytest.mark.asyncio
async def test_a_later_ai_or_manager_message_does_not_change_the_guests_last_message_time(
    db_session,
) -> None:
    """The exact gap `Conversation.last_message_at` cannot close (design D2, resolved with
    the user 2026-09-02): that column would be touched by the AI's own reply or a manager's,
    silently reopening a window the guest never reopened."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    conversation = await seed_conversation(db_session, tenant, prop)
    guest_message = await seed_message(db_session, conversation, created_at=NOW)
    await seed_message(
        db_session,
        conversation,
        sender_type=MessageSenderType.AI,
        created_at=NOW + timedelta(hours=25),
    )
    await seed_message(
        db_session,
        conversation,
        sender_type=MessageSenderType.MANAGER,
        created_at=NOW + timedelta(hours=26),
    )

    result = await messages(db_session).last_guest_message_at(tenant.id, conversation.id)

    assert result == guest_message.created_at


# --- The portal thread: one per stay (`guest-portal-messaging` R2.5, R3.4, R3.5, D6) -------


async def portal_fixture(db_session):
    """A tenant with a property and a stay — the anchors `ensure_portal` needs."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    reservation = await seed_reservation(db_session, tenant, prop)
    return tenant, prop, reservation


@pytest.mark.asyncio
async def test_ensure_portal_creates_the_thread_the_first_time(db_session) -> None:
    tenant, prop, reservation = await portal_fixture(db_session)

    conversation = await conversations(db_session).ensure_portal(
        tenant.id,
        reservation_id=reservation.id,
        property_id=prop.id,
        guest_id=None,
        language="es",
        now=NOW,
    )

    assert conversation.channel is ConversationChannel.PORTAL
    assert conversation.reservation_id == reservation.id
    assert conversation.property_id == prop.id
    assert conversation.language == "es"
    assert conversation.status is ConversationStatus.OPEN


@pytest.mark.asyncio
async def test_ensure_portal_returns_the_same_thread_the_second_time(db_session) -> None:
    """R3.4. The second call must not create a second row — and must return the first one,
    not merely decline to insert."""
    tenant, prop, reservation = await portal_fixture(db_session)
    repo = conversations(db_session)

    first = await repo.ensure_portal(
        tenant.id, reservation_id=reservation.id, property_id=prop.id,
        guest_id=None, language="es", now=NOW,
    )
    second = await repo.ensure_portal(
        tenant.id, reservation_id=reservation.id, property_id=prop.id,
        guest_id=None, language="en", now=NOW + timedelta(hours=1),
    )

    assert second.id == first.id
    total = await db_session.scalar(
        select(func.count())
        .select_from(ConversationModel)
        .where(
            ConversationModel.reservation_id == reservation.id,
            ConversationModel.channel == ConversationChannel.PORTAL,
        )
    )
    assert total == 1


@pytest.mark.asyncio
async def test_the_language_of_the_second_call_does_not_overwrite_the_first(
    db_session,
) -> None:
    """R3.3: the language is decided by the message that opened the thread. `DO NOTHING` and
    not `DO UPDATE` is what makes that true, so it is worth asserting rather than assuming."""
    tenant, prop, reservation = await portal_fixture(db_session)
    repo = conversations(db_session)

    await repo.ensure_portal(
        tenant.id, reservation_id=reservation.id, property_id=prop.id,
        guest_id=None, language="es", now=NOW,
    )
    second = await repo.ensure_portal(
        tenant.id, reservation_id=reservation.id, property_id=prop.id,
        guest_id=None, language="en", now=NOW,
    )

    assert second.language == "es"


@pytest.mark.asyncio
async def test_find_portal_returns_none_and_creates_nothing(db_session) -> None:
    """R2.5: "leer no abre conversación". Both halves asserted — the answer *and* the absence
    of a row, because a method that created one and returned it would satisfy the first."""
    tenant, prop, reservation = await portal_fixture(db_session)

    found = await conversations(db_session).find_portal(tenant.id, reservation.id)

    assert found is None
    total = await db_session.scalar(
        select(func.count()).select_from(ConversationModel).where(
            ConversationModel.reservation_id == reservation.id
        )
    )
    assert total == 0


@pytest.mark.asyncio
async def test_find_portal_returns_the_thread_once_it_exists(db_session) -> None:
    tenant, prop, reservation = await portal_fixture(db_session)
    repo = conversations(db_session)
    created = await repo.ensure_portal(
        tenant.id, reservation_id=reservation.id, property_id=prop.id,
        guest_id=None, language="es", now=NOW,
    )

    found = await repo.find_portal(tenant.id, reservation.id)

    assert found is not None
    assert found.id == created.id


@pytest.mark.asyncio
async def test_neither_method_sees_the_stays_other_channels(db_session) -> None:
    """R3.5: a stay's `WHATSAPP`/`MANUAL` threads stay intact and out of reach of the portal.

    `seed_conversation` does not set `reservation_id`, so it is set here explicitly — the
    point of the test is precisely a conversation of **the same stay** on another channel.
    """
    tenant, prop, reservation = await portal_fixture(db_session)
    for channel in (ConversationChannel.WHATSAPP, ConversationChannel.MANUAL):
        other = await seed_conversation(db_session, tenant, prop, channel=channel)
        other.reservation_id = reservation.id
    await db_session.flush()
    repo = conversations(db_session)

    assert await repo.find_portal(tenant.id, reservation.id) is None

    created = await repo.ensure_portal(
        tenant.id, reservation_id=reservation.id, property_id=prop.id,
        guest_id=None, language="es", now=NOW,
    )

    # The portal thread is a fourth row, and the other three are untouched.
    assert created.channel is ConversationChannel.PORTAL
    rows = (await db_session.execute(
        select(ConversationModel.channel).where(
            ConversationModel.reservation_id == reservation.id
        )
    )).scalars().all()
    assert sorted(c.value for c in rows) == ["MANUAL", "PORTAL", "WHATSAPP"]


async def _wait_until_a_backend_blocks_on_a_lock(engine, *, timeout: float = 10.0) -> bool:
    """Poll until PostgreSQL itself reports a backend waiting on a lock.

    Replaces a fixed `asyncio.sleep`, and the difference is the whole point. A sleep followed
    by `assert not task.done()` proves only "the loser has not finished", which is **necessary
    and not sufficient**: with `NullPool` every `AsyncSession` opens a fresh asyncpg
    connection, so on a loaded host the loser might simply not have reached its INSERT yet —
    and the test would silently degrade back into the serialised case it was written to
    replace, passing for the wrong reason with nothing to say so. Both panels of sections 3-4
    reached that independently.

    This observes the wait instead of inferring it. Scoped to `current_database()` because the
    cluster also carries the dev database, and to `transactionid` because that is the lock an
    INSERT takes while it waits on a conflicting uncommitted row — a different `wait_event`
    would be a different story and should not satisfy this.
    """
    deadline = time.monotonic() + timeout
    async with AsyncSession(engine) as observer:
        while time.monotonic() < deadline:
            waiting = await observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND state = 'active' "
                    "AND wait_event_type = 'Lock' "
                    "AND wait_event = 'transactionid'"
                )
            )
            if waiting:
                return True
            await asyncio.sleep(0.02)
    return False


@pytest.mark.asyncio
async def test_two_concurrent_callers_end_with_one_thread_and_both_see_it(
    db_session, test_engine
) -> None:
    """R3.4 in the interleaving that can actually fail, and the reason D6 is not a
    `SELECT`-then-`add`.

    **The earlier version of this test was serialised** — the winner committed before the
    loser's INSERT ran — and both the security and QA panels of sections 3-4 pointed out that
    it therefore proved nothing: a naive check-then-insert would have passed it identically,
    because the loser's `SELECT` would simply have found the already-committed row. The branch
    that distinguishes the two implementations only exists while **both** transactions are
    open, so that is what this drives.

    The sequence, and every step is load-bearing:

    1. the winner inserts and **does not commit**, so its row exists but is invisible;
    2. the loser calls `ensure_portal` in a task of its own. Its INSERT meets the winner's
       uncommitted row and blocks on the speculative-insertion lock;
    3. `assert not loser.done()` — **the discriminating assertion**. It is what proves the
       contention happened rather than being assumed;
    4. the winner commits. The loser wakes, `ON CONFLICT DO NOTHING` takes the do-nothing
       branch **without raising**, and its `SELECT` — a fresh statement snapshot under
       `READ COMMITTED` — reads the winner's row.

    A check-then-insert implementation fails at step 4 rather than step 3: it would also
    block, but on waking it gets `UniqueViolationError`, which aborts its transaction and, in
    production, would take the guest's own message down with it (R1.4's single transaction).
    So this test now discriminates the two, which the serialised one did not.
    """
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    reservation = await seed_reservation(db_session, tenant, prop)
    tenant_id, property_id, reservation_id = tenant.id, prop.id, reservation.id
    await db_session.commit()

    def call(session):
        return SqlAlchemyConversationRepository(session).ensure_portal(
            tenant_id,
            reservation_id=reservation_id,
            property_id=property_id,
            guest_id=None,
            language="es",
            now=NOW,
        )

    async with AsyncSession(test_engine, expire_on_commit=False) as winner, AsyncSession(
        test_engine, expire_on_commit=False
    ) as loser:
        first = await call(winner)          # (1) inserted, uncommitted, invisible

        pending = asyncio.create_task(call(loser))   # (2) blocks on the winner's row
        try:
            # (3) The assertion the serialised version could not make — and it **observes** the
            # contention rather than inferring it from a sleep. See the helper for why that
            # distinction is the difference between this test and the one it replaced.
            assert await _wait_until_a_backend_blocks_on_a_lock(
                test_engine
            ), "the loser never blocked on the winner's row: the two did not race"
            assert not pending.done()

            await winner.commit()           # (4) the loser wakes on the DO NOTHING branch

            second = await pending
            assert second.id == first.id
            assert second.language == "es"
            await loser.commit()
        finally:
            # **A failure here must not leave a blocked transaction behind.** Without this, an
            # assertion that fires while the loser is still waiting on the winner's row leaves
            # that task alive and its session mid-statement: the winner is never committed, the
            # lock is never released, and the next test's row-truncation blocks on it until
            # `lock_timeout` — so one red test becomes a cascade of unrelated errors
            # (`another operation is in progress`), which is exactly what
            # `steering/testing.md` warns about: "un test que deje una transacción abierta
            # bloquea el vaciado del siguiente". Seen for real by the QA panel of sections 5-6.
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pending

    async with AsyncSession(test_engine) as observer:
        total = await observer.scalar(
            select(func.count()).select_from(ConversationModel).where(
                ConversationModel.reservation_id == reservation_id,
                ConversationModel.channel == ConversationChannel.PORTAL,
            )
        )
    assert total == 1


@pytest.mark.asyncio
async def test_the_already_committed_caller_also_gets_the_existing_thread(
    db_session, test_engine
) -> None:
    """The other interleaving, kept alongside the racing one: the second message arrives long
    after the first and simply finds the thread. Cheap, and it is the common case."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    reservation = await seed_reservation(db_session, tenant, prop)
    tenant_id, property_id, reservation_id = tenant.id, prop.id, reservation.id
    await db_session.commit()

    async with AsyncSession(test_engine, expire_on_commit=False) as first_session:
        first = await SqlAlchemyConversationRepository(first_session).ensure_portal(
            tenant_id, reservation_id=reservation_id, property_id=property_id,
            guest_id=None, language="es", now=NOW,
        )
        await first_session.commit()

    async with AsyncSession(test_engine, expire_on_commit=False) as second_session:
        second = await SqlAlchemyConversationRepository(second_session).ensure_portal(
            tenant_id, reservation_id=reservation_id, property_id=property_id,
            guest_id=None, language="en", now=NOW,
        )
        await second_session.commit()

    assert second.id == first.id


# --- The WhatsApp thread: one per guest and property (`whatsapp-cloud-adapter` R4.5, D4) ---

#: Meta's `phone_number_id` for the tenant's own number — an identifier, not a dialable
#: number, and never `display_phone_number` (section 4's notes).
BUSINESS_NUMBER = "109876543210987"
OTHER_BUSINESS_NUMBER = "555000111222333"


async def whatsapp_fixture(db_session):
    """A tenant with a property, a stay and a guest — the anchors `ensure_whatsapp` takes."""
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    reservation = await seed_reservation(db_session, tenant, prop)
    guest = await seed_guest(db_session, tenant)
    return tenant, prop, reservation, guest


@pytest.mark.asyncio
async def test_ensure_whatsapp_creates_the_thread_the_first_time(db_session) -> None:
    tenant, prop, reservation, guest = await whatsapp_fixture(db_session)

    conversation = await conversations(db_session).ensure_whatsapp(
        tenant.id,
        guest_id=guest.id,
        property_id=prop.id,
        reservation_id=reservation.id,
        language="es",
        business_phone_number=BUSINESS_NUMBER,
        now=NOW,
    )

    assert conversation.channel is ConversationChannel.WHATSAPP
    assert conversation.guest_id == guest.id
    assert conversation.property_id == prop.id
    assert conversation.reservation_id == reservation.id
    assert conversation.language == "es"
    assert conversation.status is ConversationStatus.OPEN
    assert conversation.escalation_status is ConversationEscalationStatus.NONE
    assert conversation.business_phone_number == BUSINESS_NUMBER


@pytest.mark.asyncio
async def test_a_second_message_from_the_same_guest_reuses_the_thread(db_session) -> None:
    """R4.5: "una conversación existente… se reutiliza, no se duplica por mensaje". Both
    halves — the same id back *and* one row in the table, since a method that inserted a
    second row and returned the first would satisfy only the first assertion."""
    tenant, prop, reservation, guest = await whatsapp_fixture(db_session)
    repo = conversations(db_session)

    first = await repo.ensure_whatsapp(
        tenant.id, guest_id=guest.id, property_id=prop.id, reservation_id=reservation.id,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW,
    )
    second = await repo.ensure_whatsapp(
        tenant.id, guest_id=guest.id, property_id=prop.id, reservation_id=reservation.id,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW + timedelta(hours=1),
    )

    assert second.id == first.id
    total = await db_session.scalar(
        select(func.count())
        .select_from(ConversationModel)
        .where(
            ConversationModel.guest_id == guest.id,
            ConversationModel.channel == ConversationChannel.WHATSAPP,
        )
    )
    assert total == 1


@pytest.mark.asyncio
async def test_the_second_call_rewrites_neither_the_language_nor_the_business_number(
    db_session,
) -> None:
    """The D4 addendum: `business_phone_number` is "set once… and never changed after — a
    reply always leaves from the number the thread was opened on". `DO NOTHING` and not
    `DO UPDATE` is what makes that true, and the same holds for `language` (R3.3's rule,
    inherited from `ensure_portal`), so both are asserted rather than assumed."""
    tenant, prop, reservation, guest = await whatsapp_fixture(db_session)
    repo = conversations(db_session)

    await repo.ensure_whatsapp(
        tenant.id, guest_id=guest.id, property_id=prop.id, reservation_id=reservation.id,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW,
    )
    second = await repo.ensure_whatsapp(
        tenant.id, guest_id=guest.id, property_id=prop.id, reservation_id=reservation.id,
        language="en", business_phone_number=OTHER_BUSINESS_NUMBER, now=NOW,
    )

    assert second.language == "es"
    assert second.business_phone_number == BUSINESS_NUMBER


@pytest.mark.asyncio
async def test_the_same_guest_writing_about_a_second_property_opens_a_second_thread(
    db_session,
) -> None:
    """D4, confirmed with the user: per guest **and** property, not one thread per guest for
    life — "a message about property B shouldn't surface property A's unrelated history"."""
    tenant, prop, reservation, guest = await whatsapp_fixture(db_session)
    other_property = await seed_property(db_session, tenant, "PAJARITOS8")
    repo = conversations(db_session)

    first = await repo.ensure_whatsapp(
        tenant.id, guest_id=guest.id, property_id=prop.id, reservation_id=reservation.id,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW,
    )
    second = await repo.ensure_whatsapp(
        tenant.id, guest_id=guest.id, property_id=other_property.id, reservation_id=None,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW,
    )

    assert second.id != first.id
    assert second.property_id == other_property.id
    assert first.property_id == prop.id


@pytest.mark.asyncio
async def test_two_guests_at_the_same_property_get_one_thread_each(db_session) -> None:
    """The other half of the key: it is not per property alone either."""
    tenant, prop, reservation, guest = await whatsapp_fixture(db_session)
    other_guest = await seed_guest(
        db_session, tenant, full_name="Bruno Guest", phone="+34698765432"
    )
    repo = conversations(db_session)

    first = await repo.ensure_whatsapp(
        tenant.id, guest_id=guest.id, property_id=prop.id, reservation_id=reservation.id,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW,
    )
    second = await repo.ensure_whatsapp(
        tenant.id, guest_id=other_guest.id, property_id=prop.id,
        reservation_id=reservation.id, language="es",
        business_phone_number=BUSINESS_NUMBER, now=NOW,
    )

    assert second.id != first.id


@pytest.mark.asyncio
async def test_ensure_whatsapp_never_reuses_a_thread_of_another_channel(db_session) -> None:
    """The index predicate, and the mirror of R3.5's portal test: a `PORTAL` (or `MANUAL`)
    thread for the very same guest and property is neither returned nor written into — the
    partial index covers `channel = 'WHATSAPP'` rows only."""
    tenant, prop, reservation, guest = await whatsapp_fixture(db_session)
    portal = await conversations(db_session).ensure_portal(
        tenant.id, reservation_id=reservation.id, property_id=prop.id,
        guest_id=guest.id, language="es", now=NOW,
    )

    created = await conversations(db_session).ensure_whatsapp(
        tenant.id, guest_id=guest.id, property_id=prop.id, reservation_id=reservation.id,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW,
    )

    assert created.id != portal.id
    assert created.channel is ConversationChannel.WHATSAPP
    reread = await conversations(db_session).find_portal(tenant.id, reservation.id)
    assert reread is not None
    assert reread.id == portal.id
    assert reread.business_phone_number is None


@pytest.mark.asyncio
async def test_a_sender_with_no_guest_resolved_gets_a_new_row_per_message(db_session) -> None:
    """D4 and the design's Risks, asserted rather than described: a `NULL` never equals another
    `NULL` in a unique index, so rows whose `guest_id` (or `property_id`) is unresolved do not
    dedupe against each other and an unresolved sender opens a thread per message. Accepted
    for R4.3's rare, operator-visible case rather than given a second index shape.

    It is also the case that makes `RETURNING` the read-back rather than a key lookup: after
    the second call, `guest_id IS NULL AND property_id = :p AND channel = 'WHATSAPP'` matches
    **two** rows, and a lookup by the key would raise `MultipleResultsFound` here — a failure
    that would surface in production as a `500` on a guest's first message.
    """
    tenant, prop, _, _ = await whatsapp_fixture(db_session)
    repo = conversations(db_session)

    first = await repo.ensure_whatsapp(
        tenant.id, guest_id=None, property_id=prop.id, reservation_id=None,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW,
    )
    second = await repo.ensure_whatsapp(
        tenant.id, guest_id=None, property_id=prop.id, reservation_id=None,
        language="es", business_phone_number=BUSINESS_NUMBER, now=NOW + timedelta(minutes=1),
    )

    assert second.id != first.id
    assert second.guest_id is None
    total = await db_session.scalar(
        select(func.count()).select_from(ConversationModel).where(
            ConversationModel.property_id == prop.id,
            ConversationModel.channel == ConversationChannel.WHATSAPP,
        )
    )
    assert total == 2


@pytest.mark.asyncio
async def test_two_simultaneous_whatsapp_messages_land_in_one_thread(
    db_session, test_engine
) -> None:
    """The concurrency contract of D4, against real Postgres and with the same four steps as
    its `ensure_portal` sibling above: the winner inserts without committing, the loser blocks
    on the speculative-insertion lock, `assert not pending.done()` proves the contention
    happened, and on waking the loser takes the `DO NOTHING` branch **without raising** and
    reads the winner's row.

    It discriminates the same two implementations, and one more of its own: this method reads
    its row back through `RETURNING id` on the winning path, so the losing path is the *only*
    one that goes through the key lookup. A `RETURNING` that leaked the loser's non-row as
    `None` into the entity, or a key lookup that matched nothing, dies here rather than in
    production.
    """
    tenant = await seed_tenant(db_session, "TenantA")
    prop = await seed_property(db_session, tenant, "REDES11")
    guest = await seed_guest(db_session, tenant)
    tenant_id, property_id, guest_id = tenant.id, prop.id, guest.id
    await db_session.commit()

    def call(session, *, business_phone_number=BUSINESS_NUMBER):
        return SqlAlchemyConversationRepository(session).ensure_whatsapp(
            tenant_id,
            guest_id=guest_id,
            property_id=property_id,
            reservation_id=None,
            language="es",
            business_phone_number=business_phone_number,
            now=NOW,
        )

    async with AsyncSession(test_engine, expire_on_commit=False) as winner, AsyncSession(
        test_engine, expire_on_commit=False
    ) as loser:
        # **Both connections are opened before the race starts.** With `NullPool` each
        # `AsyncSession` opens a fresh asyncpg connection on its first statement, and inside
        # the full suite that setup can take longer than the lock-observation window below —
        # which fails the test for a reason that has nothing to do with the contract it
        # checks (seen for real: green alone, red in `pytest tests/messaging/`). Warming both
        # leaves the window measuring the lock and nothing else.
        await winner.execute(text("SELECT 1"))
        await loser.execute(text("SELECT 1"))

        first = await call(winner)

        pending = asyncio.create_task(call(loser, business_phone_number=OTHER_BUSINESS_NUMBER))
        try:
            # A longer deadline than the portal sibling's default for the same reason: this
            # test runs late in a long file, on a host that may be carrying other suites.
            assert await _wait_until_a_backend_blocks_on_a_lock(
                test_engine, timeout=30.0
            ), "the loser never blocked on the winner's row: the two did not race"
            assert not pending.done()

            await winner.commit()

            second = await pending
            assert second.id == first.id
            # The loser read the winner's row rather than its own values: the thread keeps the
            # number it was opened on, which is what a reply will leave from.
            assert second.business_phone_number == BUSINESS_NUMBER
            await loser.commit()
        finally:
            # Same reason as the portal sibling: a failure must not leave a blocked
            # transaction behind, or the next test's truncation waits on it until
            # `lock_timeout` and one red test becomes a cascade.
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pending

    async with AsyncSession(test_engine) as observer:
        total = await observer.scalar(
            select(func.count()).select_from(ConversationModel).where(
                ConversationModel.guest_id == guest_id,
                ConversationModel.channel == ConversationChannel.WHATSAPP,
            )
        )
    assert total == 1


def test_saving_a_conversation_can_never_rewrite_the_business_number() -> None:
    """"Set once… and never changed after" (D4 addendum) survives `save` too, and not by
    discipline: `save` writes only `_MUTABLE_CONVERSATION_COLUMNS`, and this field is not one
    of them. Adding it there is what this test exists to catch — a reply would then start
    leaving from a number the guest never wrote to."""
    assert "business_phone_number" not in _MUTABLE_CONVERSATION_COLUMNS
