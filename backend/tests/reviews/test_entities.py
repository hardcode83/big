import uuid
from datetime import datetime, timezone

from app.reviews.domain.entities import Review, ReviewResponseDraft
from app.reviews.domain.enums import ReviewChannel, ReviewStatus


def test_review_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    review = Review(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        channel=ReviewChannel.AIRBNB,
        created_at=now,
        updated_at=now,
    )

    assert review.status is ReviewStatus.NEW
    assert review.reservation_id is None
    assert review.rating is None
    assert review.sentiment is None
    assert review.recurring_issues is None
    assert review.published_at is None


def test_review_response_draft_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    draft = ReviewResponseDraft(
        id=uuid.uuid4(),
        review_id=uuid.uuid4(),
        draft_content="Thank you for staying with us.",
        language="en",
        created_at=now,
        updated_at=now,
    )

    assert draft.ai_generated is True
    assert draft.approved_by is None
    assert draft.approved_at is None


def test_review_response_draft_has_no_tenant_of_its_own() -> None:
    """§7.21 gives it no tenant_id: it is scoped through its parent review."""
    assert "tenant_id" not in ReviewResponseDraft.__dataclass_fields__
