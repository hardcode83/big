import pytest
from sqlalchemy import select

from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.infrastructure.models import TimelineEventModel


@pytest.mark.asyncio
async def test_timeline_event_roundtrip_with_metadata(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    db_session.add(prop)
    await db_session.flush()

    event = TimelineEventModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        actor_type=TimelineActorType.SYSTEM,
        event_type=TimelineEventType.PROPERTY_STATE_CHANGED,
        title="Property state changed",
        metadata_={"foo": "bar"},
    )
    db_session.add(event)
    await db_session.commit()

    result = await db_session.execute(
        select(TimelineEventModel).where(TimelineEventModel.id == event.id)
    )
    fetched = result.scalar_one()
    assert fetched.severity == TimelineSeverity.INFO
    assert fetched.metadata_ == {"foo": "bar"}
