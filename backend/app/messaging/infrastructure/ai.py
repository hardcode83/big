"""The development adapter of `AIAdapter` (R2.5, R2.8; design D8).

Deterministic and offline: the same text always yields the same verdict, which is what makes
the tests of this module assertions rather than approximations — and `steering/testing.md`
forbids anything random in a suite that runs in parallel.

**It lives here and not in `app/integrations/`** because it talks to no external system and is
shared with nobody; `steering/backend.md` reserves that package for *"adapters externos
compartidos"*. A real provider implements this same port and goes there — and the contracts
still hold for it, because they live in the return types (`MessageClassification`,
`GeneratedResponse`) rather than in this file.

`EXTERNAL_DEPENDENCY` (R2.8): the real adapter against a model provider is out of scope for
this change. This mock is the only implementer it ships.

**The reply never quotes the input.** Every `content` this adapter returns is a constant of
`RESPONSE_TEMPLATES`, so there is no path from the guest's words to `messages.content` when
the writer is ours (R3.3, D7).
"""

from decimal import Decimal

from app.messaging.domain.enums import MessageIntent
from app.messaging.domain.language import fold
from app.messaging.domain.templates import (
    RESPONSE_TEMPLATES,
    RESPONSE_VOCABULARY,
    TEMPLATE_CATALOGUE_VERSION,
    template_key,
)
from app.messaging.domain.value_objects import (
    ConversationContext,
    GeneratedResponse,
    MessageClassification,
)

ADAPTER_NAME = "MockAIAdapter"

#: Keywords per intent, in the two languages the product serves. A tuple of pairs and not a
#: dict literal because **the order is the tie-break**: a message matching two intents equally
#: well is resolved by this order, and a `dict` would hide that behind insertion semantics
#: nobody reading would think to check. Same device as `RuleBasedIncidentClassifier._KEYWORDS`.
#:
#: Ordered most specific first, and the first three are ordered by consequence rather than by
#: vocabulary: a message mentioning both a refund and the wifi is a refund conversation that
#: happens to mention the wifi, and all three of these escalate rather than being answered.
_KEYWORDS: tuple[tuple[MessageIntent, tuple[str, ...]], ...] = (
    (
        MessageIntent.EMERGENCY,
        ("emergencia", "urgencia", "fuego", "humo", "ambulancia", "emergency", "urgent", "fire", "smoke"),
    ),
    (
        MessageIntent.REFUND_OR_COMPENSATION,
        ("reembolso", "devolucion", "compensacion", "indemnizacion", "refund", "compensation", "money back"),
    ),
    (
        MessageIntent.ACCESS_PROBLEM,
        ("no puedo entrar", "cerradura", "llave", "portal", "cannot get in", "locked out", "lock", "key"),
    ),
    # Nouns and states, **never a bare verb phrase**. "no funciona" / "not working" were here
    # in the first version and classified "el wifi no funciona" as a maintenance issue,
    # because a generic verb phrase describes whatever noun precedes it and this intent sits
    # above `WIFI` on the tie-break. It is the same lesson `RuleBasedIncidentClassifier`
    # records for `keypad`: a keyword that matches everything decides nothing.
    (
        MessageIntent.MAINTENANCE_ISSUE,
        ("averia", "roto", "rota", "gotea", "fuga", "caldera", "grifo", "persiana",
         "broken", "leak", "boiler", "tap", "blind"),
    ),
    (
        MessageIntent.CLEANING_ISSUE,
        ("sucio", "sucia", "limpieza", "basura", "dirty", "cleaning", "rubbish", "stain"),
    ),
    (
        MessageIntent.NOISE,
        ("ruido", "vecinos", "fiesta", "noise", "neighbours", "party", "loud"),
    ),
    (
        MessageIntent.WIFI,
        ("wifi", "internet", "router", "conexion", "connection", "password"),
    ),
    (
        MessageIntent.PARKING,
        ("aparcamiento", "parking", "garaje", "coche", "garage", "car"),
    ),
    # **No hyphens anywhere in this table.** `fold` splits on `[a-z0-9]+`, so "check-in"
    # becomes the two tokens "check in" and a hyphenated keyword can never match — not through
    # the word set and not through the phrase substring, because the folded text contains no
    # hyphen. Three entries were written that way and were dead: "What time is check-in?" —
    # the single most likely message this system will ever receive — classified as `UNKNOWN`.
    # Found by the QA panel of sections 5-6, and it is the third instance of the class of bug
    # `RuleBasedIncidentClassifier` names for `keypad`. Both spellings are listed, because a
    # guest writes either.
    (
        MessageIntent.EARLY_CHECKIN,
        ("entrada anticipada", "antes de las", "early check in", "early checkin", "earlier"),
    ),
    (
        MessageIntent.LATE_CHECKOUT,
        ("salida tardia", "mas tarde", "late check out", "late checkout", "later checkout"),
    ),
    # After the two above, so "early check in" is not swallowed by "check in".
    (
        MessageIntent.CHECKIN_INSTRUCTIONS,
        ("instrucciones", "como entro", "llegada", "check in", "checkin", "arrival", "instructions"),
    ),
    (
        MessageIntent.REVIEW_REQUEST,
        ("valoracion", "resena", "opinion", "review", "rating", "stars"),
    ),
    (
        MessageIntent.GENERAL_FAQ,
        ("pregunta", "duda", "consulta", "question", "info", "information"),
    ),
)

