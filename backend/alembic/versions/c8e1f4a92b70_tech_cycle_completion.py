"""tech cycle completion: the technician's ETA, their materials, and a refusal event

Three additive statements, one revision (`tech-cycle-completion` design D9):

- `incidents.eta_at` — the hour the technician says they will arrive (R3.1). Belongs to the
  assignment in force, so `assign` and `reject` both clear it; nothing about that is the
  database's business, which is why this is a plain nullable column.
- `incidents.materials` — what they say they put in, typed on closing (R4.1). `VARCHAR(2000)`
  and not `TEXT`: the bound lives in the DDL as well as in pydantic, which is the pattern
  `properties` follows and what `properties-crud` R2.4 had to retrofit onto four columns that
  shipped bounded on one side only. `MAX_MATERIALS` in
  `app/maintenance/domain/entities.py` mirrors this number and
  `tests/test_migrations.py::test_the_declared_column_widths_reach_the_real_ddl` reads it back
  out of `information_schema`.
- `timeline_event_type.TECHNICIAN_REJECTED` — R1.9. The technician's refusal had no member of
  the vocabulary, and reusing `INCIDENT_CANCELLED` would have asserted for ever — the timeline
  is append-only — that the incident was closed when it in fact went back to the manager.

**Nullable, no server default, no backfill** (R5.6). Every existing incident keeps `NULL` for
both columns, which is the honest answer — nobody promised an hour and nobody declared any
parts — rather than an invented empty string a client would then have to tell apart from one.
On PostgreSQL 16 `ADD COLUMN ... NULL` without a default does not rewrite the table, so this
cannot fail on populated data; the dev database has had rows since 2026-08-10.

**On `ALTER TYPE ... ADD VALUE` and `autocommit_block()`.** Not needed, and the reasoning is
`e7a3c419d82b_guest_portal_api.py`'s, which had already worked it out from
`b7c41d92e5a3_session_revoked_reason_administrative.py`: on PostgreSQL 12+ the restriction is
on *using* the new label in the transaction that adds it, not on adding it, and this revision
writes no `timeline_events` row. An autocommit block would actively cost something rather than
being free insurance — `alembic/env.py` wraps the whole run in one `context.begin_transaction()`,
so it would commit every revision applied before it and give up the all-or-nothing property of
`alembic upgrade head`.

`IF NOT EXISTS` on the label so re-running against a database where a previous attempt
half-applied is not an error.

**The enum label is not removed on the way down, and `downgrade` says so rather than
pretending.** PostgreSQL cannot drop a value from an enum type; the only route is recreating
the type, rewriting every column that uses it and deciding what to do with rows already
carrying the value — a data decision this revision has no basis to make. An unused label costs
nothing, and `alembic downgrade base` (which CI runs) drops the whole type in the revision that
created it anyway. The two columns *are* dropped, and what is lost with them is whatever was
written after this revision applied, which is what a `DROP COLUMN` always means.

Revision ID: c8e1f4a92b70
Revises: b3f5d1c8a047
Create Date: 2026-08-22 00:00:00.000000

**Chained onto `b3f5d1c8a047` and not onto the `b9d24e70c1af` the design first named.** That
revision stopped being the head when `cleaner-incident-report` landed `b3f5d1c8a047` on top of
it, and D9's own rule settles which one to follow: the project's chain is strictly linear —
no merge revision anywhere — and `tests/test_migrations.py` walks it in both directions, so
chaining onto the older one would have produced two heads. Measured at implementation time and
recorded in D9.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c8e1f4a92b70'
down_revision: Union[str, Sequence[str], None] = 'b3f5d1c8a047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIMELINE_EVENT_TYPE_ENUM = 'timeline_event_type'
TECHNICIAN_REJECTED = 'TECHNICIAN_REJECTED'


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'incidents',
        sa.Column('eta_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'incidents',
        sa.Column('materials', sa.String(length=2000), nullable=True),
    )
    op.execute(
        f"ALTER TYPE {TIMELINE_EVENT_TYPE_ENUM} ADD VALUE IF NOT EXISTS "
        f"'{TECHNICIAN_REJECTED}'"
    )


def downgrade() -> None:
    """Downgrade schema.

    The enum label stays — see the module docstring. Both columns are dropped.
    """
    op.drop_column('incidents', 'materials')
    op.drop_column('incidents', 'eta_at')
