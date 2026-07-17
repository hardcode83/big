import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.infrastructure.models import UserModel
from app.messaging.domain.enums import ConversationChannel, MessageSenderType
from app.messaging.infrastructure.models import ConversationModel, MessageModel
from app.tenants.infrastructure.models import TenantModel


async def _tenant(db_session):
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.mark.asyncio
async def test_conversation_roundtrip(db_session) -> None:
    tenant = await _tenant(db_session)

    conversation = ConversationModel(tenant_id=tenant.id, channel=ConversationChannel.WHATSAPP)
    db_session.add(conversation)
    await db_session.commit()

    result = await db_session.execute(select(ConversationModel).where(ConversationModel.id == conversation.id))
    fetched = result.scalar_one()
    assert fetched.status.value == "OPEN"
    assert fetched.language == "es"
    assert fetched.ai_enabled is True
    assert fetched.escalation_status.value == "NONE"
    assert fetched.property_id is None
    assert fetched.reservation_id is None
    assert fetched.guest_id is None
    assert fetched.last_message_at is None


@pytest.mark.asyncio
async def test_message_roundtrip_and_metadata_column(db_session) -> None:
    tenant = await _tenant(db_session)
    conversation = ConversationModel(tenant_id=tenant.id, channel=ConversationChannel.WHATSAPP)
    db_session.add(conversation)
    await db_session.flush()

    message = MessageModel(
        conversation_id=conversation.id,
        sender_type=MessageSenderType.AI,
        content="Check-in is at 3pm.",
        metadata_={"intent_confidence": 0.92},
    )
    db_session.add(message)
    await db_session.commit()

    result = await db_session.execute(select(MessageModel).where(MessageModel.id == message.id))
    fetched = result.scalar_one()
    assert fetched.ai_generated is False
    assert fetched.metadata_ == {"intent_confidence": 0.92}


@pytest.mark.asyncio
async def test_message_conversation_restrict_on_delete(db_session) -> None:
    tenant = await _tenant(db_session)
    conversation = ConversationModel(tenant_id=tenant.id, channel=ConversationChannel.EMAIL)
    db_session.add(conversation)
    await db_session.flush()

    db_session.add(
        MessageModel(conversation_id=conversation.id, sender_type=MessageSenderType.GUEST, content="Hello?")
    )
    await db_session.commit()

    await db_session.delete(conversation)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_message_sender_user_set_null_on_user_delete(db_session) -> None:
    tenant = await _tenant(db_session)
    conversation = ConversationModel(tenant_id=tenant.id, channel=ConversationChannel.MANUAL)
    db_session.add(conversation)
    await db_session.flush()

    manager = UserModel(
        tenant_id=tenant.id,
        name="Manager Mia",
        email="mia@example.com",
        password_hash="hash",
        role="PROPERTY_MANAGER",
    )
    db_session.add(manager)
    await db_session.flush()

    message = MessageModel(
        conversation_id=conversation.id,
        sender_type=MessageSenderType.MANAGER,
        content="I'll take it from here.",
        sender_user_id=manager.id,
    )
    db_session.add(message)
    await db_session.commit()

    await db_session.delete(manager)
    await db_session.commit()

    await db_session.refresh(message)
    assert message.sender_user_id is None
