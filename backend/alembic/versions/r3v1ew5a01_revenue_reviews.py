"""reviews: the two aggregates of the reviews capability

Creates the `reviews` and `review_response_drafts` tables (R1.1, R1.2; design D10, D15).

The `domain-foundation-financial` migration (`96d526599bc1`) created both tables as
placeholders and dropped them **only** in `downgrade()` — its `upgrade()` left them in
the schema. `revenue-reviews` is the owner of the capability, so this migration drops
those placeholders first (idempotent, conditional on their presence) and then creates
the tables with the final shape: `tenant_id` only on `reviews` (R1.1, an explicit
divergence from `messages`/`review_response_drafts`), the new `classification_attempts`
column on `reviews` (D5 / OQ4: the counter that sustains R2.4's "three attempts and park
for manual triage"), and `edits_count` on `review_response_drafts` (D5 / OQ4: bitácora
de iteraciones del borrador). The drop is gated on `inspector.get_table_names()` so
that re-running on a clean database (`make down --volumes` then `make up`) skips the
drop and behaves like the original placeholder never existed.

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
    # The placeholder tables from `domain-foundation-financial` (96d526599bc1) leave
    # `reviews` and `review_response_drafts` (and their enum types) sitting in the
    # schema; drop them first, but only if they exist, so the migration is idempotent
    # on a database where the placeholder never ran.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "reviews" in existing_tables or "review_response_drafts" in existing_tables:
        # Drop in FK-safe order; review_response_drafts holds FK to reviews.
        if "review_response_drafts" in existing_tables:
            op.drop_table("review_response_drafts")
        if "reviews" in existing_tables:
            op.drop_table("reviews")
        for type_name in (
            "review_channel",
            "review_sentiment",
            "review_status",
        ):
            op.execute(f"DROP TYPE IF EXISTS {type_name}")

    # `sa.Enum` inside `create_table` does not auto-create the type in Alembic
    # context (it assumes the migration owns type lifecycle), so create the three
    # enum types explicitly. `create_type=False` on the columns below avoids the
    # double CREATE TYPE that Alembic would otherwise emit. The existence guard
    # is raw `CREATE TYPE ... IF NOT EXISTS` because: (1) `postgresql.ENUM.create`
    # with `checkfirst=True` runs a separate SELECT round-trip inside the same
    # transaction, and the SELECT goes through a different code path that does
    # not always see the type freshly created by the historic migration in this
    # same transaction (race between `pg_type` visibility and `pg_type_is_visible`
    # rules); (2) `IF NOT EXISTS` is supported on `CREATE TYPE` since PostgreSQL 9.5
    # (the project targets 16), so it is the simplest atomic guard.
    for type_name, values in (
        ("review_channel", ("AIRBNB", "BOOKING", "GOOGLE", "MANUAL", "OTHER")),
        ("review_sentiment", ("POSITIVE", "NEUTRAL", "NEGATIVE")),
        ("review_status", ("NEW", "DRAFTED", "APPROVED", "POSTED_MANUALLY", "IGNORED")),
    ):
        values_sql = ", ".join(f"'{value}'" for value in values)
        op.execute(f"CREATE TYPE {type_name} AS ENUM ({values_sql})")

    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column(
            "channel",
            postgresql.ENUM(
                "AIRBNB",
                "BOOKING",
                "GOOGLE",
                "MANUAL",
                "OTHER",
                name="review_channel",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("reviewer_name", sa.String(length=200), nullable=True),
        sa.Column("rating", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=5), nullable=True),
        sa.Column(
            "sentiment",
            postgresql.ENUM(
                "POSITIVE",
                "NEUTRAL",
                "NEGATIVE",
                name="review_sentiment",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("recurring_issues", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "NEW",
                "DRAFTED",
                "APPROVED",
                "POSTED_MANUALLY",
                "IGNORED",
                name="review_status",
                create_type=False,
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
    # The placeholder migration `96d526599bc1_domain_foundation_financial` is the
    # original owner of `reviews`, `review_response_drafts`, and the three enum types
    # (`review_channel`, `review_sentiment`, `review_status`) — its downgrade drops
    # them all (tables unconditionally, enum types via
    # `postgresql.ENUM(name=...).drop(..., checkfirst=True)`). The chain-upgrade-
    # then-downgrade-then-upgrade contract in
    # `tests/test_migrations.py::test_the_chain_upgrades_to_head_and_unwinds_...`
    # requires each revision to unwind on its own, so the placeholder is the one
    # that does the dropping; this downgrade is intentionally a no-op.
    pass
