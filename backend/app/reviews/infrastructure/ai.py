"""The development adapter of `AIReviewAnalyzer` and `AIReviewDraftGenerator` (R2.5, R3.2;
design D1, D7).

Deterministic and offline: the same body always yields the same verdict, which is
what makes the tests assertions rather than approximations and what makes the
classification job of D2/D16 stop retrying a review it has already looked at.

**It lives here and not in `app/integrations/`** because it talks to no external
system and is shared with nobody; `steering/backend.md` reserves that package for
*"adapters externos compartidos"*. A real provider implements the same ports and
goes there — and the contracts still hold for it, because they live in the return
types (`ReviewAnalysis`, `GeneratedDraft`) rather than in this file.

**The summary and the content are never echoes of the reviewer's body** (D7, R2.1,
R3.3). Every value this file returns is a constant of `templates.REVIEW_DRAFT_TEMPLATES`,
and `templates.assert_in_catalogue` is the second net the pipeline calls before
persisting. The vocabulary of `recurring_issues` is the closed enum of
`RecurringIssueTag`; an invented tag degrades to `OTHER` with a warning, the same
discipline `Review._coerce_recurring_issues` applies at the entity.
"""

from decimal import Decimal

from app.reviews.domain.entities import Review
from app.reviews.domain.enums import (
    RecurringIssueTag,
    ReviewSentiment,
)
from app.reviews.domain.language import fold
from app.reviews.domain.templates import (
    REVIEW_DRAFT_TEMPLATES,
    REVIEW_DRAFT_TEMPLATES_VERSION,
    REVIEW_DRAFT_VOCABULARY,
)
from app.reviews.domain.value_objects import GeneratedDraft, ReviewAnalysis

ADAPTER_NAME = "MockReviewAnalyzer"

#: A small closed vocabulary of summary phrasings the analyser can return. One per
#: sentiment, and the **only** thing that ever reaches `reviews.ai_summary` from this
#: adapter. Adding a sentiment to the enum without adding a line here fails in
#: `_summary_for`, loudly, rather than falling back to something derived from the
#: reviewer's words.
_SUMMARIES: dict[ReviewSentiment, str] = {
    ReviewSentiment.POSITIVE: "Positive review reported at the property",
    ReviewSentiment.NEUTRAL: "Mixed review reported at the property",
    ReviewSentiment.NEGATIVE: "Negative review reported at the property",
}

#: The closed vocabulary of `ReviewAnalysis.summary`, exposed as a module constant so
#: the test `test_classifier_vocabulary_contract` can sweep the package. The
#: distinction cost a review round: a sweep rooted at one directory cannot see an
#: adapter in `app/integrations/`, which is exactly where a real provider goes.
ANALYSIS_SUMMARY_VOCABULARY: frozenset[str] = frozenset(_SUMMARIES.values())

#: Keywords per sentiment, in the two languages the product serves. A tuple of pairs
#: and not a dict literal because **the order is the tie-break**: a body matching two
#: sentiments equally well is resolved by this order.
#:
#: Ordered most specific first. `NEGATIVE` leads because a body mentioning both a
#: broken boiler and a kind host is a NEGATIVE review that happens to mention a kind
#: host — and the manager triages by the worse signal, not by averaging.
_KEYWORDS: tuple[tuple[ReviewSentiment, tuple[str, ...]], ...] = (
    (
        ReviewSentiment.NEGATIVE,
        (
            "ruido", "sucio", "sucia", "roto", "rota", "averia", "horrible", "feo",
            "feo", "feo",
            "noisy", "dirty", "broken", "horrible", "ugly", "bad", "terrible",
            "awful", "disappointing", "rude", "cold", "smelly",
        ),
    ),
    (
        ReviewSentiment.POSITIVE,
        (
            "maravilloso", "perfecto", "increible", "genial", "amable", "limpio",
            "wonderful", "perfect", "amazing", "great", "lovely", "clean",
            "kind", "beautiful", "fantastic", "comfortable",
        ),
    ),
)

#: Confidence is calibrated against `TenantConfig.ai_confidence_threshold`'s default
#: of `0.75`. Two matched keywords is a body that says the same thing twice; one is
#: a plausible guess; none is **below** the threshold on purpose: a body this adapter
#: does not recognise stays `NEW` for a human to triage (R2.3), rather than being
#: filed as `NEUTRAL` with an air of certainty. The same calibration
#: `RuleBasedIncidentClassifier` documents.
_STRONG_CONFIDENCE = Decimal("0.95")
_WEAK_CONFIDENCE = Decimal("0.80")
_UNMATCHED_CONFIDENCE = Decimal("0.30")


