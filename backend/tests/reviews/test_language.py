"""`detect` of `app.reviews.domain.language` (R5.1, design D14).

Mirrors `tests/messaging/test_language.py` and for the same reason: the detector and its
heuristic are the contract, not a description of it, so a corpus of representative
bodies pins the verdict each one returns.

The detector returns `None` on no evidence (R5.1, A2): the manager triages a body that
did not say ES or EN, and the create endpoint answers `422` rather than guessing.
"""

import pytest

from app.reviews.domain.language import detect, detect_or_raise, fold
from app.reviews.domain.exceptions import ReviewLanguageInferenceError


@pytest.mark.parametrize(
    "content",
    [
        "La casa estaba muy limpia, gracias por todo.",
        "Necesito ayuda con el wifi por favor.",
        "El check-in fue muy sencillo y la anfitriona muy amable.",
        "La habitacion era ruidosa por la noche.",
    ],
)
def test_spanish_bodies_return_es(content: str) -> None:
    assert detect(content) == "es"


@pytest.mark.parametrize(
    "content",
    [
        "The flat was very clean, thank you for everything.",
        "I need help with the wifi please.",
        "Check-in was easy and the host was very kind.",
        "The room was noisy at night.",
    ],
)
def test_english_bodies_return_en(content: str) -> None:
    assert detect(content) == "en"


@pytest.mark.parametrize("content", ["", "wifi", "ok", "12345", "checkout", "??", None])
def test_bodies_with_no_signal_return_none(content: str | None) -> None:
    """A body the detector cannot decide is left for human triage (R5.1, A2)."""
    assert detect(content) is None


def test_a_tie_returns_none() -> None:
    """A body like 'the problema' carries one marker from each side: it is no evidence."""
    assert detect("the problema") is None


def test_spanish_only_characters_are_strong_markers() -> None:
    """`¿` and `¡` appear in no English text, so they are the strongest signals — counted
    on the raw string, before accent folding would destroy them (D14)."""
    assert detect("¿?") == "es"
    assert detect("mañana") == "es"


def test_accents_do_not_change_the_verdict() -> None:
    """A reviewer writing 'habitación' and one writing 'habitacion' mean the same thing."""
    assert detect("la habitación está sucia") == detect(
        "la habitacion esta sucia"
    )


def test_detect_or_raise_wraps_none_in_a_domain_error() -> None:
    with pytest.raises(ReviewLanguageInferenceError):
        detect_or_raise("???")
    assert detect_or_raise("Hola, gracias por todo.") == "es"


def test_fold_lowercases_strips_accents_and_splits_on_word_boundaries() -> None:
    """The half the detector matches against: whole words, accents removed, lowercased."""
    assert fold("Hay HABITACIÓN grande.") == "hay habitacion grande"
