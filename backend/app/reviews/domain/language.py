"""Which of the two supported languages a review is written in (R5.1, design D14).

Pure domain, no dependency: `re` and `unicodedata` are standard library, so the purity
`tests/test_layering.py` enforces holds.

**Same shape as `app/messaging/domain/language.py`, and the overlap is deliberate, not a
candidate to fold.** Detecting ES vs EN off a short review body is the same problem the
guest-message detector solves, and the test corpus and the answer are the same. Importing
the messaging detector would be a `reviews/domain/` depending on a `messaging/domain/` of a
sibling module, which `tests/test_layering.py` would reject; and the normalisation step
that detector uses to count stop-words is free to drift for reasons the two modules do
not share. The duplication is the discipline; this paragraph is the reason.

**Returns `"es"` / `"en"` / `None`**, where `None` means "no verdict": a review body
without recognisable words leaves `language` for human triage (A2). The caller decides
whether `None` is a `422` (our `CreateReviewUseCase` does) or a fallback to a tenant
default; the heuristic never invents.
"""

import re
import unicodedata

from app.reviews.domain.exceptions import ReviewLanguageInferenceError

_WORD = re.compile(r"[a-z0-9]+")

#: Spanish letters absent in English. Counted on the **raw** text, before the accent fold —
#: folding first would destroy the signal they carry. `¿` and `¡` are the strongest of them:
#: no English text contains one.
_SPANISH_CHARACTERS = frozenset("ñáéíóúü¿¡")

#: Function words, chosen for being frequent and *unambiguous between these two languages*.
#: A marker that scores for both sides is not a marker, it is noise that moves the
#: tie-break around. The list mirrors the one `messaging` ships — same reasoning.
_SPANISH_WORDS = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "de", "del", "que", "por", "para", "con", "sin", "sobre",
        "es", "esta", "este", "esto", "estoy", "estamos", "son", "hay",
        "mi", "mis", "su", "sus", "nuestro", "nuestra",
        "hola", "gracias", "buenos", "buenas", "dias", "tardes", "noches",
        "puedo", "puede", "necesito", "quiero", "tengo", "tiene",
        "donde", "cuando", "como", "porque", "cual", "cuanto",
        "favor", "perdon", "disculpe", "ayuda", "problema", "habitacion",
    }
)
_ENGLISH_WORDS = frozenset(
    {
        "the", "is", "are", "was", "were", "be", "been",
        "of", "to", "in", "on", "at", "for", "with", "from", "about",
        "my", "your", "our", "their", "we", "you", "they",
        "hi", "hello", "thanks", "thank", "please", "sorry",
        "can", "could", "would", "should", "will", "need", "want", "have", "has",
        "where", "when", "how", "why", "which", "there", "this", "that",
        "and", "but", "not", "any", "some", "help", "room", "problem",
    }
)

#: How much the winning language has to beat the other by before the detector returns it
#: (D14). `1.5x` is what the messaging detector uses and what the corpus it was measured
#: against rewarded; the same number here makes the two modules agree on a short review
#: versus a short guest message, which is the same input shape.
_MIN_RATIO = 1.5


def fold(text: str) -> str:
    """Lowercase and strip accents, **keeping the order of the words**.

    Accents go because a guest writing "maravillosa" and one writing "maravillosa" mean
    the same thing, and a review body that mixes both spellings would otherwise miss one
    of the markers.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(_WORD.findall(stripped))


def _spanish_score(content: str, words: set[str]) -> int:
    """Count Spanish markers, character-set first then word-set.

    The character set (`ñ`, `á`, `¿`, `¡`, …) is the strongest signal: `¿` and `¡` appear
    in no English text and stay visible after the accent fold strips everything else.
    Counting them on the raw content (before `fold`) is what makes `detect("¿?")` return
    `"es"` — `fold` strips them because they are not `[a-z0-9]`, and bailing on an empty
    fold would lose them.
    """
    characters = sum(1 for char in _SPANISH_CHARACTERS if char in content.lower())
    return characters + len(words & _SPANISH_WORDS)


def detect(content: str | None) -> str | None:
    """`"es"`, `"en"`, or `None` when the body does not say.

    `None` is a real answer and not a failure: A2 fixes it as the language-detection
    fallback for human triage. A tie or a non-decisive lead (the leading language does not
    beat the other by `_MIN_RATIO`) is treated as `None`, so a body like "great, gracias"
    is not classified by the single shared marker.
    """
    if content is None:
        return None
    folded = fold(content)
    words = set(folded.split()) if folded else set()
    spanish = _spanish_score(content, words)
    english = len(words & _ENGLISH_WORDS)

    if spanish == 0 and english == 0:
        return None
    if spanish >= english * _MIN_RATIO and spanish > 0:
        return "es"
    if english >= spanish * _MIN_RATIO and english > 0:
        return "en"
    return None


def detect_or_raise(content: str | None) -> str:
    """`detect` that wraps `None` in a domain error (R5.1).

    The create endpoint uses this when the manager did not pass an explicit `language`;
    without a verdict the request cannot pick a template and the caller must either try
    again with a body that says ES or EN, or fill `language` themselves.
    """
    verdict = detect(content)
    if verdict is None:
        raise ReviewLanguageInferenceError(
            "language could not be inferred from the review body; pass `language` "
            "explicitly or rewrite the body so it carries unambiguous ES/EN markers"
        )
    return verdict
