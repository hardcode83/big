"""The invariants of `Review` and `ReviewResponseDraft` (R1.4, R1.5, R4.1; design D4).

Three properties this file enforces:

* `Review.__post_init__` refuses a `None` `property_id`, an out-of-range `rating`, and a
  `rating` with more than one decimal — the entity is the only ceiling the schema does
  not give us (D15 records the deliberate omission of a CHECK on the column).
* The five legal status moves pass and the four illegal ones refuse with
  `InvalidReviewTransitionError` (R4.1, D4). `POSTED_MANUALLY` and `IGNORED` are
  terminal.
* `ReviewResponseDraft.edit()` increments `edits_count`, refuses empty content, and
  refuses any change after `approved_at` is set (R3.5, R3.6). `ai_generated` is
  provenance and never flips to `FALSE`.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.reviews.domain.entities import (
    MAX_REVIEW_CONTENT_LENGTH,
    MAX_REVIEWER_NAME_LENGTH,
    Review,
    ReviewResponseDraft,
)
from app.reviews.domain.enums import (
    RecurringIssueTag,
    ReviewChannel,
    ReviewSentiment,
    ReviewStatus,
)
from app.reviews.domain.exceptions import (
    InvalidReviewTransitionError,
    ReviewValidationError,
)


def _review(**overrides) -> Review:
    """A minimal `Review` whose `__post_init__` passes; kwargs override."""
    now = datetime.now(timezone.utc)
    return Review(
        id=overrides.pop("id", uuid.uuid4()),
        tenant_id=overrides.pop("tenant_id", uuid.uuid4()),
        property_id=overrides.pop("property_id", uuid.uuid4()),
        channel=overrides.pop("channel", ReviewChannel.MANUAL),
        created_at=overrides.pop("created_at", now),
        updated_at=overrides.pop("updated_at", now),
        **overrides,
    )


def test_review_instantiates_with_defaults() -> None:
    review = _review()
    assert review.status is ReviewStatus.NEW
    assert review.reservation_id is None
    assert review.rating is None
    assert review.sentiment is None
    assert review.recurring_issues == ()
    assert review.published_at is None
    assert review.classification_attempts == 0


def test_review_rejects_none_property_id() -> None:
    """R1.5: a review without a property cannot emit any timeline event R6.1 declares
    mandatory, so the entity refuses it on construction."""
    with pytest.raises(ReviewValidationError, match="must belong to a property"):
        _review(property_id=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_rating", [Decimal("5.5"), Decimal("0.5"), Decimal("0.05")])
def test_review_rejects_out_of_range_or_subdecimal_rating(bad_rating: Decimal) -> None:
    with pytest.raises(ReviewValidationError, match="rating"):
        _review(rating=bad_rating)


@pytest.mark.parametrize(
    "good_rating",
    [Decimal("1.0"), Decimal("3.0"), Decimal("5.0"), Decimal("2.5"), Decimal("4.7")],
)
def test_review_accepts_one_decimal_in_range(good_rating: Decimal) -> None:
    review = _review(rating=good_rating)
    assert review.rating == good_rating


def test_review_rejects_an_unsupported_language() -> None:
    with pytest.raises(ReviewValidationError, match="language"):
        _review(language="fr")


def test_review_rejects_an_over_long_content() -> None:
    with pytest.raises(ReviewValidationError, match="content exceeds"):
        _review(content="x" * (MAX_REVIEW_CONTENT_LENGTH + 1))


def test_review_rejects_an_over_long_reviewer_name() -> None:
    with pytest.raises(ReviewValidationError, match="name exceeds"):
        _review(reviewer_name="x" * (MAX_REVIEWER_NAME_LENGTH + 1))


def test_review_coerces_unknown_recurring_issue_to_other(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R2.2 / D7: the closed tag set degrades an invented tag to `OTHER` and logs a warning.

    Without this guard a writer that forgot to type-narrow would persist the invented
    value into a JSONB column whose census entry promises the enum.
    """
    with caplog.at_level("WARNING"):
        review = _review(recurring_issues=["unknown_tag", RecurringIssueTag.WIFI])  # type: ignore[list-item]
    assert review.recurring_issues == (RecurringIssueTag.OTHER, RecurringIssueTag.WIFI)
    assert any("dropped_unknown_tag" in record.message for record in caplog.records)


def test_review_keeps_recurring_issues_immutable_in_shape() -> None:
    """`Review.recurring_issues` is a tuple, not a list, so a writer cannot append
    post-construction and bypass the `__post_init__` guard."""
    review = _review(recurring_issues=[RecurringIssueTag.NOISE])
    assert isinstance(review.recurring_issues, tuple)


# ---------------------------------------------------------------------------
# State machine (R4.1, D4)
# ---------------------------------------------------------------------------


def test_mark_drafted_moves_new_to_drafted() -> None:
    review = _review()
    now = datetime.now(timezone.utc)
    review.mark_drafted(now=now)
    assert review.status is ReviewStatus.DRAFTED


@pytest.mark.parametrize(
    ("method", "expected_target"),
    [
        ("approve", ReviewStatus.APPROVED),
        ("ignore", ReviewStatus.IGNORED),
    ],
)
def test_legal_transitions_pass(method: str, expected_target: ReviewStatus) -> None:
    review = _review()
    now = datetime.now(timezone.utc)
    getattr(review, method)(now=now)
    assert review.status is expected_target


