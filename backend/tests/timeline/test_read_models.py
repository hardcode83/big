"""`TenantActivityEntry.from_rendered` (`dashboard-activity-feed` design D6, R3.1)."""

import uuid
from datetime import UTC, datetime

from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.read_models import TenantActivityEntry, from_rendered
from app.timeline.domain.rendering import RenderedEntry

RENDERED = RenderedEntry(
    id=uuid.uuid4(),
    occurred_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    actor_type=TimelineActorType.SYSTEM,
    event_type=TimelineEventType.RESERVATION_IMPORTED,
    severity=TimelineSeverity.INFO,
    title="Reservation imported from beds24",
    description="A description",
)


def test_from_rendered_maps_all_ten_fields() -> None:
    property_id = uuid.uuid4()

    entry = from_rendered(
        RENDERED,
        property_id=property_id,
        property_name="Flat by the beach",
        property_internal_code="REDES11",
    )

    assert entry == TenantActivityEntry(
        id=RENDERED.id,
        occurred_at=RENDERED.occurred_at,
        actor_type=RENDERED.actor_type,
        event_type=RENDERED.event_type,
        severity=RENDERED.severity,
        title=RENDERED.title,
        description=RENDERED.description,
        property_id=property_id,
        property_name="Flat by the beach",
        property_internal_code="REDES11",
    )


def test_from_rendered_keeps_none_identity_fields_as_none_not_dropped() -> None:
    """Design D6: a dangling/cross-tenant `property_id` resolves to `None` names, and
    `from_rendered` must carry that through verbatim rather than dropping the fields or
    coercing them to some other falsy value.
    """
    property_id = uuid.uuid4()

    entry = from_rendered(
        RENDERED,
        property_id=property_id,
        property_name=None,
        property_internal_code=None,
    )

    assert entry.property_id == property_id
    assert entry.property_name is None
    assert entry.property_internal_code is None
