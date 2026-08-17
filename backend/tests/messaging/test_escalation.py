"""The six conditions of PRD §13, one test each, plus the order between them (R5.1, R4.2, R5.6).

The order tests are the ones that matter most: the conditions are **not exclusive**, so a
message can satisfy three at once, and which reason gets recorded is what an operator reads
when deciding what happened. D10 declares that order and this file is what holds it.
"""

from decimal import Decimal

import pytest

from app.messaging.domain.enums import EscalationReason, MessageIntent
from app.messaging.domain.escalation import (
    EMERGENCY_KEYWORDS,
    EMERGENCY_KEYWORDS_VERSION,
    IMMINENT_CHECKIN_HOURS,
    REPEATED_INTENT_LIMIT,
    contains_emergency_keyword,
    evaluate,
)
from app.messaging.domain.value_objects import MessageClassification

#: `TenantConfig.ai_confidence_threshold`'s default.
THRESHOLD = Decimal("0.75")
CONFIDENT = Decimal("0.80")

QUIET = "El wifi de la habitacion no conecta"


def decide(
    *,
    intent: MessageIntent = MessageIntent.WIFI,
    confidence: Decimal = CONFIDENT,
    content: str = QUIET,
    repeated_intent_count: int = 0,
    hours_to_checkin: Decimal | None = None,
) -> EscalationReason | None:
    return evaluate(
        classification=MessageClassification(intent=intent, confidence=confidence),
        content=content,
        threshold=THRESHOLD,
        repeated_intent_count=repeated_intent_count,
        hours_to_checkin=hours_to_checkin,
    )


def test_a_confident_ordinary_message_does_not_escalate() -> None:
    """The control: without it every test below could pass on a function that always escalates."""
    assert decide() is None


# --- The six conditions of PRD §13, one each (R5.1) --------------------------------------


def test_an_emergency_keyword_escalates() -> None:
    assert decide(content="Hay humo en la cocina") is EscalationReason.EMERGENCY_KEYWORD


def test_low_confidence_escalates() -> None:
    assert decide(confidence=Decimal("0.74")) is EscalationReason.LOW_CONFIDENCE


def test_the_emergency_intent_escalates() -> None:
    assert decide(intent=MessageIntent.EMERGENCY) is EscalationReason.EMERGENCY_INTENT


def test_a_refund_request_escalates() -> None:
    """Rule 10 of `steering/security.md`: the AI never promises a refund. It never gets the
    chance — D7 gives this intent no template either."""
    assert (
        decide(intent=MessageIntent.REFUND_OR_COMPENSATION)
        is EscalationReason.REFUND_OR_COMPENSATION
    )


def test_an_access_problem_close_to_check_in_escalates() -> None:
    assert (
        decide(intent=MessageIntent.ACCESS_PROBLEM, hours_to_checkin=Decimal("1.5"))
        is EscalationReason.IMMINENT_CHECKIN_ACCESS_PROBLEM
    )


def test_a_repeated_unresolved_intent_escalates() -> None:
    assert (
        decide(repeated_intent_count=REPEATED_INTENT_LIMIT + 1)
        is EscalationReason.REPEATED_INTENT
    )


# --- The exact edges (R4.2, R5.1) --------------------------------------------------------


def test_confidence_equal_to_the_threshold_does_not_escalate() -> None:
    """R4.2 fixes the comparison as **strictly** less than, so that this capability and
    `maintenance` do not disagree about the boundary. Same edge as `Incident.classify`."""
    assert decide(confidence=THRESHOLD) is None


def test_confidence_one_step_below_the_threshold_escalates() -> None:
    assert decide(confidence=THRESHOLD - Decimal("0.01")) is EscalationReason.LOW_CONFIDENCE


def test_an_access_problem_exactly_at_the_window_does_not_escalate() -> None:
    """"menos de 2 h" — strictly less, like every other threshold here."""
    assert decide(intent=MessageIntent.ACCESS_PROBLEM, hours_to_checkin=IMMINENT_CHECKIN_HOURS) is None


