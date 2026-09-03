"""The two vocabularies this change adds, pinned by name (R2.3, design D5, D10).

Names and not counts: a test that only asserted `len(MessageIntent) == 14` would pass a
rename, and a rename is exactly what this pins. `messages.intent` is a `VARCHAR(100)`, so
the enum member's *name* is what every persisted row carries — change it in Python and the
rows written yesterday stop mapping, silently.
"""

from app.messaging.domain.enums import ConversationChannel, EscalationReason, MessageIntent

#: PRD §13, in the order it lists them.
PRD_INTENTS = (
    "CHECKIN_INSTRUCTIONS",
    "ACCESS_PROBLEM",
    "WIFI",
    "PARKING",
    "LATE_CHECKOUT",
    "EARLY_CHECKIN",
    "CLEANING_ISSUE",
    "MAINTENANCE_ISSUE",
    "NOISE",
    "REFUND_OR_COMPENSATION",
    "EMERGENCY",
    "GENERAL_FAQ",
    "REVIEW_REQUEST",
    "UNKNOWN",
)

#: The six conditions of PRD §13 plus the one D10 declares as a divergence.
DESIGN_ESCALATION_REASONS = (
    "EMERGENCY_KEYWORD",
    "LOW_CONFIDENCE",
    "EMERGENCY_INTENT",
    "REFUND_OR_COMPENSATION",
    "IMMINENT_CHECKIN_ACCESS_PROBLEM",
    "REPEATED_INTENT",
    "DELIVERY_FAILED",
)


def test_message_intent_declares_the_fourteen_names_of_the_prd() -> None:
    assert tuple(member.name for member in MessageIntent) == PRD_INTENTS


def test_message_intent_values_equal_their_names() -> None:
    """What is persisted is the name. Any drift between the two is a migration nobody wrote."""
    assert all(member.value == member.name for member in MessageIntent)


def test_escalation_reason_declares_the_seven_of_the_design() -> None:
    assert tuple(member.name for member in EscalationReason) == DESIGN_ESCALATION_REASONS


def test_escalation_reason_values_equal_their_names() -> None:
    assert all(member.value == member.name for member in EscalationReason)


def test_delivery_failed_is_the_only_reason_outside_the_prd() -> None:
    """D10 names it a divergence, so it must stay visibly separable from the PRD's six."""
    prd_reasons = set(DESIGN_ESCALATION_REASONS) - {"DELIVERY_FAILED"}

    assert len(prd_reasons) == 6
    assert EscalationReason.DELIVERY_FAILED.name not in prd_reasons


def test_conversation_channel_declares_portal() -> None:
    """`guest-portal-messaging` R3.1. Pinned by name and value for the same reason as
    `MessageIntent`: `conversations.channel` persists the member's name."""
    assert ConversationChannel.PORTAL in ConversationChannel
    assert ConversationChannel.PORTAL.value == "PORTAL"


def test_conversation_channel_values_equal_their_names() -> None:
    assert all(member.value == member.name for member in ConversationChannel)
