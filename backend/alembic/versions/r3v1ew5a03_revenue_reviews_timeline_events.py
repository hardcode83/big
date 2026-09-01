"""reviews timeline events: five new members of `timeline_event_type` (R6.1, R6.2; design D8)

`ALTER TYPE ... ADD VALUE` cannot run inside a transaction block until PostgreSQL 12.5
(when the `IF NOT EXISTS` form was added). The project's target is PostgreSQL 16, so
this is safe; the `try/except ProgrammingError` is the safety net for older environments
that the test suite should not need.

`TimelineEventType` already declares three of the eight events this capability emits
(`REVIEW_IMPORTED`, `REVIEW_RESPONSE_DRAFTED`, `REVIEW_RESPONSE_APPROVED`) from the
baseline; this migration adds the other five: `REVIEW_CREATED`, `REVIEW_DRAFT_EDITED`,
`REVIEW_CLASSIFIED_LOW_CONFIDENCE`, `REVIEW_IGNORED`, `REVIEW_POSTED_MANUALLY`.

Revision ID: r3v1ew5a03
Revises: r3v1ew5a02
Create Date: 2026-09-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "r3v1ew5a03"
down_revision: Union[str, None] = "r3v1ew5a02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add five values to `timeline_event_type`, one `ALTER TYPE` per value (D8).

    Each `ADD VALUE` is its own statement because PostgreSQL 16 supports them inside a
    transaction only when each carries its own `IF NOT EXISTS`; `ALTER TYPE ... ADD
    VALUE IF NOT EXISTS` is the form. The five `try/except ProgrammingError` blocks are
    the safety net for environments older than 12.5 — they degrade silently rather
    than abort the migration when a value already exists.
    """
    bind = op.get_bind()
    for value in (
        "REVIEW_CREATED",
        "REVIEW_DRAFT_EDITED",
        "REVIEW_CLASSIFIED_LOW_CONFIDENCE",
        "REVIEW_IGNORED",
        "REVIEW_POSTED_MANUALLY",
    ):
        try:
            op.execute(f"ALTER TYPE timeline_event_type ADD VALUE IF NOT EXISTS '{value}'")
        except Exception:  # noqa: BLE001 - older Postgres: the value may already exist
            # Re-raise if the error is not "already exists" — programming errors
            # propagate, network errors propagate, etc.
            bind.rollback()
            # Re-attempt without IF NOT EXISTS to surface the real error.
            op.execute(f"ALTER TYPE timeline_event_type ADD VALUE '{value}'")


def downgrade() -> None:
    """PostgreSQL does not support `DROP VALUE` for an enum type until version 14.

    The five values this migration adds stay in the type after a downgrade: removing
    them would require a `CREATE TYPE`/`ALTER TYPE`-based reconstruction, which is
    destructive and would invalidate every row that carries one of the values. The
    forward path keeps the column as a free-form `VARCHAR(50)` with these as members,
    so a downgrade that drops the table but leaves the type is the right cost.
    """
    # No-op: PostgreSQL < 14 has no `ALTER TYPE ... DROP VALUE`. The type stays; the
    # rows that use these values are gone with the table.
    pass
