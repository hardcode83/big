import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.reviews.domain.enums import ReviewChannel, ReviewSentiment, ReviewStatus


@dataclass
class Review:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    channel: ReviewChannel
    created_at: datetime
    updated_at: datetime
    reservation_id: uuid.UUID | None = None
    external_id: str | None = None
    reviewer_name: str | None = None
    rating: Decimal | None = None
    content: str | None = None
    language: str | None = None
    sentiment: ReviewSentiment | None = None
    ai_summary: str | None = None
    recurring_issues: list[Any] | None = None
    status: ReviewStatus = ReviewStatus.NEW
    published_at: datetime | None = None


@dataclass
class ReviewResponseDraft:
    """No tenant_id of its own (§7.21): scoped transitively through `review_id`."""

    id: uuid.UUID
    review_id: uuid.UUID
    draft_content: str
    language: str
    created_at: datetime
    updated_at: datetime
    ai_generated: bool = True
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
