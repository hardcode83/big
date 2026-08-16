"""When a conversation stops being the AI's to answer (R5.1, R4.2; design D10).

Pure: no repositories, no clock, no I/O. The use case gathers the facts and this function
decides, which is what `steering/backend-architecture.md` means by "si hay una regla (no solo
un paso de orquestación), pertenece a `domain/`" — and it is what lets all six conditions be
tested without standing anything up.

**No `requires_escalation` on `MessageClassification`**, although PRD §13 suggests one: that
would put the policy inside the adapter, which is inside what tomorrow is an external
provider. The system decides when it escalates, not the model (D10, Rejected).
"""

from decimal import Decimal

from app.messaging.domain.enums import EscalationReason, MessageIntent
from app.messaging.domain.language import normalise_words
from app.messaging.domain.value_objects import MessageClassification

#: Bumped whenever the keyword lists change, so an operator reading an old escalation can
#: tell which list was in force. `ASSUMPTION` of R5.5: PRD §13 asks for a "lista configurable
#: de palabras clave de emergencia" and this delivers it as a versioned domain constant
#: rather than a `TenantConfig` column — per-tenant configuration needs a migration and a
#: settings UI, both of which belong to `hardening-release`. The constant is replaceable
#: without touching the pipeline.
EMERGENCY_KEYWORDS_VERSION = "2026-08-16.1"

#: Words that mean "stop classifying and get a person", per language. Matched on whole words
#: over accent-folded text, so "intoxicación" and "intoxicacion" both hit and "gasolinera"
#: does not count as "gas".
EMERGENCY_KEYWORDS: dict[str, frozenset[str]] = {
    "es": frozenset(
        {
            "fuego", "incendio", "humo", "gas", "sangre", "sangrando", "herido", "herida",
            "ambulancia", "emergencia", "urgencia", "policia", "bomberos", "robo",
            "inundacion", "intoxicacion", "desmayado", "desmayada", "asfixia",
        }
    ),
    "en": frozenset(
        {
            "fire", "smoke", "gas", "blood", "bleeding", "injured", "hurt",
            "ambulance", "emergency", "urgent", "police", "firefighters", "burglary",
            "flood", "poisoning", "unconscious", "choking",
        }
    ),
}

#: Every emergency word in either language. The check does not depend on the detected
#: language: a guest panicking in a second language is still a guest panicking, and language
#: detection is the coarsest part of this module (D9's own Risks entry).
_ALL_EMERGENCY_KEYWORDS = frozenset().union(*EMERGENCY_KEYWORDS.values())

#: How close to the check-in an access problem has to be to jump the queue (PRD §13, R5.1).
#: **Strictly less than**, like every other threshold in this codebase.
IMMINENT_CHECKIN_HOURS = Decimal(2)

#: More than this many unresolved guest messages carrying the same intent means the AI is
#: not getting anywhere (PRD §13: "más de 2 mensajes"). Strictly greater.
REPEATED_INTENT_LIMIT = 2


def contains_emergency_keyword(content: str) -> bool:
    """Whether the guest's own words say this is an emergency (R5.1, first condition)."""
    return bool(normalise_words(content) & _ALL_EMERGENCY_KEYWORDS)


def evaluate(
    *,
    classification: MessageClassification,
    content: str,
    threshold: Decimal,
    repeated_intent_count: int,
    hours_to_checkin: Decimal | None,
) -> EscalationReason | None:
    """The first condition that holds, or `None` if the AI may answer (R5.1).

    **The order is declared here because the conditions are not exclusive**, and the reason
    recorded is the first that matches. It runs from least to most dependent on the
    classifier:

    1. `EMERGENCY_KEYWORD` — does not depend on the classifier at all, so it is unaffected
       by a model having a bad day.
    2. `LOW_CONFIDENCE` — if the verdict is not trustworthy, nothing downstream of it is, so
       it is decided before any intent-based condition.
    3. `EMERGENCY_INTENT`
    4. `REFUND_OR_COMPENSATION`
    5. `IMMINENT_CHECKIN_ACCESS_PROBLEM`
    6. `REPEATED_INTENT`

    `DELIVERY_FAILED`, the seventh reason, is never returned here: it is not about whether to
    answer but about an answer that could not be delivered, and it is applied by the pipeline
    (D14).
    """
    if contains_emergency_keyword(content):
        return EscalationReason.EMERGENCY_KEYWORD

    if _verdict_is_unusable(classification, threshold):
        return EscalationReason.LOW_CONFIDENCE

    if classification.intent is MessageIntent.EMERGENCY:
        return EscalationReason.EMERGENCY_INTENT

    if classification.intent is MessageIntent.REFUND_OR_COMPENSATION:
        return EscalationReason.REFUND_OR_COMPENSATION

    if (
        classification.intent is MessageIntent.ACCESS_PROBLEM
        and hours_to_checkin is not None
        and hours_to_checkin < IMMINENT_CHECKIN_HOURS
    ):
        return EscalationReason.IMMINENT_CHECKIN_ACCESS_PROBLEM

    if repeated_intent_count > REPEATED_INTENT_LIMIT:
        return EscalationReason.REPEATED_INTENT

    return None


def _verdict_is_unusable(
    classification: MessageClassification, threshold: Decimal
) -> bool:
    """Two ways the classifier can fail to give us something to act on, one reason.

    The first is R4.2's: confidence **strictly less than**
    `TenantConfig.ai_confidence_threshold`. Strictly, because that is the exact edge
    `Incident.classify` uses (`app/maintenance/domain/entities.py:219`), and two capabilities
    disagreeing about a boundary is the kind of divergence nobody notices until it matters.

    The second is `UNKNOWN`, and it is a **precision of D10 rather than one of its six
    conditions**. R2.7 requires the system to escalate for `UNKNOWN` without generating any
    reply, and D7 gives `UNKNOWN` no template — so without this, a classifier confident that
    a message is unclassifiable (or a tenant whose threshold sits below the mock's 0.30)
    would fall through every condition and reach a `KeyError` in the catalogue. There is no
    seventh reason for it because there is nothing new to tell an operator: both mean the
    classifier gave us no verdict to act on, which is what `LOW_CONFIDENCE` already names.
    """
    return (
        classification.confidence < threshold
        or classification.intent is MessageIntent.UNKNOWN
    )
