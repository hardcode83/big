import uuid

import pytest
from sqlalchemy import select, text

from app.audit.infrastructure.models import AuditLogModel
from app.auth.infrastructure.models import UserModel
from app.tenants.infrastructure.models import TenantModel


async def _tenant(db_session) -> TenantModel:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.mark.asyncio
async def test_audit_log_roundtrip(db_session) -> None:
    tenant = await _tenant(db_session)

    entry = AuditLogModel(
        tenant_id=tenant.id,
        action="reservation.update",
        entity_type="Reservation",
        entity_id=uuid.uuid4(),
        changes={"status": {"old": "CONFIRMED", "new": "CANCELLED"}},
    )
    db_session.add(entry)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(AuditLogModel).where(AuditLogModel.id == entry.id))
    ).scalar_one()
    assert fetched.actor_user_id is None
    assert fetched.created_at is not None
    assert fetched.changes["status"]["new"] == "CANCELLED"


@pytest.mark.asyncio
async def test_audit_log_survives_the_purge_of_its_actor(db_session) -> None:
    """SET NULL, not RESTRICT: purging a user must not erase the audit trail."""
    tenant = await _tenant(db_session)
    actor = UserModel(
        tenant_id=tenant.id,
        name="Manager Mar",
        email="mar@example.com",
        password_hash="hash",
        role="PROPERTY_MANAGER",
    )
    db_session.add(actor)
    await db_session.flush()

    entry = AuditLogModel(
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        actor_ip="203.0.113.7",
        action="user.role_change",
        entity_type="User",
        entity_id=uuid.uuid4(),
    )
    db_session.add(entry)
    await db_session.commit()

    await db_session.delete(actor)
    await db_session.commit()
    await db_session.refresh(entry)

    assert entry.actor_user_id is None
    assert entry.action == "user.role_change"
    assert entry.actor_ip == "203.0.113.7"


@pytest.mark.asyncio
async def test_audit_log_polymorphic_entity_reference_has_no_foreign_key() -> None:
    assert AuditLogModel.__table__.c.entity_id.foreign_keys == set()
    assert AuditLogModel.__table__.c.entity_id.nullable is False


@pytest.mark.asyncio
async def test_audit_log_index_keeps_the_descending_order(db_session) -> None:
    """§7.25 asks for created_at DESC; a plain index would silently lose it."""
    definition = (
        await db_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_audit_logs_tenant_id_actor_user_id_created_at'"
            )
        )
    ).scalar_one()

    assert "created_at DESC" in definition

    lookup = (
        await db_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_audit_logs_tenant_id_entity_type_entity_id'"
            )
        )
    ).scalar_one()
    assert "entity_type" in lookup and "entity_id" in lookup
