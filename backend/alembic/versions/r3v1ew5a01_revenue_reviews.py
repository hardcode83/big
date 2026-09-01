"""reviews: the two aggregates of the reviews capability

Creates the `reviews` and `review_response_drafts` tables (R1.1, R1.2; design D10, D15).

The `domain-foundation-financial` migration created both tables and then dropped them in
`downgrade()` — that change was a placeholder, not the owner. `revenue-reviews` brings
its own migration and re-creates them with the final shape: `tenant_id` only on `reviews`
(R1.1, an explicit divergence from `messages`/`review_response_drafts`), the new
`classification_attempts` column on `reviews` (D5 / OQ4: the counter that sustains
R2.4's "three attempts and park for manual triage"), and `edits_count` on
`review_response_drafts` (D5 / OQ4: bitácora de iteraciones del borrador).

**Three indexes** for `reviews`. `ix_reviews_tenant_id` is the basic filter of rule 1
of `steering/security.md`; `ix_reviews_property_id_status` speeds the listing of R5.3
(filtered by property and ordered by status); and `ix_reviews_tenant_id_published_at`
backs the inbox ordering `published_at DESC NULLS LAST`. None of them is speculative —
each has a named reader.

**`tenant_id` does not exist on `review_response_drafts`**, and the comment in
`infrastructure/models.py:46-53` already explains why: `messages` is the precedent.
The repository adapter joins `reviews` explicitly to activate the global loader criteria;
the test `tests/reviews/test_tenant_isolation.py` pins the contract end to end.

**`server_default='0'` on both counters, not `now()`**: the counters are integers, and
`now()` on an integer column would fail at the driver. Both have the same default the
entity declares, so an `INSERT` from a writer that does not set them lands in the same
state the dataclass declares.

Revision ID: r3v1ew5a01
Revises: e5c9b1f47a28
Create Date: 2026-09-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "r3v1ew5a01"
down_revision: Union[str, None] = "e5c9b1f47a28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column(
            "channel",
            sa.Enum(
                "AIRBNB",
                "BOOKING",
                "GOOGLE",
                "MANUAL",
                "OTHER",
                name="review_channel",
            ),
            nullable=False,
        ),
        sa.Column("reviewer_name", sa.String(length=200), nullable=True),
        sa.Column("rating", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=5), nullable=True),
        sa.Column(
            "sentiment",
            sa.Enum(
                "POSITIVE",
                "NEUTRAL",
                "NEGATIVE",
                name="review_sentiment",
            ),
            nullable=True,
        ),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("recurring_issues", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "NEW",
                "DRAFTED",
                "APPROVED",
                "POSTED_MANUALLY",
                "IGNORED",
                name="review_status",
            ),
            server_default="NEW",
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "classification_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_reviews_tenant_id"),
        "reviews",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_reviews_property_id_status",
        "reviews",
        ["property_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_reviews_tenant_id_published_at",
        "reviews",
        ["tenant_id", "published_at"],
        unique=False,
    )

    op.create_table(
        "review_response_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("draft_content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("ai_generated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "edits_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", name="uq_review_response_drafts_review_id"),
    )


def downgrade() -> None:
    op.drop_table("review_response_drafts")
    op.drop_index("ix_reviews_tenant_id_published_at", table_name="reviews")
    op.drop_index("ix_reviews_property_id_status", table_name="reviews")
    op.drop_index(op.f("ix_reviews_tenant_id"), table_name="reviews")
    op.drop_table("reviews")
