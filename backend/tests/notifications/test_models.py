import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select

from app.auth.infrastructure.models import UserModel
from app.notifications.domain.enums import NotificationChannel
from app.notifications.infrastructure.models import NotificationLogModel
from app.tenants.infrastructure.models import TenantModel


async def _tenant(db_session) -> TenantModel:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.mark.asyncio
async def test_notification_log_roundtrip_applies_the_prd_defaults(db_session) -> None:
    tenant = await _tenant(db_session)

    log = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_contact="owner@example.com",
        channel=NotificationChannel.EMAIL,
        notification_type="cleaning.assigned",
    )
    db_session.add(log)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(NotificationLogModel).where(NotificationLogModel.id == log.id)
        )
    ).scalar_one()
    assert fetched.status.value == "PENDING"
    assert fetched.attempts == 0
    assert fetched.sla_breached is False
    assert fetched.recipient_user_id is None


@pytest.mark.asyncio
async def test_notification_log_recipient_set_null_on_user_delete(db_session) -> None:
    tenant = await _tenant(db_session)
    recipient = UserModel(
        tenant_id=tenant.id,
        name="Owner Olga",
        email="olga@example.com",
        password_hash="hash",
        role="TENANT_OWNER",
    )
    db_session.add(recipient)
    await db_session.flush()

    log = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_user_id=recipient.id,
        recipient_contact="olga@example.com",
        channel=NotificationChannel.PUSH,
        notification_type="incident.opened",
    )
    db_session.add(log)
    await db_session.commit()

    await db_session.delete(recipient)
    await db_session.commit()
    await db_session.refresh(log)

    assert log.recipient_user_id is None
    assert log.recipient_contact == "olga@example.com"


@pytest.mark.asyncio
async def test_notification_log_polymorphic_reference_has_no_foreign_key(db_session) -> None:
    """§7.24: related_id points at a different table per related_type (D7)."""
    tenant = await _tenant(db_session)

    log = NotificationLogModel(
        tenant_id=tenant.id,
        recipient_contact="+34600000000",
        channel=NotificationChannel.WHATSAPP,
        notification_type="cleaning.sla_breach",
        related_type="CleaningTask",
        related_id=uuid.uuid4(),
        sla_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db_session.add(log)
    await db_session.commit()

    assert NotificationLogModel.__table__.c.related_id.foreign_keys == set()


@pytest.mark.asyncio
async def test_notification_log_declares_both_prd_indexes(db_session) -> None:
    indexes = await db_session.run_sync(
        lambda sync_session: inspect(sync_session.get_bind()).get_indexes("notification_logs")
    )
    by_name = {index["name"]: index["column_names"] for index in indexes}

    assert by_name["ix_notification_logs_tenant_id_status_sla_deadline_at"] == [
        "tenant_id",
        "status",
        "sla_deadline_at",
    ]
    assert by_name["ix_notification_logs_related_type_related_id"] == [
        "related_type",
        "related_id",
    ]
