import uuid
from datetime import datetime, timezone

from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity


def test_timeline_event_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    event = TimelineEvent(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        actor_type=TimelineActorType.SYSTEM,
        event_type=TimelineEventType.PROPERTY_STATE_CHANGED,
        title="Property state changed",
        created_at=now,
    )

    assert event.severity == TimelineSeverity.INFO
    assert event.metadata == {}
    assert event.reservation_id is None
    assert event.actor_user_id is None


def test_the_guest_portal_check_in_has_its_own_event_type() -> None:
    """`guest-portal-api` R6.3, design D12.

    A milestone with operational meaning needs a name of its own. The two candidates for
    reuse both say something false: `CHECKIN_WINDOW_OPENED` is the clock reaching a date,
    not a guest doing anything, and `LEGAL_REGISTRATION_SUBMITTED` would assert a filing
    with the police that has not happened — permanently, since the timeline is append-only.
    """
    assert TimelineEventType.GUEST_CHECKIN_COMPLETED.value == "GUEST_CHECKIN_COMPLETED"
    assert TimelineEventType("GUEST_CHECKIN_COMPLETED") is TimelineEventType.GUEST_CHECKIN_COMPLETED


def test_the_guest_actor_type_the_portal_needs_already_exists() -> None:
    """D12: `GUEST` is already in `TimelineActorType`, so nothing is added there."""
    assert TimelineActorType.GUEST.value == "GUEST"
