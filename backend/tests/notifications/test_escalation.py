"""`NotificationType` and the escalation policy — pure domain (`celery-jobs` R5).

No database, no clock: these are the tests `steering/testing.md` asks for first when the
domain holds a real rule.
"""

from app.auth.domain.enums import UserRole
from app.notifications.domain.enums import NotificationType
from app.notifications.domain.escalation import Escalation, escalation_for

# The sixteen names of PRD §14, transcribed from the PRD and not from the enum, so that
# the test fails if the enum drifts rather than agreeing with itself.
PRD_14_TYPES = (
    "CLEANING_TASK_ASSIGNED",
    "CLEANING_NO_RESPONSE",
    "CLEANING_COMPLETED",
    "CLEANING_FAILED",
    "INCIDENT_CREATED_CRITICAL",
    "INCIDENT_CREATED_HIGH",
    "OWNER_APPROVAL_REQUIRED",
    "TECHNICIAN_ASSIGNED",
    "TECHNICIAN_NO_RESPONSE",
    "GUEST_ESCALATION",
    "LOCK_ALERT",
    "CHECKIN_REMINDER_24H",
    "CHECKIN_REMINDER_2H",
    "CHECKOUT_REMINDER",
    "PRICE_RECOMMENDATION",
    "SLA_BREACH",
)


def test_the_enum_is_exactly_the_sixteen_types_of_prd_14() -> None:
    assert tuple(member.value for member in NotificationType) == PRD_14_TYPES


def test_each_member_name_equals_its_value() -> None:
    """The column stores the value; a name/value mismatch would store a surprise."""
    for member in NotificationType:
        assert member.name == member.value


def test_a_breached_cleaning_assignment_escalates_to_the_manager() -> None:
    """The one escalation PRD §14 states outright."""
    escalation = escalation_for("CLEANING_TASK_ASSIGNED")

    assert escalation == Escalation(
        notification_type=NotificationType.SLA_BREACH,
        recipient_role=UserRole.PROPERTY_MANAGER,
        reason="cleaning_assignment_unanswered",
    )


def test_a_breached_technician_assignment_escalates_to_the_manager() -> None:
    """PRD §14 asks for `PhoneAdapter.call`; no such port exists, so it goes to the
    manager and the reason records why instead of pretending a call happened."""
    escalation = escalation_for("TECHNICIAN_ASSIGNED")

    # Exact equality, like the cleaning case above: a substring assertion would survive an
    # edit that interpolated a value into `reason`, and `reason` is rendered into `body`
    # downstream, where rule 11 of `steering/security.md` applies.
    assert escalation == Escalation(
        notification_type=NotificationType.SLA_BREACH,
        recipient_role=UserRole.PROPERTY_MANAGER,
        reason="technician_assignment_unanswered_no_phone_adapter",
    )


def test_every_type_without_a_defined_escalation_returns_none() -> None:
    """Exhaustive over the enum: adding a member forces a decision here, and the default
    decision (R5.6: mark it breached, record it, invent no recipient) is explicit."""
    with_escalation = {
        NotificationType.CLEANING_TASK_ASSIGNED,
        NotificationType.TECHNICIAN_ASSIGNED,
    }

    for member in NotificationType:
        if member in with_escalation:
            assert escalation_for(member.value) is not None
        else:
            assert escalation_for(member.value) is None, member


def test_an_unknown_type_is_not_an_error() -> None:
    """The column is free text; a row this enum has never heard of must not crash a job
    that runs every minute."""
    assert escalation_for("SOMETHING_A_LATER_CHANGE_INVENTED") is None
    assert escalation_for("") is None


def test_the_policy_never_escalates_to_a_role_that_cannot_act() -> None:
    """`CLEANER` and `TECHNICIAN` are the roles that failed to respond in the first
    place, and `SUPER_ADMIN` is global rather than operational (PRD §6)."""
    for member in NotificationType:
        escalation = escalation_for(member.value)
        if escalation is not None:
            assert escalation.recipient_role in {
                UserRole.PROPERTY_MANAGER,
                UserRole.TENANT_OWNER,
            }
