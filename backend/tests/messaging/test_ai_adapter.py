"""`MockAIAdapter`: deterministic, offline, and unable to quote the guest (R2.5, R2.7, R3.3).

The confidences are pinned by value because they are load-bearing rather than cosmetic: PRD
§13 names `0.80` for a recognised intent, and the unrecognised one must sit **below**
`TenantConfig.ai_confidence_threshold`'s default of `0.75` so that the escalation path is
exercised by the mock itself and not only by a test that fabricates a low confidence by hand
(R2.5).
"""

import uuid
from decimal import Decimal

import pytest

from app.messaging.domain.enums import ConversationChannel, MessageIntent
from app.messaging.domain.templates import (
    INTENTS_WITHOUT_TEMPLATE,
    RESPONSE_TEMPLATES,
    RESPONSE_VOCABULARY,
    TEMPLATE_CATALOGUE_VERSION,
)
from app.messaging.domain.value_objects import ConversationContext, GeneratedResponse
from app.messaging.infrastructure.ai import (
    ADAPTER_NAME,
    CATALOGUE_VERSION,
    MockAIAdapter,
    _KEYWORDS,
)
from app.tenants.domain.value_objects import SUPPORTED_LANGUAGES

#: `TenantConfig.ai_confidence_threshold`'s default.
DEFAULT_THRESHOLD = Decimal("0.75")

CONTEXT = ConversationContext(
    conversation_id=uuid.uuid4(),
    property_id=uuid.uuid4(),
    reservation_id=None,
    channel=ConversationChannel.WHATSAPP,
    language="es",
    ai_enabled=True,
    guest_message_count=1,
)

#: A guest's prose carrying exactly the rule-3 values the census worries about: an identity
#: document, a phone number and a door code. Any adapter that paraphrased its input rather
#: than answering from the catalogue would surface one of these.
LEAKY_MESSAGE = (
    "No puedo entrar. Mi DNI es 12345678Z, mi telefono es +34 600 123 456 y el "
    "codigo que me disteis es 4471."
)
LEAK_MARKERS = ("12345678Z", "600 123 456", "4471", "DNI", "telefono", "codigo")


async def classify(content: str):
    return await MockAIAdapter().classify_message(
        content=content, language="es", context=CONTEXT
    )


# --- Classification (R2.5) ---------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("El wifi no funciona", MessageIntent.WIFI),
        ("The wifi is not working", MessageIntent.WIFI),
        ("Hay humo en la cocina", MessageIntent.EMERGENCY),
        ("Quiero un reembolso", MessageIntent.REFUND_OR_COMPENSATION),
        ("I want a refund", MessageIntent.REFUND_OR_COMPENSATION),
        ("No puedo entrar, la cerradura no abre", MessageIntent.ACCESS_PROBLEM),
        ("La caldera esta rota", MessageIntent.MAINTENANCE_ISSUE),
        ("The boiler is broken", MessageIntent.MAINTENANCE_ISSUE),
        ("El piso esta sucio", MessageIntent.CLEANING_ISSUE),
        ("Hay mucho ruido de los vecinos", MessageIntent.NOISE),
        ("Donde esta el parking", MessageIntent.PARKING),
        ("Necesito las instrucciones de llegada", MessageIntent.CHECKIN_INSTRUCTIONS),
        ("Can I have a late checkout", MessageIntent.LATE_CHECKOUT),
        ("Quiero dejar una valoracion", MessageIntent.REVIEW_REQUEST),
    ],
)
async def test_a_recognised_message_is_classified_with_the_prd_confidence(
    content: str, expected: MessageIntent
) -> None:
    classification = await classify(content)

    assert classification.intent is expected
    assert classification.confidence == Decimal("0.80")


