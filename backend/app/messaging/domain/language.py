"""Which of the two supported languages a message is written in (R4.8, design D9).

Pure domain, no dependency: `re` and `unicodedata` are standard library, so the purity
`tests/test_layering.py` enforces holds.

**Why not `langdetect`/`fasttext`.** A new dependency to tell two languages apart, whose
result depends on a seed — which breaks `steering/testing.md` ("nada aleatorio en la
suite") — and which is *worse* on one-line messages, which is what 90 % of this traffic
looks like. Markers over a closed list are worse in general and better here.

**Why `normalise_words` is a copy and not an import.** `app/maintenance/infrastructure/
classifier.py` has the same six lines. Importing them would be a `domain/` module of this
domain importing the `infrastructure/` of another, which `tests/test_layering.py` rejects —
and rightly, since a classifier's normalisation is free to change for reasons that have
nothing to do with language detection. So it is copied, and this paragraph is why.

The damage a wrong verdict can do is bounded by construction: the reply comes from the
closed catalogue of `templates.py`, so the worst outcome is answering in English someone who
wrote in Spanish — irritating, never dangerous — and `Conversation.language` is the declared
fallback (R4.8).
"""

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9]+")

#: Characters that exist in Spanish and not in English. Counted on the **raw** text, before
#: `normalise_words` folds the accents away — folding first would destroy exactly the signal
#: they carry. `¿` and `¡` are the strongest of them: no English text contains one.
_SPANISH_CHARACTERS = frozenset("ñáéíóúü¿¡")

#: Function words, chosen for being frequent and *unambiguous between these two languages*.
#: Deliberate omissions: `a` (both), `no` (both), `me` (both), `son`/`son`-alikes. A marker
#: that scores for both sides is not a marker, it is noise that moves the tie-break around.
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


def fold(text: str) -> str:
    """Lowercase and strip accents, **keeping the order of the words**.

    Accents go because a guest writing "climatización" and one writing "climatizacion" mean
    the same thing. Copied from `maintenance`'s classifier — see the module docstring for why
    it is a copy — and split in two here because two callers want different halves of it:
    `normalise_words` wants a bag for single-term matching, and `MockAIAdapter` wants the
    sequence, because a keyword like "no puedo entrar" only exists in order.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(_WORD.findall(stripped))


def normalise_words(text: str) -> set[str]:
    """The folded text as a set of whole words.

    Whole words because a substring match would see "gas" inside "gasolinera" — the failure
    `maintenance`'s classifier documents and the reason this is a set rather than a string.
    """
    return set(fold(text).split())


def detect_language(content: str) -> str | None:
    """`"es"`, `"en"`, or `None` when the text does not say.

    `None` is a real answer and not a failure: R4.8 makes `Conversation.language` the
    fallback, and returning a guess on no evidence would take that decision away from the
    one place that is entitled to make it. A tie counts as no evidence for the same reason.
    """
    words = normalise_words(content)
    spanish = len(words & _SPANISH_WORDS) + sum(
        1 for char in _SPANISH_CHARACTERS if char in content.lower()
    )
    english = len(words & _ENGLISH_WORDS)

    if spanish > english:
        return "es"
    if english > spanish:
        return "en"
    return None
