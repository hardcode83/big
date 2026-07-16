import uuid
from datetime import datetime, time, timezone

from app.properties.domain.entities import Property, PropertyStateTransition
from app.properties.domain.enums import (
    PropertyOperationalState,
    PropertyStatus,
    StateTransitionTriggeredBy,
)


def test_property_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    prop = Property(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="REDES11",
        internal_code="redes11",
        created_at=now,
        updated_at=now,
    )

    assert prop.current_operational_state == PropertyOperationalState.VACANT_READY
    assert prop.status == PropertyStatus.ACTIVE
    assert prop.default_check_in_time == time(15, 0)
    assert prop.default_check_out_time == time(11, 0)
    assert prop.max_guests == 2


def test_property_state_transition_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    transition = PropertyStateTransition(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        to_state=PropertyOperationalState.AWAITING_CHECKIN,
        triggered_by=StateTransitionTriggeredBy.SYSTEM,
        created_at=now,
    )

    assert transition.from_state is None
    assert transition.triggered_by_user_id is None
    assert transition.metadata == {}