def _summary_for(sentiment: ReviewSentiment) -> str:
    summary = _SUMMARIES.get(sentiment)
    if summary is None:
        raise KeyError(f"No closed summary is declared for sentiment {sentiment!r}")
    return summary


def _classify_sentiment(content: str) -> tuple[ReviewSentiment, int]:
    """The sentiment verdict and how many keywords matched.

    Returns the keyword count alongside the verdict because the adapter's confidence
    depends on it — two matches is a body that says the same thing twice, one is a
    guess, none is below the threshold on purpose.
    """
    words = set(fold(content).split())
    best = ReviewSentiment.NEUTRAL
    best_hits = 0
    for sentiment, keywords in _KEYWORDS:
        hits = sum(1 for keyword in keywords if keyword in words)
        if hits > best_hits:
            best, best_hits = sentiment, hits
    return best, best_hits


class MockReviewAnalyzer:
    """`AIReviewAnalyzer`, by keyword. No state, no I/O, no randomness."""

    async def analyze_review(
        self, *, content: str, language: str | None
    ) -> ReviewAnalysis:
        # `language` is accepted for the port's symmetry with the draft generator and
        # the future multi-lingual analyser, but the mock's keyword table is
        # language-agnostic (the same words, folded the same way). Recorded so the
        # signature matches `AIReviewAnalyzer` and a real provider can swap in.
        _ = language
        sentiment, hits = _classify_sentiment(content)
        if hits == 0:
            confidence = _UNMATCHED_CONFIDENCE
        elif hits == 1:
            confidence = _WEAK_CONFIDENCE
        else:
            confidence = _STRONG_CONFIDENCE
        return ReviewAnalysis(
            sentiment=sentiment,
            summary=_summary_for(sentiment),
            # The mock emits an empty `recurring_issues` list: it does not invent tags
            # because inventing is the failure mode the entity guard exists to catch.
            recurring_issues=(),
            confidence=confidence,
            summary_vocabulary=ANALYSIS_SUMMARY_VOCABULARY,
            issues_vocabulary=frozenset(RecurringIssueTag),
        )


class MockReviewDraftGenerator:
    """`AIReviewDraftGenerator`, by closed catalogue. No state, no I/O, no randomness.

    The catalogue is `REVIEW_DRAFT_TEMPLATES`; the vocabulary the value object checks
    against is `REVIEW_DRAFT_VOCABULARY`. Substitutable with a real provider by
    contract (`steering/backend-architecture.md`, Liskov).
    """

    async def generate_draft(
        self, *, review: Review, language: str
    ) -> GeneratedDraft:
        """The template for the review's sentiment and the requested language.

        **A `KeyError` for an unsupported language** is the intended behaviour, not an
        oversight: the caller (`CreateReviewUseCase`, `ClassifyPendingReviewsUseCase`)
        resolves the language through `detect_or_raise`, and a `KeyError` for a body
        that did not say ES or EN would have been a 422 before this method ever ran.
        The catalogue has no entry for `IGNORED` or `POSTED_MANUALLY` because the use
        case never asks for one (D12), so a caller that steps over the policy gets a
        loud `KeyError` rather than a draft the manager never approved.

        `language` is the resolved language of the review, supplied by the caller — the
        port never has to know about detection (D1).
        """
        _ = language  # accepted by the port; the catalogue entry is keyed by it.
        sentiment = review.sentiment or ReviewSentiment.NEUTRAL
        content = REVIEW_DRAFT_TEMPLATES[(sentiment, language)]
        return GeneratedDraft(
            content=content,
            language=language,
            confidence=Decimal("0.85"),
            template_version=REVIEW_DRAFT_TEMPLATES_VERSION,
            vocabulary=REVIEW_DRAFT_VOCABULARY,
        )


#: The catalogue version this adapter answers from, persisted into the structured log
#: line on each generated draft (D13). Not stored in `review_response_drafts` itself —
#: PRD §7.21 declares no `metadata` column.
CATALOGUE_VERSION = REVIEW_DRAFT_TEMPLATES_VERSION
