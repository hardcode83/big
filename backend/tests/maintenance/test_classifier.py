"""The deterministic classifier (R1.1, R1.3, R1.5; design D1, D4).

The test that matters most here is `test_the_summary_never_echoes_the_reported_text`: D4
closes the `ai_summary` sink **by contract**, and a contract with no test is a comment.
"""

from decimal import Decimal

import pytest

from app.maintenance.domain.enums import IncidentCategory, IncidentSeverity
from app.maintenance.domain.value_objects import IncidentClassification
from app.maintenance.infrastructure.classifier import (
    ADAPTER_NAME,
    _SEVERITIES,
    _SUMMARIES,
    RuleBasedIncidentClassifier,
)

pytestmark = pytest.mark.asyncio

CLASSIFIER = RuleBasedIncidentClassifier()


async def test_it_is_deterministic() -> None:
    """D1/D3: a second run must not produce a different verdict, or the job of D2 would
    re-decide an incident it already looked at."""
    first = await CLASSIFIER.classify(
        title="Fuga de agua", description="Sale agua por debajo del fregadero."
    )
    second = await CLASSIFIER.classify(
        title="Fuga de agua", description="Sale agua por debajo del fregadero."
    )

    assert first == second


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Huele a gas en la cocina", IncidentCategory.SAFETY),
        ("There is smoke coming from the oven", IncidentCategory.SAFETY),
        ("La cerradura no abre con la llave", IncidentCategory.LOCK),
        ("The keypad will not accept the code", IncidentCategory.ACCESS),
        ("Hay una fuga de agua en el baño", IncidentCategory.WATER),
        ("El inodoro está atascado", IncidentCategory.PLUMBING),
        ("No hay luz en el salón", IncidentCategory.ELECTRICITY),
        ("La calefacción no calienta", IncidentCategory.HVAC),
        ("La nevera no enfría", IncidentCategory.APPLIANCE),
        ("El wifi no funciona", IncidentCategory.WIFI),
        ("Mucho ruido de los vecinos", IncidentCategory.NOISE),
        ("El piso está sucio", IncidentCategory.CLEANING),
        ("La silla está rota", IncidentCategory.DAMAGE),
    ],
)
async def test_it_recognises_each_category(text: str, category: IncidentCategory) -> None:
    result = await CLASSIFIER.classify(title=text, description=text)

    assert result.category is category
    assert result.severity is _SEVERITIES[category]
    assert result.confidence >= Decimal("0.75")


async def test_an_unrecognised_fault_is_not_a_verdict() -> None:
    """R1.3: below the default threshold, so it stays `OPEN` for a human instead of being
    filed as `OTHER`/`MEDIUM` with an air of certainty."""
    result = await CLASSIFIER.classify(
        title="Consulta", description="Quería preguntar una cosa sobre el piso."
    )

    assert result.category is IncidentCategory.OTHER
    assert result.confidence < Decimal("0.75")


async def test_accents_do_not_change_the_verdict() -> None:
    with_accents = await CLASSIFIER.classify(
        title="La climatización falla", description="No enfría."
    )
    without = await CLASSIFIER.classify(
        title="La climatizacion falla", description="No enfria."
    )

    assert with_accents == without


async def test_matching_is_by_whole_word() -> None:
    """A substring match would read "gasolinera" as a gas leak and open a CRITICAL."""
    result = await CLASSIFIER.classify(
        title="Aparcamiento", description="La gasolinera de al lado cierra tarde."
    )

    assert result.category is not IncidentCategory.SAFETY


async def test_safety_wins_a_tie() -> None:
    """The ordering of `_KEYWORDS` is the tie-break, and it puts safety first: a text about
    smoke and a broken appliance is a safety incident that happens to involve an appliance."""
    result = await CLASSIFIER.classify(
        title="Humo", description="Sale humo del horno."
    )

    assert result.category is IncidentCategory.SAFETY
    assert result.severity is IncidentSeverity.CRITICAL


#: Two tokens no closed summary could ever contain — the shape of what a guest actually
#: leaks into free text. Deliberately not a sentence: common words like "is" are substrings
#: of ordinary English, and the assertion below is about *these values* surviving, not about
#: whether the summary happens to share a letter sequence with a stop word.
DISTINCTIVE = "ES9121000418450200051332 12345678Z"


@pytest.mark.parametrize("category", list(IncidentCategory))
async def test_the_summary_never_echoes_the_reported_text(
    category: IncidentCategory,
) -> None:
    """D4, and the reason it is a security test rather than a style one.

    `incidents.ai_summary` is a rule-11 sink under the structured form by default; its
    writer is ours and its input is prose an anonymous guest typed, so excepción 2 —
    "porque el valor no es nuestro y no lo hemos ido a buscar" — does not cover it. If the
    summary can carry a word of the input, a real provider paraphrasing the description
    copies the guest's document number into a column nobody declared.
    """
    result = await CLASSIFIER.classify(
        title=f"{category.value} {DISTINCTIVE}",
        description=f"{DISTINCTIVE} — algo va mal con {category.value}.",
    )

    assert result.summary in _SUMMARIES.values()
    for token in DISTINCTIVE.split():
        assert token not in result.summary


async def test_every_category_has_a_closed_summary_and_a_severity() -> None:
    """What makes the guarantee above structural: an enum member added without its line
    here fails loudly instead of falling back to something derived from the input."""
    assert set(_SUMMARIES) == set(IncidentCategory)
    assert set(_SEVERITIES) == set(IncidentCategory)


async def test_it_satisfies_the_port_contract() -> None:
    result = await CLASSIFIER.classify(title="El wifi no va", description="Sin internet.")

    assert isinstance(result, IncidentClassification)
    assert Decimal(0) <= result.confidence <= Decimal(1)
    assert ADAPTER_NAME.isidentifier()
