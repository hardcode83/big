"""The contracts `ReviewAnalysis` and `GeneratedDraft` carry (R2.1, R3.3; design D7).

Both classes refuse their closed invariants at construction; the tests below pin those
refusals so a second adapter that returns a bad value raises instead of reaching the
column. Rule 11 of `sdd/steering/security.md` declares the admission condition for these
two value objects, and the type checks are the structural half of that admission.
"""

from decimal import Decimal

import pytest

from app.reviews.domain.enums import RecurringIssueTag, ReviewSentiment
from app.reviews.domain.exceptions import (
    DraftLanguageUnsupportedError,
    ReviewValidationError,
)
from app.reviews.domain.templates import REVIEW_DRAFT_VOCABULARY
from app.reviews.domain.value_objects import GeneratedDraft, ReviewAnalysis


#: A tiny but non-empty vocabulary so the test exercises the closed-form check.
SUMMARY_VOCABULARY = frozenset({"Great stay", "Needs improvement", "Mixed"})


def _analysis(**overrides):
    base = dict(
        sentiment=ReviewSentiment.POSITIVE,
        summary="Great stay",
        recurring_issues=(RecurringIssueTag.WIFI,),
        confidence=Decimal("0.85"),
        summary_vocabulary=SUMMARY_VOCABULARY,
        issues_vocabulary=frozenset(RecurringIssueTag),
    )
    base.update(overrides)
    return ReviewAnalysis(**base)


def test_review_analysis_accepts_a_well_formed_value() -> None:
    analysis = _analysis()
    assert analysis.sentiment is ReviewSentiment.POSITIVE
    assert analysis.confidence == Decimal("0.85")


def test_review_analysis_rejects_a_non_enum_sentiment() -> None:
    with pytest.raises(ReviewValidationError, match="sentiment"):
        _analysis(sentiment="POSITIVE")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [Decimal("-0.1"), Decimal("1.5"), Decimal("2")])
def test_review_analysis_rejects_confidence_outside_zero_to_one(bad: Decimal) -> None:
    with pytest.raises(ReviewValidationError, match="confidence"):
        _analysis(confidence=bad)


def test_review_analysis_rejects_an_empty_vocabulary() -> None:
    with pytest.raises(ReviewValidationError, match="vocabulary"):
        _analysis(summary_vocabulary=frozenset())


def test_review_analysis_rejects_a_summary_outside_its_vocabulary() -> None:
    with pytest.raises(ReviewValidationError, match="vocabulary"):
        _analysis(summary="Not in catalogue")


def test_review_analysis_rejects_a_recurring_issue_outside_its_vocabulary() -> None:
    """An adapter that invents a tag is refused by the type; the entity then degrades
    it to `OTHER` with a warning. The two halves together are the rule-11 guarantee."""
    with pytest.raises(ReviewValidationError, match="recurring_issues"):
        _analysis(
            recurring_issues=(RecurringIssueTag.WIFI,),
            issues_vocabulary=frozenset({RecurringIssueTag.NOISE}),
        )


def test_review_analysis_allows_summary_to_be_none() -> None:
    """A review may be classified without a summary if the analyser declines to
    summarise — `ai_summary` is then `NULL` until a future run fills it."""
    analysis = _analysis(summary=None)
    assert analysis.summary is None


def test_generated_draft_accepts_a_well_formed_value() -> None:
    draft = GeneratedDraft(
        content=next(iter(REVIEW_DRAFT_VOCABULARY)),
        language="es",
        confidence=Decimal("0.90"),
        template_version="2026-09-01.1",
        vocabulary=REVIEW_DRAFT_VOCABULARY,
    )
    assert draft.content in REVIEW_DRAFT_VOCABULARY


def test_generated_draft_rejects_an_unsupported_language() -> None:
    with pytest.raises(DraftLanguageUnsupportedError, match="language"):
        GeneratedDraft(
            content="x",
            language="fr",
            confidence=Decimal("0.90"),
            template_version="2026-09-01.1",
            vocabulary=frozenset({"x"}),
        )


@pytest.mark.parametrize("bad", [Decimal("-0.1"), Decimal("1.1"), Decimal("2")])
def test_generated_draft_rejects_confidence_outside_zero_to_one(bad: Decimal) -> None:
    with pytest.raises(ReviewValidationError, match="confidence"):
        GeneratedDraft(
            content="x",
            language="es",
            confidence=bad,
            template_version="2026-09-01.1",
            vocabulary=frozenset({"x"}),
        )


def test_generated_draft_rejects_an_empty_vocabulary() -> None:
    with pytest.raises(ReviewValidationError, match="vocabulary"):
        GeneratedDraft(
            content="x",
            language="es",
            confidence=Decimal("0.90"),
            template_version="2026-09-01.1",
            vocabulary=frozenset(),
        )


def test_generated_draft_rejects_content_outside_its_vocabulary() -> None:
    with pytest.raises(ReviewValidationError, match="vocabulary"):
        GeneratedDraft(
            content="Not in catalogue",
            language="es",
            confidence=Decimal("0.90"),
            template_version="2026-09-01.1",
            vocabulary=REVIEW_DRAFT_VOCABULARY,
        )


@pytest.mark.parametrize(
    "bad_version",
    ["2026-9-1.1", "2026-09-01", "2026/09/01.1", "today", ""],
)
def test_generated_draft_rejects_malformed_template_version(bad_version: str) -> None:
    with pytest.raises(ReviewValidationError, match="template_version"):
        GeneratedDraft(
            content="x",
            language="es",
            confidence=Decimal("0.90"),
            template_version=bad_version,
            vocabulary=frozenset({"x"}),
        )
