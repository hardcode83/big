"""cleaner incident report: incidents.cleaning_task_id

One additive, nullable column (`cleaner-incident-report` R4.1, design D10): the cleaning
task during which a cleaner opened the incident.

`ondelete='RESTRICT'`, like `property_id` and `reservation_id` on the same table, and not
the `SET NULL` the two foreign keys towards `users` carry: losing the link is worst exactly
when someone deletes the task it points at.

**No backfill and no index.** Every existing row stays `NULL`, which R4.2 declares valid —
an incident opened from the guest portal, derived from a conversation or written by the demo
seed never had a cleaning behind it. Nothing in this change queries by the column, so an
index would be a cost with no reader.

Revision ID: b3f5d1c8a047
Revises: e7a3c419d82b
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f5d1c8a047'
down_revision: Union[str, Sequence[str], None] = 'e7a3c419d82b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'incidents',
        sa.Column('cleaning_task_id', sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        'incidents_cleaning_task_id_fkey',
        'incidents',
        'cleaning_tasks',
        ['cleaning_task_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('incidents_cleaning_task_id_fkey', 'incidents', type_='foreignkey')
    op.drop_column('incidents', 'cleaning_task_id')
