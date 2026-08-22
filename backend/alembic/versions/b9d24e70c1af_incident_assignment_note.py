"""incidents.assignment_note: the note handed over with an assignment

One additive column (`tech-incident-context` design D6). PRD §7.13 declares no column for
it, so this is a **declared divergence** from the PRD schema, of the same kind as
`users.must_change_password` and `properties.has_wifi_password`.

`VARCHAR(2000)` and not `TEXT`: the bound lives in the DDL as well as in pydantic, which is
the pattern `properties` follows and what `properties-crud` R2.4 had to retrofit onto four
columns that shipped bounded on one side only.

**Nullable, no server default, no backfill.** Every existing incident keeps `NULL`, which is
the honest answer — nobody wrote a note — rather than an invented empty string a client
would then have to tell apart from one. On PostgreSQL 16 `ADD COLUMN ... NULL` without a
default does not rewrite the table, so this cannot fail on populated data; the dev database
has had rows since 2026-08-10.

`downgrade` drops the column. What is lost is whatever was written after this revision
applied, which is what a `DROP COLUMN` always means.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9d24e70c1af'
down_revision: Union[str, Sequence[str], None] = 'e7a3c419d82b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'incidents',
        sa.Column('assignment_note', sa.String(length=2000), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('incidents', 'assignment_note')
