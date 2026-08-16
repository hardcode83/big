"""The catalogue is closed, complete and has nowhere to put a sentence (R2.6, R2.7, R3.3).

Calqued on `tests/maintenance/test_classifier_vocabulary_contract.py`, and for the same
reason: rule 10 of `sdd/steering/security.md` forbids the AI from promising a refund,
admitting responsibility, giving legal advice, revealing another guest's data, inventing a
code, a price or availability, or saying a technician is on the way. A catalogue of constants
with no interpolation hole cannot say any of those, and that is a property a test can check —
unlike a promise that nobody will write such a template.
"""

import pytest

from app.messaging.domain.enums import MessageIntent
from app.messaging.domain.language import fold as _fold
from app.messaging.domain.templates import (
    INTENTS_WITHOUT_TEMPLATE,
    RESPONSE_TEMPLATES,
    RESPONSE_VOCABULARY,
    TEMPLATE_CATALOGUE_VERSION,
    template_key,
)
from app.tenants.domain.value_objects import SUPPORTED_LANGUAGES

#: Sorted so the parametrize ids are stable across xdist workers — `steering/testing.md`
#: forbids driving cases off a `set`/`frozenset`, whose iteration order varies per process.
CATALOGUE_ENTRIES = sorted(RESPONSE_TEMPLATES.items(), key=lambda item: (item[0][0].value, item[0][1]))
CATALOGUE_IDS = [f"{intent.value}:{language}" for (intent, language), _ in CATALOGUE_ENTRIES]


def test_the_catalogue_covers_eleven_intents_in_both_languages() -> None:
    """R2.6. Eleven and not fourteen — see the absence test below."""
    covered = {intent for intent, _ in RESPONSE_TEMPLATES}

    assert len(covered) == 11
    assert set(RESPONSE_TEMPLATES) == {
        (intent, language) for intent in covered for language in SUPPORTED_LANGUAGES
    }


def test_the_three_intents_that_must_never_be_answered_have_no_template() -> None:
    """R2.7: "NEVER SHALL invocar `generate_response` para ellos".

    The absence in the catalogue is the **second** net of that prohibition — the first is the
    pipeline's branch — and it is the one that turns a mistake into a loud `KeyError` instead
    of a reply the guest should never have received.
    """
    assert INTENTS_WITHOUT_TEMPLATE == {
        MessageIntent.REFUND_OR_COMPENSATION,
        MessageIntent.EMERGENCY,
        MessageIntent.UNKNOWN,
    }
    for intent in INTENTS_WITHOUT_TEMPLATE:
        for language in SUPPORTED_LANGUAGES:
            assert (intent, language) not in RESPONSE_TEMPLATES


def test_every_intent_is_either_answered_or_declared_unanswerable() -> None:
    """No third case: an intent added to the enum without a decision fails here rather than
    reaching a `KeyError` in production."""
    answered = {intent for intent, _ in RESPONSE_TEMPLATES}

    assert answered | INTENTS_WITHOUT_TEMPLATE == set(MessageIntent)
    assert not answered & INTENTS_WITHOUT_TEMPLATE


@pytest.mark.parametrize(("key", "template"), CATALOGUE_ENTRIES, ids=CATALOGUE_IDS)
def test_no_template_has_an_interpolation_hole(
    key: tuple[MessageIntent, str], template: str
) -> None:
    """A constant with a `{}`, a `%s` or a stray `$` in it is not a closed vocabulary.

    Cheap to write, and it closes the obvious way to satisfy the letter of R2.6 while still
    emitting whatever the guest typed.
    """
    assert "{" not in template and "}" not in template
    assert "%s" not in template and "%(" not in template
    assert "$" not in template


@pytest.mark.parametrize(("key", "template"), CATALOGUE_ENTRIES, ids=CATALOGUE_IDS)
def test_every_template_is_a_non_empty_constant(
    key: tuple[MessageIntent, str], template: str
) -> None:
    assert isinstance(template, str)
    assert template.strip() == template
    assert len(template) > 20