@pytest.mark.parametrize(
    ("method", "start_status"),
    [
        # D4: the four illegal jumps.
        ("approve", ReviewStatus.NEW),
        ("approve", ReviewStatus.IGNORED),
        ("mark_posted_manually", ReviewStatus.DRAFTED),
        ("mark_posted_manually", ReviewStatus.NEW),
    ],
)
def test_illegal_transitions_raise(method: str, start_status: ReviewStatus) -> None:
    review = _review(status=start_status)
    now = datetime.now(timezone.utc)
    with pytest.raises(InvalidReviewTransitionError):
        getattr(review, method)(now=now)


def test_terminal_states_admit_no_further_transitions() -> None:
    """`POSTED_MANUALLY` and `IGNORED` are terminal (D4): once a review sits there, no
    method returns without raising."""
    for terminal in (ReviewStatus.IGNORED, ReviewStatus.POSTED_MANUALLY):
        review = _review(status=terminal)
        now = datetime.now(timezone.utc)
        for method in ("mark_drafted", "approve", "ignore", "mark_posted_manually"):
            with pytest.raises(InvalidReviewTransitionError):
                getattr(review, method)(now=now)


def test_ignore_works_from_drafted_too() -> None:
    """A manager can shelve a draft without posting (R4.1)."""
    review = _review(status=ReviewStatus.DRAFTED)
    review.ignore(now=datetime.now(timezone.utc))
    assert review.status is ReviewStatus.IGNORED


def test_mark_classified_low_confidence_clears_the_three_ai_fields() -> None:
    """R2.3: confidence below threshold leaves the row with `sentiment`, `ai_summary=None`,
    `recurring_issues=()`."""
    review = _review(
        sentiment=ReviewSentiment.NEUTRAL,
        ai_summary="stale summary",
        recurring_issues=(RecurringIssueTag.WIFI,),
    )
    now = datetime.now(timezone.utc)
    review.mark_classified_low_confidence(
        sentiment=ReviewSentiment.POSITIVE, now=now
    )
    assert review.sentiment is ReviewSentiment.POSITIVE
    assert review.ai_summary is None
    assert review.recurring_issues == ()


def test_assign_analysis_preserves_status() -> None:
    """Re-classifying a `DRAFTED` review updates the AI fields but does not move the axis."""
    review = _review(status=ReviewStatus.DRAFTED)
    now = datetime.now(timezone.utc)
    review.assign_analysis(
        sentiment=ReviewSentiment.NEGATIVE,
        summary="Noise complaint noted",
        recurring_issues=(RecurringIssueTag.NOISE,),
        now=now,
    )
    assert review.status is ReviewStatus.DRAFTED
    assert review.sentiment is ReviewSentiment.NEGATIVE
    assert review.ai_summary == "Noise complaint noted"
    assert review.recurring_issues == (RecurringIssueTag.NOISE,)


def test_increment_attempts_advances_the_counter() -> None:
    review = _review()
    now = datetime.now(timezone.utc)
    review.increment_attempts(now=now)
    review.increment_attempts(now=now)
    assert review.classification_attempts == 2


# ---------------------------------------------------------------------------
# ReviewResponseDraft (R3.5, R3.6, D5)
# ---------------------------------------------------------------------------


def _draft(**overrides) -> ReviewResponseDraft:
    now = datetime.now(timezone.utc)
    return ReviewResponseDraft(
        id=overrides.pop("id", uuid.uuid4()),
        review_id=overrides.pop("review_id", uuid.uuid4()),
        draft_content=overrides.pop("draft_content", "Gracias por su valoracion."),
        language=overrides.pop("language", "es"),
        created_at=overrides.pop("created_at", now),
        updated_at=overrides.pop("updated_at", now),
        **overrides,
    )


def test_review_response_draft_instantiates_with_defaults() -> None:
    draft = _draft()
    assert draft.ai_generated is True
    assert draft.approved_by is None
    assert draft.approved_at is None
    assert draft.edits_count == 0


def test_review_response_draft_has_no_tenant_of_its_own() -> None:
    """§7.21 gives it no tenant_id: it is scoped through its parent review."""
    assert "tenant_id" not in ReviewResponseDraft.__dataclass_fields__


def test_review_response_draft_rejects_an_unsupported_language() -> None:
    with pytest.raises(ReviewValidationError, match="language"):
        _draft(language="fr")


def test_edit_increments_edits_count_and_keeps_ai_generated_true() -> None:
    draft = _draft()
    now = datetime.now(timezone.utc)
    draft.edit(new_content="Otra version del borrador.", now=now)
    assert draft.edits_count == 1
    assert draft.draft_content == "Otra version del borrador."
    assert draft.ai_generated is True


def test_edit_refuses_empty_content() -> None:
    draft = _draft()
    with pytest.raises(ReviewValidationError, match="cannot be empty"):
        draft.edit(new_content="   ", now=datetime.now(timezone.utc))


def test_edit_refuses_over_long_content() -> None:
    draft = _draft()
    with pytest.raises(ReviewValidationError, match="content exceeds"):
        draft.edit(
            new_content="x" * (MAX_REVIEW_CONTENT_LENGTH + 1),
            now=datetime.now(timezone.utc),
        )


def test_edit_refuses_change_after_approval() -> None:
    """R3.6: approval locks the content."""
    draft = _draft()
    now = datetime.now(timezone.utc)
    draft.approve(actor_id=uuid.uuid4(), now=now)
    with pytest.raises(ReviewValidationError, match="approved"):
        draft.edit(new_content="Too late.", now=now)


def test_approve_records_actor_and_timestamp() -> None:
    draft = _draft()
    actor = uuid.uuid4()
    now = datetime.now(timezone.utc)
    draft.approve(actor_id=actor, now=now)
    assert draft.approved_by == actor
    assert draft.approved_at == now
