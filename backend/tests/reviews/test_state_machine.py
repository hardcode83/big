"""The state machine on `Review` (R4.1, design D4).

Five legal moves and four illegal ones — the legal moves pass through their methods,
the illegal ones raise `InvalidReviewTransitionError`. The route answers `409`
through `api/errors.py`. `POSTED_MANUALLY` and `IGNORED` are terminal.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.reviews.domain.entities import Review, ReviewResponseDraft
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
    now = datetime.now(UTC)
    return Review(
        id=overrides.pop("id", uuid.uuid4()),
        tenant_id=overrides.pop("tenant_id", uuid.uuid4()),
        property_id=overrides.pop("property_id", uuid.uuid4()),
        channel=overrides.pop("channel", ReviewChannel.MANUAL),
        created_at=overrides.pop("created_at", now),
        updated_at=overrides.pop("updated_at", now),
        **overrides,
    )


@pytest.mark.parametrize(
    ("method", "expected_target"),
    [
        ("mark_drafted", ReviewStatus.DRAFTED),
        ("ignore", ReviewStatus.IGNORED),
    ],
)
def test_legal_transitions_pass(method: str, expected_target: ReviewStatus) -> None:
    review = _review()
    getattr(review, method)(now=datetime.now(UTC))
    assert review.status is expected_target


def test_ignore_works_from_drafted() -> None:
    """A manager can shelve a draft without posting it (R4.1)."""
    review = _review(status=ReviewStatus.DRAFTED)
    review.ignore(now=datetime.now(UTC))
    assert review.status is ReviewStatus.IGNORED


def test_mark_drafted_only_from_new() -> None:
    review = _review(status=ReviewStatus.DRAFTED)
    with pytest.raises(InvalidReviewTransitionError):
        review.mark_drafted(now=datetime.now(UTC))


def test_approve_only_from_drafted() -> None:
    review = _review(status=ReviewStatus.NEW)
    with pytest.raises(InvalidReviewTransitionError):
        review.approve(now=datetime.now(UTC))


def test_mark_posted_manually_only_from_approved() -> None:
    review = _review(status=ReviewStatus.DRAFTED)
    with pytest.raises(InvalidReviewTransitionError):
        review.mark_posted_manually(now=datetime.now(UTC))


def test_terminal_states_admit_no_further_transitions() -> None:
    for terminal in (ReviewStatus.IGNORED, ReviewStatus.POSTED_MANUALLY):
        review = _review(status=terminal)
        for method in (
            "mark_drafted",
            "approve",
            "ignore",
            "mark_posted_manually",
        ):
            with pytest.raises(InvalidReviewTransitionError):
                getattr(review, method)(now=datetime.now(UTC))


def test_assign_analysis_preserves_status() -> None:
    """Re-classifying a `DRAFTED` review updates the AI fields but does not move the
    axis (D4): the row's transition and its analysis are two separate facts."""
    review = _review(status=ReviewStatus.DRAFTED)
    review.assign_analysis(
        sentiment=ReviewSentiment.NEGATIVE,
        summary="Noise complaint noted",
        recurring_issues=(RecurringIssueTag.NOISE,),
        now=datetime.now(UTC),
    )
    assert review.status is ReviewStatus.DRAFTED
    assert review.sentiment is ReviewSentiment.NEGATIVE
    assert review.ai_summary == "Noise complaint noted"


def test_mark_classified_low_confidence_clears_three_ai_fields() -> None:
    """R2.3: below the threshold, the three AI fields are cleared and the status moves."""
    review = _review(
        sentiment=ReviewSentiment.NEUTRAL,
        ai_summary="stale summary",
        recurring_issues=(RecurringIssueTag.WIFI,),
    )
    review.mark_classified_low_confidence(
        sentiment=ReviewSentiment.POSITIVE, now=datetime.now(UTC)
    )
    assert review.sentiment is ReviewSentiment.POSITIVE
    assert review.ai_summary is None
    assert review.recurring_issues == ()


# ---------------------------------------------------------------------------
# Draft state (R3.5, R3.6, D5)
# ---------------------------------------------------------------------------


def _draft(**overrides) -> ReviewResponseDraft:
    now = datetime.now(UTC)
    return ReviewResponseDraft(
        id=overrides.pop("id", uuid.uuid4()),
        review_id=overrides.pop("review_id", uuid.uuid4()),
        draft_content=overrides.pop("draft_content", "Gracias por su valoracion."),
        language=overrides.pop("language", "es"),
        created_at=overrides.pop("created_at", now),
        updated_at=overrides.pop("updated_at", now),
        **overrides,
    )


def test_edit_increments_edits_count_and_keeps_ai_generated_true() -> None:
    draft = _draft()
    draft.edit(new_content="Otra version del borrador.", now=datetime.now(UTC))
    assert draft.edits_count == 1
    assert draft.ai_generated is True


def test_edit_after_approval_is_refused() -> None:
    draft = _draft()
    draft.approve(actor_id=uuid.uuid4(), now=datetime.now(UTC))
    with pytest.raises(ReviewValidationError, match="approved"):
        draft.edit(new_content="Too late.", now=datetime.now(UTC))


def test_approve_locks_edits_for_good() -> None:
    """R3.6: a second `approve()` is harmless (the row is already approved), but
    subsequent `edit()` calls are refused."""
    draft = _draft()
    actor = uuid.uuid4()
    draft.approve(actor_id=actor, now=datetime.now(UTC))
    assert draft.approved_by == actor
    with pytest.raises(ReviewValidationError):
        draft.edit(new_content="Anything", now=datetime.now(UTC))