def test_the_vocabulary_is_exactly_the_catalogue() -> None:
    """`RESPONSE_VOCABULARY` is what an adapter declares in the value it returns, so it must
    not drift from what the catalogue can actually produce."""
    assert RESPONSE_VOCABULARY == frozenset(RESPONSE_TEMPLATES.values())
    assert len(RESPONSE_VOCABULARY) == len(RESPONSE_TEMPLATES)


#: Rule 10 of `steering/security.md` has seven clauses, and there is a phrase group for each.
#: Grouped by clause rather than flattened so a missing clause is visible: the first version
#: of this list covered four of the seven, and the security panel of sections 3-4 found the
#: three that were absent — legal advice, other guests' data, and availability.
RULE_10_FORBIDDEN: dict[str, tuple[str, ...]] = {
    "promising a refund or compensation": (
        "reembols", "refund", "compensa", "devolvemos", "money back", "indemniza",
    ),
    "admitting responsibility": (
        "culpa nuestra", "our fault", "responsabilidad nuestra", "we are responsible",
        "lo sentimos", "we apologise", "we apologize", "pedimos disculpas",
    ),
    # No bare `sue`: matching is on substrings, and "issue" contains it — so the first person
    # to write a natural English template ("we have registered your issue") would get a red
    # test accusing them of legal advice. A check people learn to delete is worse than a gap,
    # so it is spelled as the phrases someone would actually write. Found by the security
    # panel of sections 3-4.
    "giving legal advice": (
        "abogado", "lawyer", "legalmente", "legally", "la ley", "the law",
        "sus derechos", "your rights", "denuncia", "demandar", "sue us", "sue you",
    ),
    "revealing another guest's data": (
        "otro huesped", "otros huespedes", "another guest", "other guests",
        "el huesped de", "the guest in",
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
    "claiming a technician is on the way": (
        "tecnico va", "technician is on", "tecnico esta de camino",
        "un tecnico ira", "a technician will come", "enviamos a alguien",
    ),
}


@pytest.mark.parametrize("clause", sorted(RULE_10_FORBIDDEN))
def test_no_template_can_promise_what_rule_10_forbids(clause: str) -> None:
    """Rule 10 of `steering/security.md`, one parametrized case per clause.

    **This is a net, not the guarantee, and the distinction is the point.** The closed
    catalogue makes it impossible for the *guest's* words to reach a reply; it cannot make it
    impossible for a person to type a sentence that breaks rule 10 into a constant. Nothing
    mechanical can. What this catches is the wording a well-meaning edit would reach for —
    "lo sentimos, le devolveremos el importe" — and what guards the rest is review.
    """
    for template in sorted(RESPONSE_VOCABULARY):
        # Padded, because `fold` emits no leading or trailing space: without it a phrase
        # anchored with one (" gratis") could never match at the edges of a template.
        lowered = f" {_fold(template)} "
        for phrase in RULE_10_FORBIDDEN[clause]:
            assert phrase not in lowered, (
                f"template risks {clause} (rule 10 of steering/security.md): {template!r}"
            )


def test_the_rule_10_list_covers_every_clause_of_the_rule() -> None:
    """Eight groups for the seven prohibitions plus the technician one, and a count is
    exactly the assertion that would have caught the first version of this list."""
    assert len(RULE_10_FORBIDDEN) == 8
    assert all(phrases for phrases in RULE_10_FORBIDDEN.values())


def test_the_catalogue_declares_its_version() -> None:
    """Persisted into `messages.metadata["template_version"]` (D15), so an operator reading an
    old row can tell which wording the guest actually got."""
    assert TEMPLATE_CATALOGUE_VERSION == "2026-08-16.1"


@pytest.mark.parametrize("language", list(SUPPORTED_LANGUAGES))
def test_the_template_key_helper_is_the_one_spelling(language: str) -> None:
    assert template_key(MessageIntent.WIFI, language) == f"WIFI:{language}"