#: PRD §13 names this number literally for a recognised intent.
_RECOGNISED_CONFIDENCE = Decimal("0.80")

#: And this one is **below** `TenantConfig.ai_confidence_threshold`'s default of `0.75` on
#: purpose (R2.5): a message this adapter does not recognise takes the escalation path, so
#: that path is exercised by the mock itself and not only by a test that fabricates a low
#: confidence by hand.
_UNRECOGNISED_CONFIDENCE = Decimal("0.30")


def _matches(keyword: str, content: str, words: set[str]) -> bool:
    """Whole words for a single term, substring for a declared phrase.

    A multi-word keyword like "no puedo entrar" cannot be matched against the word set, and
    matching it as a substring is safe precisely because it is a phrase — the failure mode the
    word-set rule exists to prevent ("gas" inside "gasolinera") needs a short single token.
    """
    if " " in keyword:
        return keyword in content
    return keyword in words


class MockAIAdapter:
    """`AIAdapter`, by keyword. No state, no I/O, no randomness.

    Substitutable with a real provider by contract (`steering/backend-architecture.md`,
    Liskov): same return types, same precondition — and, importantly, the same obligation to
    declare its vocabulary, because `GeneratedResponse` refuses a `content` outside the set
    the adapter declares.
    """

    async def classify_message(
        self, *, content: str, language: str, context: ConversationContext
    ) -> MessageClassification:
        folded = fold(content)
        words = set(folded.split())

        for intent, keywords in _KEYWORDS:
            if any(_matches(keyword, folded, words) for keyword in keywords):
                return MessageClassification(
                    intent=intent, confidence=_RECOGNISED_CONFIDENCE
                )

        return MessageClassification(
            intent=MessageIntent.UNKNOWN, confidence=_UNRECOGNISED_CONFIDENCE
        )

    async def generate_response(
        self, *, intent: MessageIntent, language: str, context: ConversationContext
    ) -> GeneratedResponse:
        """The template for that intent and language.

        **A `KeyError` for the three intents R2.7 forbids answering** is the intended
        behaviour, not an oversight: the catalogue has no entry for
        `REFUND_OR_COMPENSATION`, `EMERGENCY` or `UNKNOWN`, so a caller that steps over the
        pipeline's branch fails loudly instead of sending a guest a sentence they should never
        have received (D7).
        """
        content = RESPONSE_TEMPLATES[(intent, language)]
        return GeneratedResponse(
            content=content,
            language=language,
            template_key=template_key(intent, language),
            vocabulary=RESPONSE_VOCABULARY,
        )


#: The catalogue version this adapter answers from, persisted into
#: `messages.metadata["template_version"]` by the pipeline (D15).
CATALOGUE_VERSION = TEMPLATE_CATALOGUE_VERSION
