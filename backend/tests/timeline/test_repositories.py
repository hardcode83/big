"""`SqlAlchemyTimelineEventRepository` — the first persistence of the timeline (R2).

What matters here beyond a round trip: the event keeps the instant and the metadata the
use case decided on, because those are the evidence the timeline exists for.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.exceptions import TimelineMetadataNotSerialisableError
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData
from app.timeline.infrastructure.models import TimelineEventModel
from app.core.tenancy import CrossTenantWriteError
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository


async def _tenant_and_property(db_session, name: str) -> tuple[TenantModel, PropertyModel]:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(tenant_id=tenant.id, name=f"{name} flat", internal_code=f"{name}-1")
    db_session.add(prop)
    await db_session.flush()
    return tenant, prop


def _event(tenant_id: uuid.UUID, property_id: uuid.UUID, *, created_at: datetime):
    return TimelineEventFactory.create(
        TimelineEventData(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=property_id,
            actor_type=TimelineActorType.SYSTEM,
            event_type=TimelineEventType.RESERVATION_IMPORTED,
            title="Reservation imported",
            created_at=created_at,
            severity=TimelineSeverity.INFO,
            description="From the mock PMS",
            metadata={"source": "pms", "external_pms_id": "PMS-1"},
        )
    )


@pytest.mark.asyncio
async def test_it_persists_the_event_with_its_instant_and_metadata(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    decided_at = datetime(2026, 7, 31, 10, 30, tzinfo=UTC)
    event = _event(tenant.id, prop.id, created_at=decided_at)

    await SqlAlchemyTimelineEventRepository(db_session).add(tenant.id, event)

    stored = (
        await db_session.execute(select(TimelineEventModel).where(TimelineEventModel.id == event.id))
    ).scalar_one()
    assert stored.event_type is TimelineEventType.RESERVATION_IMPORTED
    assert stored.actor_type is TimelineActorType.SYSTEM
    assert stored.actor_user_id is None
    assert stored.title == "Reservation imported"
    assert stored.description == "From the mock PMS"
    # The use case's instant, not the server's `now()` — sibling events of one
    # operation have to share it.
    assert stored.created_at == decided_at
    assert stored.metadata_ == {"source": "pms", "external_pms_id": "PMS-1"}


@pytest.mark.asyncio
async def test_an_event_without_metadata_stores_null_not_an_empty_object(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    event = _event(tenant.id, prop.id, created_at=datetime.now(UTC))
    event.metadata = {}

    await SqlAlchemyTimelineEventRepository(db_session).add(tenant.id, event)

    stored = (
        await db_session.execute(select(TimelineEventModel).where(TimelineEventModel.id == event.id))
    ).scalar_one()
    assert stored.metadata_ is None


@pytest.mark.asyncio
async def test_it_refuses_metadata_the_jsonb_column_cannot_store(db_session) -> None:
    """A `date` in `metadata` used to surface as an opaque 500 at INSERT time.

    `date`/`Decimal`/`UUID` are the natural types of a reservation's own fields, so this is
    the likely caller mistake — and the error must name the offending key instead of
    arriving as "Object of type date is not JSON serializable" from the driver.
    """
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    event = _event(tenant.id, prop.id, created_at=datetime.now(UTC))
    event.metadata = {"check_in_date": date(2026, 8, 1), "nights": 3}

    with pytest.raises(TimelineMetadataNotSerialisableError) as raised:
        await SqlAlchemyTimelineEventRepository(db_session).add(tenant.id, event)

    assert "check_in_date" in str(raised.value)
    assert "nights" not in str(raised.value)


@pytest.mark.asyncio
async def test_nested_json_native_metadata_is_accepted(db_session) -> None:
    """The change map of `RESERVATION_UPDATED` is nested dicts of strings (R2.2)."""
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    event = _event(tenant.id, prop.id, created_at=datetime.now(UTC))
    event.metadata = {"changed": {"adults": {"from": 2, "to": 3}}}

    await SqlAlchemyTimelineEventRepository(db_session).add(tenant.id, event)

    stored = (
        await db_session.execute(select(TimelineEventModel).where(TimelineEventModel.id == event.id))
    ).scalar_one()
    assert stored.metadata_ == {"changed": {"adults": {"from": 2, "to": 3}}}


@pytest.mark.asyncio
async def test_it_refuses_an_event_of_another_tenant(db_session) -> None:
    tenant_a, _ = await _tenant_and_property(db_session, "TenantA")
    tenant_b, prop_b = await _tenant_and_property(db_session, "TenantB")
    foreign = _event(tenant_b.id, prop_b.id, created_at=datetime.now(UTC))

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyTimelineEventRepository(db_session).add(tenant_a.id, foreign)
