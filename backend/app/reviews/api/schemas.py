"""Request/response DTOs of the seven review endpoints (R5, R3.5, R4.2; design D11).

Three rules this module exists to enforce:

* **No request schema has a `tenant_id`.** The effective tenant comes only from the verified
  token.
* **`extra="forbid"` on every body**, so a body that mentions `tenant_id` or `id` is a
  `422` rather than a silently ignored key.
* **No field a client can set to whatever they like**: `rating` is bounded `1.0..5.0`,
  `channel` is bounded by `ReviewChannel`, `language` is bounded by `SUPPORTED_LANGUAGES`,
  and the `action` on `PATCH /response` is a `Literal` of four members.

The envelope — `{data, total, page, per_page, total_pages}` — is the same shape
`messaging` and `maintenance` ship (PRD §23).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.reviews.domain.entities import Review, ReviewResponseDraft
from app.reviews.domain.enums import (
    RecurringIssueTag,
    ReviewChannel,
    ReviewSentiment,
    ReviewStatus,
)

MAX_PER_PAGE = 100
#: `page` needs a ceiling too, not just `per_page`: it becomes a SQL OFFSET and a
#: 20-digit page number overflows int8. Same bound and same reason as
#: `messaging`/`maintenance`/`tenants`.
MAX_PAGE = 100_000


class CreateReviewRequest(BaseModel):
    """R5.1 — what the manager posts to `POST /reviews`."""

    model_config = ConfigDict(extra="forbid")

    property_id: uuid.UUID
    channel: ReviewChannel
    reviewer_name: Annotated[str | None, Field(default=None, max_length=200)] = None
    rating: Annotated[Decimal | None, Field(default=None, ge=Decimal("1.0"), le=Decimal("5.0"))] = (
        None
    )
    content: Annotated[str | None, Field(default=None, max_length=4000)] = None
    language: Annotated[str | None, Field(default=None, max_length=5)] = None
    reservation_id: uuid.UUID | None = None


class ReviewResponse(BaseModel):
    """What an authenticated operator may see about one review.

    Fields are enumerated rather than dumped from the entity, so a `from_attributes`
    dump would never publish whatever `Review` grows next.
    """

    id: uuid.UUID
    property_id: uuid.UUID
    channel: ReviewChannel
    reviewer_name: str | None
    rating: Decimal | None
    content: str | None
    language: str | None
    sentiment: ReviewSentiment | None
    ai_summary: str | None
    recurring_issues: list[RecurringIssueTag]
    status: ReviewStatus
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    classification_attempts: int
    reservation_id: uuid.UUID | None

    @classmethod
    def from_domain(cls, review: Review) -> "ReviewResponse":
        return cls(
            id=review.id,
            property_id=review.property_id,
            channel=review.channel,
            reviewer_name=review.reviewer_name,
            rating=review.rating,
            content=review.content,
            language=review.language,
            sentiment=review.sentiment,
            ai_summary=review.ai_summary,
            recurring_issues=list(review.recurring_issues),
            status=review.status,
            published_at=review.published_at,
            created_at=review.created_at,
            updated_at=review.updated_at,
            classification_attempts=review.classification_attempts,
            reservation_id=review.reservation_id,
        )


class ReviewDraftResponse(BaseModel):
    """The draft of one review (R5.4)."""

    id: uuid.UUID
    review_id: uuid.UUID
    draft_content: str
    language: str
    ai_generated: bool
    edits_count: int
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, draft: ReviewResponseDraft) -> "ReviewDraftResponse":
        return cls(
            id=draft.id,
            review_id=draft.review_id,
            draft_content=draft.draft_content,
            language=draft.language,
            ai_generated=draft.ai_generated,
            edits_count=draft.edits_count,
            approved_by=draft.approved_by,
            approved_at=draft.approved_at,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )


class ReviewSummaryResponse(BaseModel):
    """R5.5 — the per-property card the dashboard renders."""

    window_days: int
    top_n: int
    by_sentiment: dict[ReviewSentiment, int]
    by_recurring_issue: dict[RecurringIssueTag, int]


class ReviewResponseActionRequest(BaseModel):
    """R3.5 / R4.2 — the body of `PATCH /reviews/{id}/response`.

    `action = EDIT` carries a `draft_content`; the other three do not.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["APPROVE", "IGNORE", "MARK_POSTED", "EDIT"]
    draft_content: Annotated[str | None, Field(default=None, max_length=4000)] = None


class RegenerateReviewDraftRequest(BaseModel):
    """R3.5 — the body of `POST /reviews/{id}/response` (regenerate the draft)."""

    model_config = ConfigDict(extra="forbid")

    language: Annotated[str | None, Field(default=None, max_length=5)] = None


class ReviewPageResponse(BaseModel):
    """PRD §23 envelope for the listing endpoint."""

    items: list[ReviewResponse]
    total: int
    page: int
    per_page: int

    @classmethod
    def from_domain(
        cls,
        reviews: Sequence[Review],
        *,
        total: int,
        page: int,
        per_page: int,
    ) -> "ReviewPageResponse":
        return cls(
            items=[ReviewResponse.from_domain(review) for review in reviews],
            total=total,
            page=page,
            per_page=per_page,
        )


__all__ = [
    "CreateReviewRequest",
    "ReviewResponse",
    "ReviewDraftResponse",
    "ReviewSummaryResponse",
    "ReviewResponseActionRequest",
    "RegenerateReviewDraftRequest",
    "ReviewPageResponse",
    "MAX_PAGE",
    "MAX_PER_PAGE",
]
