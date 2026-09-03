"""timeline tenant_id + created_at index

Adds the covering index `dashboard-activity-feed` design D4 asks for: `list_for_tenant`
(`app/timeline/infrastructure/repositories.py`) filters and orders by
`(tenant_id, created_at DESC)`, and no existing index on `timeline_events` covers that
pair — the three that exist lead with `property_id`, `tenant_id, event_type` and
`reservation_id` respectively, none of which the tenant-wide feed filters on first.

Index-only, reversible, no data changes.

Revision ID: ecc25b9ad299
Revises: 4ba1f499f7c2
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ecc25b9ad299'
down_revision: Union[str, None] = '4ba1f499f7c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_timeline_events_tenant_id_created_at",
        "timeline_events",
        ["tenant_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_timeline_events_tenant_id_created_at",
        table_name="timeline_events",
    )
