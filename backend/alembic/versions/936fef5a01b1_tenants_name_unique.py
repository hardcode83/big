"""tenants_name_unique: add `uq_tenants_name` to `tenants.name` (`platform-admin-api`, R-2 / D2)

`tenants.name` is the only natural handle on the row the API exposes before its `id` is
known — `POST /api/v1/platform/tenants` takes a `name`, not an `id` — and the document
search in `docs/platform.md` (per D6) is keyed on the same column. The `bootstrap.py`
comment at line 176 already names the gap: the baseline declared `tenants.name` as a
plain `String(200)` and the application translated "name already taken" by catching an
`asyncpg.UniqueViolationError` against a `unique` index that was never created. That
worked because `bootstrap.py` is the only writer today, and its own de-duplication check
runs first; `platform-admin-api`'s API would not be so lucky.

The constraint closes the gap the design assumed (`platform-admin-api` D2, R-2). **D2
explicitly recorded that the constraint would already be in place**; it is not — the
baseline `4a5faad7796b_baseline_domain_foundation_core.py` declares `tenants.name` as a
plain `String(200)` with no `UniqueConstraint`. This amendment adds it on the change
that needs it, which is what D2's own footnote ("if the constraint is missing at the
moment `POST /tenants` lands, the migration that adds it belongs to that change, not to
a retroactive one") says it should be.

**No backfill.** The change adds a uniqueness guarantee the application will rely on; the
existing rows it constrains are the ones the bootstrap wrote, and `bootstrap.py` is the
one path that already refuses to write a duplicate by name. There is no scenario in which
the column can hold two equal values at the time this migration runs, and so the
`ADD CONSTRAINT` cannot fail on data the migration has not yet constrained.

**`downgrade()` is a plain drop, and not a guarded one.** The reverse of the deviation
recorded above is the constraint being gone — not the column being gone. Removing the
constraint cannot leave the data in a state the constraint would have rejected, and the
next `INSERT` would be a `500` from the same `IntegrityError` `bootstrap.py` already
catches and translates. No rows need to be inspected.

Revision ID: 936fef5a01b1
Revises: 936fef59b1d4
Create Date: 2026-09-02 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "936fef5a01b1"
down_revision: Union[str, Sequence[str], None] = "936fef59b1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UNIQUE_CONSTRAINT = "uq_tenants_name"
_TABLE = "tenants"
_COLUMN = "name"


def upgrade() -> None:
    """Add the unique constraint the API relies on."""
    op.create_unique_constraint(_UNIQUE_CONSTRAINT, _TABLE, [_COLUMN])


def downgrade() -> None:
    """Drop the constraint — does not touch the column, does not inspect rows."""
    op.drop_constraint(_UNIQUE_CONSTRAINT, _TABLE, type_="unique")