def test_an_access_problem_far_from_check_in_does_not_escalate() -> None:
    assert decide(intent=MessageIntent.ACCESS_PROBLEM, hours_to_checkin=Decimal("30")) is None


def test_exactly_two_repeated_messages_do_not_escalate() -> None:
    """PRD §13 says "más de 2"."""
    assert decide(repeated_intent_count=REPEATED_INTENT_LIMIT) is None


# --- R5.6: no reservation, no imminent check-in, and no failure --------------------------


def test_an_access_problem_without_a_reservation_does_not_escalate_and_does_not_fail() -> None:
    """R5.6 verbatim: "THEN THE SYSTEM SHALL tratar la condición como no cumplida, y NEVER
    SHALL fallar el procesamiento del mensaje por ello."

    `hours_to_checkin` arrives `None` because the conversation has no `reservation_id`, so
    there is no check-in instant to measure from — `effective_bounds` needs a reservation.
    """
    assert decide(intent=MessageIntent.ACCESS_PROBLEM, hours_to_checkin=None) is None


def test_a_conversation_without_a_reservation_still_escalates_for_other_reasons() -> None:
    """The absent reservation must not swallow the conditions that do not need one."""
    assert (
        decide(
            intent=MessageIntent.ACCESS_PROBLEM,
            hours_to_checkin=None,
            content="No puedo entrar y hay humo",
        )
        is EscalationReason.EMERGENCY_KEYWORD
    )


# --- The order between conditions that hold at once (D10) --------------------------------


def test_the_keyword_wins_over_everything_else() -> None:
    """First because it does not depend on the classifier at all: a model having a bad day
    must not be able to suppress "there is smoke"."""
    assert (
        decide(
            intent=MessageIntent.REFUND_OR_COMPENSATION,
            confidence=Decimal("0.10"),
            content="Quiero un reembolso, hay fuego en la cocina",
            repeated_intent_count=99,
            hours_to_checkin=Decimal("0.5"),
        )
        is EscalationReason.EMERGENCY_KEYWORD
    )


def test_low_confidence_wins_over_every_intent_based_condition() -> None:
    """If the verdict is not trustworthy, nothing derived from the intent is either — so
    recording `REFUND_OR_COMPENSATION` here would tell an operator something the classifier
    did not actually establish."""
    assert (
        decide(
            intent=MessageIntent.REFUND_OR_COMPENSATION,
            confidence=Decimal("0.10"),
            repeated_intent_count=99,
        )
        is EscalationReason.LOW_CONFIDENCE
    )


def test_the_keyword_wins_over_the_emergency_intent() -> None:
    """The pair (1, 3), which the catch-all order test above does not isolate.

    Both reasons mean "emergency", so nothing is unsafe either way — but only one of them is
    independent of the classifier, and that independence is the reason condition 1 is first.
    Recording `EMERGENCY_INTENT` would credit the model for something the guest's own words
    established.
    """
    assert (
        decide(intent=MessageIntent.EMERGENCY, content="Hay fuego en la cocina")
        is EscalationReason.EMERGENCY_KEYWORD
    )


def test_the_keyword_wins_over_an_imminent_check_in() -> None:
    """The pair (1, 5). "No puedo entrar y hay fuego" ninety minutes before check-in is not a
    check-in problem, and the reason an operator reads decides how they respond."""
    assert (
        decide(
            intent=MessageIntent.ACCESS_PROBLEM,
            content="No puedo entrar y hay fuego",
            hours_to_checkin=Decimal("1.5"),
        )
        is EscalationReason.EMERGENCY_KEYWORD
    )


def test_low_confidence_wins_over_an_imminent_check_in() -> None:
    """The pair (2, 5). The check-in condition is derived from the intent, so a verdict we do
    not trust must not be the reason recorded for acting on it."""
    assert (
        decide(
            intent=MessageIntent.ACCESS_PROBLEM,
            confidence=Decimal("0.10"),
            hours_to_checkin=Decimal("1.5"),
        )
        is EscalationReason.LOW_CONFIDENCE
    )


