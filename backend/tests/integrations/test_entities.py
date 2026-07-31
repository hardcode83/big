import uuid
from datetime import datetime, timezone

from app.integrations.domain.entities import WebhookEvent


def test_webhook_event_instantiates_with_defaults() -> None:
    event = WebhookEvent(
        id=uuid.uuid4(),
        provider="octorate",
        event_type="reservation.created",
        payload={"id": "ABC-123"},
        received_at=datetime.now(timezone.utc),
    )

    assert event.tenant_id is None
    assert event.processed is False
    assert event.processed_at is None
    assert event.error is None


def test_webhook_event_accepts_an_attributed_tenant() -> None:
    tenant_id = uuid.uuid4()
    event = WebhookEvent(
        id=uuid.uuid4(),
        provider="smoobu",
        event_type="reservation.updated",
        payload={},
        received_at=datetime.now(timezone.utc),
        tenant_id=tenant_id,
    )

    assert event.tenant_id == tenant_id