@pytest.mark.asyncio
async def test_an_unrecognised_message_is_unknown_below_the_default_threshold() -> None:
    """R2.5's second half, and the reason the number matters: below `0.75` means the mock
    itself drives a message down the escalation path, so that path is exercised by the
    system rather than only by a fabricated test value."""
    classification = await classify("zzz qqq")

    assert classification.intent is MessageIntent.UNKNOWN
    assert classification.confidence == Decimal("0.30")
    assert classification.confidence < DEFAULT_THRESHOLD


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("What time is check-in?", MessageIntent.CHECKIN_INSTRUCTIONS),
        ("A que hora es el check-in?", MessageIntent.CHECKIN_INSTRUCTIONS),
        ("Can I get an early check-in tomorrow?", MessageIntent.EARLY_CHECKIN),
        ("Quiero entrada anticipada", MessageIntent.EARLY_CHECKIN),
        ("Is late check-out possible?", MessageIntent.LATE_CHECKOUT),
        ("Tengo una pregunta sobre la piscina", MessageIntent.GENERAL_FAQ),
    ],
)
async def test_a_hyphenated_phrase_is_recognised(
    content: str, expected: MessageIntent
) -> None:
    """**The class of bug this table has now produced three times.**

    `fold` splits on `[a-z0-9]+`, so "check-in" becomes two tokens — and a hyphenated keyword
    can never match, through either matching path. Three entries were written that way and
    were dead: "What time is check-in?", the single most likely message this system will ever
    receive, classified as `UNKNOWN` and escalated. Found by the QA panel of sections 5-6.
    """
    assert (await classify(content)).intent is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent",
    sorted(
        {intent for intent, _ in _KEYWORDS}, key=lambda member: member.value
    ),
)
async def test_every_intent_in_the_table_is_reachable(intent: MessageIntent) -> None:
    """A keyword table entry no message can reach is a promise the table does not keep.

    Driven off `_KEYWORDS` itself rather than a hand-written list, so an intent added later
    arrives here automatically — and one whose keywords are entirely shadowed by an earlier
    entry fails, which is exactly how the three hyphenated entries above stayed dead.
    """
    keywords = dict(_KEYWORDS)[intent]
    reachable = [
        keyword
        for keyword in keywords
        if (await MockAIAdapter().classify_message(
            content=keyword, language="es", context=CONTEXT
        )).intent is intent
    ]

    assert reachable, (
        f"no keyword of {intent.value} classifies as {intent.value}: every one of "
        f"{list(keywords)} is unreachable or shadowed by an earlier entry"
    )


@pytest.mark.asyncio
async def test_classification_is_deterministic() -> None:
    """`steering/testing.md`: nothing random in a suite that runs in parallel. Two calls on
    the same text must be the same verdict, or every test here is an approximation."""
    first = await classify("El wifi no funciona")
    second = await classify("El wifi no funciona")

    assert first == second


@pytest.mark.asyncio
async def test_accents_and_case_do_not_change_the_verdict() -> None:
    assert (await classify("La CALEFACCIÓN está rota")).intent is (
        await classify("la calefaccion esta rota")
    ).intent


@pytest.mark.asyncio
async def test_a_keyword_matches_whole_words_only() -> None:
    """"gas" inside "gasolinera" is the failure the word-set rule exists to prevent."""
    assert (await classify("Hay una gasolinera cerca?")).intent is not MessageIntent.EMERGENCY


@pytest.mark.asyncio
async def test_the_order_of_the_keyword_table_is_the_tie_break() -> None:
    """A message naming both a refund and the wifi is a refund conversation that happens to
    mention the wifi — and it escalates rather than being answered."""
    classification = await classify("Quiero un reembolso porque el wifi no funciona")

    assert classification.intent is MessageIntent.REFUND_OR_COMPENSATION


@pytest.mark.asyncio
async def test_a_bare_verb_phrase_does_not_decide_the_intent() -> None:
    """"no funciona" describes whatever noun precedes it, so it belongs to no intent.

    It was a `MAINTENANCE_ISSUE` keyword in the first version of the table, and since that
    intent sits above `WIFI` on the tie-break, "el wifi no funciona" — the single most likely
    message this system will ever receive — was classified as a maintenance issue and would
    have opened an incident for a router. Same lesson `RuleBasedIncidentClassifier` records
    for `keypad`.
    """
    assert (await classify("El wifi no funciona")).intent is MessageIntent.WIFI
    assert (await classify("La caldera no funciona")).intent is MessageIntent.MAINTENANCE_ISSUE
    assert (await classify("no funciona")).intent is MessageIntent.UNKNOWN


