import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

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


# --- The guest-portal actor column (`guest-portal-api` R6.1, design D11) --------------


@pytest.mark.asyncio
async def test_a_guest_portal_row_records_its_bearer_and_no_user(db_session) -> None:
    """R6.1. The two actor columns are alternatives, and this is the anonymous one."""
    tenant = await _tenant(db_session)
    token_hash = "b" * 64

    entry = AuditLogModel(
        tenant_id=tenant.id,
        actor_guest_token_hash=token_hash,
        actor_ip="203.0.113.9",
        action="GUEST_DOCUMENT_UPDATED",
        entity_type="GUEST",
        entity_id=uuid.uuid4(),
    )
    db_session.add(entry)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(AuditLogModel).where(AuditLogModel.id == entry.id))
    ).scalar_one()
    assert fetched.actor_guest_token_hash == token_hash
    assert fetched.actor_user_id is None


@pytest.mark.asyncio
async def test_the_guest_actor_column_is_nullable_and_sixty_four_wide() -> None:
    """Every pre-existing writer leaves it NULL, so it cannot be `NOT NULL`."""
    column = AuditLogModel.__table__.c.actor_guest_token_hash

    assert column.nullable is True
    assert column.type.length == 64


@pytest.mark.asyncio
async def test_the_actor_index_still_covers_only_the_user_actor(db_session) -> None:
    """D11 leaves `ix_audit_logs_tenant_id_actor_user_id_created_at` alone, deliberately.

    Guest-portal rows fall in that index's NULL bucket, and the question it exists to answer
    — "everything this person did", cheaply, across entities — is about users. Widening it to
    a second actor column would double its size to serve a query nobody asks.
    """
    definition = (
        await db_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_audit_logs_tenant_id_actor_user_id_created_at'"
            )
        )
    ).scalar_one()

    assert "actor_guest_token_hash" not in definition


@pytest.mark.asyncio
async def test_the_database_itself_refuses_a_cleartext_guest_token(db_session) -> None:
    """R1.2/R6.4 of `guest-portal-api`, enforced below the application.

    `AuditLogFactory` rejects it too, and with a better message — but `AuditLog` is a plain
    mutable dataclass, so a caller can build one directly or mutate the field after the
    factory returned. The security panel of section 1 made the point that the guarantee must
    not depend on every future writer remembering the factory. A `secrets.token_urlsafe(32)`
    value is 43 characters, so `VARCHAR(64)` would take it without complaint.
    """
    tenant = await _tenant(db_session)

    db_session.add(
        AuditLogModel(
            tenant_id=tenant.id,
            actor_guest_token_hash="not-a-digest",
            action="GUEST_DOCUMENT_UPDATED",
            entity_type="GUEST",
            entity_id=uuid.uuid4(),
        )
    )

    with pytest.raises(
        IntegrityError, match="ck_audit_logs_actor_guest_token_hash_is_a_digest"
    ):
        await db_session.flush()


@pytest.mark.asyncio
async def test_the_check_still_allows_the_column_to_be_absent(db_session) -> None:
    """Every pre-existing writer leaves it NULL; the CHECK must not break them.

    The positive half, so the test above cannot pass by rejecting everything.
    """
    tenant = await _tenant(db_session)

    db_session.add(
        AuditLogModel(
            tenant_id=tenant.id,
            action="USER_UPDATED",
            entity_type="USER",
            entity_id=uuid.uuid4(),
        )
    )
    await db_session.flush()  # must not raise
