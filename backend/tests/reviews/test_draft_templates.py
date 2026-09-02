"""The catalogue of review-response drafts is closed, complete and has no interpolation
hole (R3.2, R3.4; design D6, D12).

Calqued on `tests/messaging/test_templates.py`, with the same machinery the rule-10
phrase list uses — a `dict[str, tuple[str, ...]]` keyed by clause, one parametrize case
per clause, a stable sort by clause name.

The catalogue is **six** entries: three sentiments × two languages. `IGNORED` and
`POSTED_MANUALLY` never produce a draft (D12), and the absence test pins that.
"""

import pytest

from app.reviews.domain.enums import ReviewSentiment
from app.reviews.domain.exceptions import ReviewValidationError
from app.reviews.domain.templates import (
    REVIEW_DRAFT_TEMPLATES,
    REVIEW_DRAFT_TEMPLATES_VERSION,
    REVIEW_DRAFT_VOCABULARY,
    assert_in_catalogue,
)
from app.tenants.domain.value_objects import SUPPORTED_LANGUAGES

#: Sorted so the parametrize ids are stable across xdist workers — `steering/testing.md`
#: forbids driving cases off a `set`/`frozenset`, whose iteration order varies per process.
CATALOGUE_TEMPLATES = sorted(
    REVIEW_DRAFT_TEMPLATES.values(),
    key=lambda template: template[:20],
)
CATALOGUE_IDS = sorted(
    [f"{sentiment.value}:{language}" for (sentiment, language) in REVIEW_DRAFT_TEMPLATES]
)


def test_the_catalogue_covers_three_sentiments_in_both_languages() -> None:
    """R3.2 / D12: three sentiments × two languages, no more."""
    covered = {sentiment for sentiment, _ in REVIEW_DRAFT_TEMPLATES}
    assert covered == {ReviewSentiment.POSITIVE, ReviewSentiment.NEUTRAL, ReviewSentiment.NEGATIVE}
    assert set(REVIEW_DRAFT_TEMPLATES) == {
        (sentiment, language)
        for sentiment in covered
        for language in SUPPORTED_LANGUAGES
    }


@pytest.mark.parametrize("template", CATALOGUE_TEMPLATES, ids=CATALOGUE_IDS)
def test_no_template_has_an_interpolation_hole(template: str) -> None:
    """A constant with `{}`, `%s` or `$` is not a closed vocabulary.

    Cheap to write, and it closes the obvious way to satisfy the letter of R3.2 while
    still emitting whatever the reviewer typed.
    """
    assert "{" not in template and "}" not in template
    assert "%s" not in template and "%(" not in template
    assert "$" not in template


@pytest.mark.parametrize("template", CATALOGUE_TEMPLATES, ids=CATALOGUE_IDS)
def test_every_template_is_a_non_empty_constant(template: str) -> None:
    assert isinstance(template, str)
    assert template.strip() == template
    assert len(template) > 20


def test_the_vocabulary_is_exactly_the_catalogue() -> None:
    """`REVIEW_DRAFT_VOCABULARY` is what an adapter declares in the value it returns; the
    pipeline compares against it. A drift here means the catalogue can produce a string
    the vocabulary refuses, or vice versa."""
    assert REVIEW_DRAFT_VOCABULARY == frozenset(REVIEW_DRAFT_TEMPLATES.values())
    assert len(REVIEW_DRAFT_VOCABULARY) == len(REVIEW_DRAFT_TEMPLATES)


def test_assert_in_catalogue_accepts_a_member() -> None:
    sample = next(iter(REVIEW_DRAFT_VOCABULARY))
    assert_in_catalogue(sample)  # does not raise


def test_assert_in_catalogue_rejects_a_non_member() -> None:
    with pytest.raises(ReviewValidationError, match="catalogue"):
        assert_in_catalogue("Not a catalogue entry")


def test_the_catalogue_declares_its_version() -> None:
    """Carried into the structured log line on each generated draft (D13)."""
    assert REVIEW_DRAFT_TEMPLATES_VERSION == "2026-09-01.1"


#: Rule 10 of `steering/security.md` has seven clauses, and there is a phrase group for each
#: — exactly the eight groups `tests/messaging/test_templates.py` carries, minus the two
#: that don't apply to a review response ("revealing another guest's data" is guest-facing
#: only, and "claiming a technician is on the way" is incident language). Calqued on
#: `messaging` rather than re-derived, because the same words would break the same rule.
RULE_10_FORBIDDEN: dict[str, tuple[str, ...]] = {
    "promising a refund or compensation": (
        "reembols", "refund", "compensa", "devolvemos", "money back", "indemniza",
    ),
    "admitting responsibility": (
        "culpa nuestra", "our fault", "responsabilidad nuestra", "we are responsible",
        "lo sentimos", "we apologise", "we apologize", "pedimos disculpas",
    ),
    "giving legal advice": (
        "abogado", "lawyer", "legalmente", "legally", "la ley", "the law",
        "sus derechos", "your rights", "denuncia", "demandar", "sue us", "sue you",
    ),
    "inventing a code": (
        "codigo de acceso", "access code", "contrasena del wifi", "wifi password",
        "la clave es", "the code is",
    ),
    "inventing availability": (
        "esta disponible", "hay disponibilidad", "we have availability",
        "is available", "tenemos sitio", "podemos ofrecerle",
    ),
    "inventing a price": (
        "euros", "eur ", " gratis", "free of charge", "sin coste", "no extra cost",
    ),
}


@pytest.mark.parametrize("clause", sorted(RULE_10_FORBIDDEN))
def test_no_draft_can_promise_what_rule_10_forbids(clause: str) -> None:
    """The same net the messaging catalogue carries.

    **Net, not the guarantee.** The closed catalogue makes it impossible for the
    *reviewer's* words to reach the response; it cannot make it impossible for a person
    to type a sentence that breaks rule 10 into a constant. What this catches is the
    wording a well-meaning edit would reach for.
    """
    for template in REVIEW_DRAFT_VOCABULARY:
        lowered = f" {template.lower()} "
        for phrase in RULE_10_FORBIDDEN[clause]:
            assert phrase not in lowered, (
                f"template risks {clause} (rule 10 of steering/security.md): {template!r}"
            )


def test_the_rule_10_list_covers_every_clause_that_applies() -> None:
    """Six groups: the four universal ones (refund, responsibility, legal, price), plus
    code and availability. The two messaging clauses that don't apply (other guests'
    data, technician claim) are deliberately absent."""
    assert len(RULE_10_FORBIDDEN) == 6
    assert all(phrases for phrases in RULE_10_FORBIDDEN.values())
