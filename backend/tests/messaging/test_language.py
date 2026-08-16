"""Language detection, and the honest `None` (R4.8, design D9).

One-line messages, because that is what this traffic looks like and what D9 rejected
`langdetect` for being bad at.
"""

import pytest

from app.messaging.domain.language import detect_language, normalise_words


@pytest.mark.parametrize(
    "content",
    [
        "Hola, ¿a qué hora es el check-in?",
        "Buenos días, no encuentro el código de la puerta",
        "Necesito ayuda con la calefacción por favor",
        "El wifi no funciona en la habitación",
    ],
)
def test_spanish_messages_are_detected_as_spanish(content: str) -> None:
    assert detect_language(content) == "es"


@pytest.mark.parametrize(
    "content",
    [
        "Hi, what time is check-in?",
        "Hello, I cannot find the door code",
        "I need help with the heating please",
        "The wifi is not working in the room",
    ],
)
def test_english_messages_are_detected_as_english(content: str) -> None:
    assert detect_language(content) == "en"


@pytest.mark.parametrize("content", ["", "wifi", "ok", "12345", "checkout", "??"])
def test_a_message_with_no_signal_returns_none(content: str) -> None:
    """R4.8's "IF no puede decidirlo": `None` is a real answer, not a failure. Guessing here
    would take the fallback decision away from `Conversation.language`, which is the one
    place entitled to make it."""
    assert detect_language(content) is None


def test_a_message_with_equal_evidence_returns_none() -> None:
    """A tie is no evidence, for the same reason as above."""
    assert detect_language("the problema") is None


def test_a_spanish_only_character_is_enough_on_its_own() -> None:
    """`¿` and `¡` appear in no English text, so they are the strongest markers there are —
    and they are counted on the raw string, before accent folding would destroy them."""
    assert detect_language("¿?") == "es"
    assert detect_language("mañana") == "es"


def test_accents_do_not_change_the_verdict() -> None:
    """A guest writing "habitación" and one writing "habitacion" mean the same thing."""
    assert detect_language("la habitación está sucia") == detect_language(
        "la habitacion esta sucia"
    )


def test_normalisation_splits_whole_words_and_folds_accents() -> None:
    """The half that matters for `escalation.contains_emergency_keyword`: whole words, so
    "gasolinera" is not a gas leak."""
    assert normalise_words("Hay GAS en la cocina") == {"hay", "gas", "en", "la", "cocina"}
    assert "gas" not in normalise_words("Voy a la gasolinera")
    assert normalise_words("intoxicación") == {"intoxicacion"}