def test_low_confidence_wins_over_the_emergency_intent() -> None:
    """The adjacent pair (2, 3), which the other order tests do not reach.

    Without it a swap of these two `if` blocks survives the whole suite — the QA panel of
    sections 3-4 demonstrated it with a mutant — and an operator would read `EMERGENCY_INTENT`
    for a message the classifier was not confident about, i.e. would be told the system
    established something it did not. The conversation escalates either way, so nothing is
    unsafe; what is at stake is that the recorded reason is true.
    """
    assert (
        decide(intent=MessageIntent.EMERGENCY, confidence=Decimal("0.10"))
        is EscalationReason.LOW_CONFIDENCE
    )


def test_the_emergency_intent_wins_over_a_repeated_intent() -> None:
    """The pair (3, 6). Not (3, 4): a message has one intent, so `EMERGENCY` and
    `REFUND_OR_COMPENSATION` cannot both hold and no test of that pair is possible — which is
    why conditions 3 and 4 need no ordering test between them."""
    assert (
        decide(intent=MessageIntent.EMERGENCY, repeated_intent_count=99)
        is EscalationReason.EMERGENCY_INTENT
    )


def test_a_refund_request_wins_over_a_repeated_intent() -> None:
    """The pair (4, 6)."""
    assert (
        decide(intent=MessageIntent.REFUND_OR_COMPENSATION, repeated_intent_count=99)
        is EscalationReason.REFUND_OR_COMPENSATION
    )


def test_an_imminent_check_in_wins_over_a_repeated_intent() -> None:
    assert (
        decide(
            intent=MessageIntent.ACCESS_PROBLEM,
            hours_to_checkin=Decimal("0.5"),
            repeated_intent_count=99,
        )
        is EscalationReason.IMMINENT_CHECKIN_ACCESS_PROBLEM
    )


# --- UNKNOWN (R2.7) ----------------------------------------------------------------------


def test_an_unknown_intent_escalates_even_when_the_classifier_is_confident() -> None:
    """R2.7 requires escalation without a reply for `UNKNOWN`, and D7 gives it no template,
    so a confident `UNKNOWN` falling through every condition would reach a `KeyError` in the
    catalogue. It is recorded as `LOW_CONFIDENCE` because there is nothing else to tell an
    operator: the classifier gave us no verdict to act on."""
    assert (
        decide(intent=MessageIntent.UNKNOWN, confidence=Decimal("0.99"))
        is EscalationReason.LOW_CONFIDENCE
    )


# --- The keyword list itself (R5.5) ------------------------------------------------------


def test_the_keyword_list_is_versioned_and_covers_both_languages() -> None:
    """`ASSUMPTION` of R5.5: a versioned domain constant, not a `TenantConfig` column."""
    assert EMERGENCY_KEYWORDS_VERSION == "2026-08-16.1"
    assert set(EMERGENCY_KEYWORDS) == {"es", "en"}
    assert all(EMERGENCY_KEYWORDS[language] for language in EMERGENCY_KEYWORDS)


def test_a_keyword_matches_whole_words_only() -> None:
    """"gasolinera" is not a gas leak, and "firewall" is not a fire."""
    assert contains_emergency_keyword("Voy a la gasolinera") is False
    assert contains_emergency_keyword("the firewall blocks my laptop") is False
    assert contains_emergency_keyword("Hay gas") is True


def test_a_keyword_matches_regardless_of_the_message_language() -> None:
    """A guest panicking in a second language is still a guest panicking, and D9 records that
    language detection is the coarsest part of this module."""
    assert contains_emergency_keyword("There is humo everywhere") is True


@pytest.mark.parametrize("keyword", sorted(EMERGENCY_KEYWORDS["es"] | EMERGENCY_KEYWORDS["en"]))
def test_every_declared_keyword_actually_triggers(keyword: str) -> None:
    """A word in the list that the matcher cannot reach is a promise the list does not keep."""
    assert contains_emergency_keyword(f"por favor {keyword} ahora") is True