@pytest.mark.asyncio
async def test_an_emergency_beats_every_other_intent_in_the_table() -> None:
    classification = await classify("Hay fuego y el wifi no funciona y quiero un reembolso")

    assert classification.intent is MessageIntent.EMERGENCY


@pytest.mark.asyncio
async def test_the_classification_never_carries_the_guests_words() -> None:
    """`MessageClassification` has no string field at all, so there is nowhere for the input
    to ride out — asserted rather than assumed, because this is the object handed to whatever
    logs the classification."""
    classification = await classify(LEAKY_MESSAGE)

    rendered = repr(classification)
    for marker in LEAK_MARKERS:
        assert marker.lower() not in rendered.lower()


# --- Generation (R2.6, R2.7, R3.3) -------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent",
    sorted(
        {intent for intent, _ in RESPONSE_TEMPLATES}, key=lambda member: member.value
    ),
)
@pytest.mark.parametrize("language", list(SUPPORTED_LANGUAGES))
async def test_every_answerable_intent_produces_a_catalogue_constant(
    intent: MessageIntent, language: str
) -> None:
    """The mechanism of R3.3: what reaches `messages.content` when the writer is ours is
    *literally* a member of the catalogue."""
    response = await MockAIAdapter().generate_response(
        intent=intent, language=language, context=CONTEXT
    )

    assert isinstance(response, GeneratedResponse)
    assert response.content in RESPONSE_VOCABULARY
    assert response.content == RESPONSE_TEMPLATES[(intent, language)]
    assert response.template_key == f"{intent.value}:{language}"
    assert response.language == language


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent", sorted(INTENTS_WITHOUT_TEMPLATE, key=lambda member: member.value)
)
@pytest.mark.parametrize("language", list(SUPPORTED_LANGUAGES))
async def test_the_three_forbidden_intents_fail_loudly(
    intent: MessageIntent, language: str
) -> None:
    """R2.7: "NEVER SHALL invocar `generate_response` para ellos". The catalogue has no entry,
    so a caller that steps over the pipeline's branch gets a `KeyError` instead of sending a
    guest a sentence they should never have received (D7)."""
    with pytest.raises(KeyError):
        await MockAIAdapter().generate_response(
            intent=intent, language=language, context=CONTEXT
        )


@pytest.mark.asyncio
async def test_the_adapter_declares_the_catalogue_as_its_vocabulary() -> None:
    """The admission condition of rule 11 for this column. Not the guarantee — the guarantee
    is the pipeline comparing against `RESPONSE_VOCABULARY` itself — but the condition every
    adapter has to meet, including a real provider in `app/integrations/`."""
    response = await MockAIAdapter().generate_response(
        intent=MessageIntent.WIFI, language="es", context=CONTEXT
    )

    assert response.vocabulary == RESPONSE_VOCABULARY


@pytest.mark.asyncio
async def test_generation_never_reads_the_conversation_context_into_the_reply() -> None:
    """The reply is a constant, so no identifier from the context can appear in it — which is
    what makes the catalogue a closed form rather than a template with the holes hidden."""
    response = await MockAIAdapter().generate_response(
        intent=MessageIntent.WIFI, language="es", context=CONTEXT
    )

    assert str(CONTEXT.conversation_id) not in response.content
    assert str(CONTEXT.property_id) not in response.content


def test_the_adapter_publishes_the_catalogue_version_it_answers_from() -> None:
    """Persisted into `messages.metadata["template_version"]` by the pipeline (D15)."""
    assert CATALOGUE_VERSION == TEMPLATE_CATALOGUE_VERSION


def test_the_adapter_names_itself_with_an_identifier() -> None:
    assert ADAPTER_NAME.isidentifier()
