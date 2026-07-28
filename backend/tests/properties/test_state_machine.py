import pytest


def test_property_state_trigger_catalog_is_closed() -> None:
    from app.properties.domain.transition_enums import PropertyStateTrigger

    assert [member.value for member in PropertyStateTrigger] == [
        "CHECKIN_WINDOW_OPENED",
        "CHECKIN_TIME_REACHED",
        "CHECKOUT_TIME_REACHED",
        "RESERVATION_CANCELLED_BEFORE_CHECKIN",
        "CLEANER_ASSIGNED",
        "CLEANER_REJECTED",
        "CLEANING_ASSIGNMENT_EXPIRED",
        "CLEANING_STARTED",
        "CLEANING_COMPLETED",
        "INCIDENT_HIGH",
        "INCIDENT_CRITICAL",
        "INCIDENT_RESOLVED",
        "OWNER_BLOCKED",
        "PROPERTY_MARKED_OUT_OF_SERVICE",
        "PROPERTY_REACTIVATED",
        "OWNER_MANAGER_UNBLOCKED",
    ]
    with pytest.raises(ValueError):
        PropertyStateTrigger("DOOR_OPENED")
