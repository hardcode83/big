import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.reviews.domain.enums import ReviewChannel, ReviewSentiment, ReviewStatus


class ReviewModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "reviews"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), default=None
    )
    external_id: Mapped[str | None] = mapped_column(String(200), default=None)
    channel: Mapped[ReviewChannel] = mapped_column(
        Enum(ReviewChannel, name="review_channel", native_enum=True)
    )
    reviewer_name: Mapped[str | None] = mapped_column(String(200), default=None)
    # No CHECK on the 1.0-5.0 range: §7.20 documents it in a comment but declares no
    # constraint, and range validation belongs to the domain layer of `revenue` (D12).
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), default=None)
    content: Mapped[str | None] = mapped_column(default=None)
    language: Mapped[str | None] = mapped_column(String(5), default=None)
    sentiment: Mapped[ReviewSentiment | None] = mapped_column(
        Enum(ReviewSentiment, name="review_sentiment", native_enum=True), default=None
    )
    ai_summary: Mapped[str | None] = mapped_column(default=None)
    recurring_issues: Mapped[list[Any] | None] = mapped_column(JSONB, default=None)
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", native_enum=True),
        default=ReviewStatus.NEW,
        server_default=ReviewStatus.NEW.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ReviewResponseDraftModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """No tenant_id of its own (§7.21).

    Scoped transitively through the mandatory, unique `review_id`. The global tenant
    filter matches on column presence, so it does NOT cover this table — any
    repository touching it must join `reviews` explicitly (see the fifth limit in the
    docstring of `_scope_statement_to_tenant`).
    """

    __tablename__ = "review_response_drafts"

    review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reviews.id", ondelete="RESTRICT"), unique=True
    )
    draft_content: Mapped[str] = mapped_column()
    language: Mapped[str] = mapped_column(String(5))
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
