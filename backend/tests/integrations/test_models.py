import uuid

import pytest
from sqlalchemy import select, text

from app.integrations.infrastructure.models import WebhookEventModel
from app.tenants.infrastructure.models import TenantModel


async def _tenant(db_session) -> TenantModel:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.mark.asyncio
async def test_webhook_event_persists_without_a_tenant(db_session) -> None:
    """§7.26: an unattributed payload is still recorded, not dropped."""
    event = WebhookEventModel(
        provider="octorate",
        event_type="reservation.created",
        payload={"id": "ABC-123"},
    )
    db_session.add(event)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(WebhookEventModel).where(WebhookEventModel.id == event.id)
        )
    ).scalar_one()
    assert fetched.tenant_id is None
    assert fetched.processed is False
    assert fetched.received_at is not None
    assert fetched.payload == {"id": "ABC-123"}


@pytest.mark.asyncio
async def test_webhook_event_defaults_come_from_the_ddl(db_session) -> None:
    """Raw `text()`: Core would apply the Python-side default and prove nothing."""
    await db_session.execute(
        text(
            "INSERT INTO webhook_events (id, provider, event_type, payload) "
            "VALUES (:id, 'beds24', 'reservation.cancelled', '{}'::jsonb)"
        ),
        {"id": uuid.uuid4()},
    )
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(WebhookEventModel).where(WebhookEventModel.provider == "beds24")
        )
    ).scalar_one()
    assert fetched.processed is False
    assert fetched.received_at is not None
    assert fetched.tenant_id is None


@pytest.mark.asyncio
async def test_webhook_event_tenant_restrict_on_delete(db_session) -> None:
    """The FK is nullable but still a real FK: it cannot outlive its tenant silently."""
    from sqlalchemy.exc import IntegrityError

    tenant = await _tenant(db_session)
    db_session.add(
        WebhookEventModel(
            tenant_id=tenant.id,
            provider="octorate",
            event_type="reservation.created",
            payload={},
        )
    )
    await db_session.commit()

    await db_session.delete(tenant)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_webhook_events_declares_the_prd_index_in_order(db_session) -> None:
    """§7.26 fixes the ORDER, not just the membership: INDEX(provider, processed, received_at).

    Asserting the ordered column list rather than three substrings: a B-tree only
    serves the leftmost prefixes of its column order, so a reordered index optimises
    different queries while a membership check stays green (QA finding, section 3).
    """
    columns = (
        await db_session.execute(
            text(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_attribute a ON a.attrelid = i.indexrelid "
                "WHERE c.relname = 'ix_webhook_events_provider_processed_received_at' "
                "ORDER BY a.attnum"
            )
        )
    ).scalars().all()

    assert list(columns) == ["provider", "processed", "received_at"]


@pytest.mark.asyncio
async def test_webhook_events_does_not_use_the_tenant_scoped_mixin() -> None:
    """The column is hand-declared precisely because the mixin forbids NULL (D4)."""
    from app.core.db import TenantScopedMixin

    assert not issubclass(WebhookEventModel, TenantScopedMixin)
    assert WebhookEventModel.__table__.c.tenant_id.nullable is True
    assert WebhookEventModel.__table__.c.tenant_id.foreign_keys
