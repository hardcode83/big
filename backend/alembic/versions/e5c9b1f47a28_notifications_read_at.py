"""notifications read_at: the in-app inbox stops being read-only

Adds `notification_logs.read_at` and the two indexes of `notifications-inbox-web` design D1
(R1.1).

**Nullable, no `server_default`, no backfill.** A row written before this column existed has
been read by nobody, so `NULL` is the truthful value for every one of them; `now()` as a
default would have declared the whole history read. `ADD COLUMN ... NULL` without a default
does not rewrite the table in PostgreSQL 16, so this cannot fail on populated data.

**Two indexes, and neither is speculative.** `notification_logs` had no index by recipient at
all — `__table_args__` declared only `(tenant_id, status, sla_deadline_at)` and
`(related_type, related_id)`, and `recipient_user_id` is a foreign key, which SQLAlchemy does
not index on its own. `list_for_recipient` has been scanning the tenant's whole table since
`access-notifications`, and this change is the first one to put users in front of it. The
second index is **partial** (`WHERE read_at IS NULL`) because the unread counter is the only
query every connected user issues every 60 s, and the only one whose cost grows without bound
as read rows accumulate: a partial index holds only the small set that is actually consulted.

Revision ID: e5c9b1f47a28
Revises: d4a7e18c6b93
Create Date: 2026-08-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5c9b1f47a28'
down_revision: Union[str, None] = 'd4a7e18c6b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification_logs",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notification_logs_tenant_id_recipient_user_id_created_at",
        "notification_logs",
        ["tenant_id", "recipient_user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_notification_logs_unread",
        "notification_logs",
        ["tenant_id", "recipient_user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notification_logs_unread", table_name="notification_logs")
    op.drop_index(
        "ix_notification_logs_tenant_id_recipient_user_id_created_at",
        table_name="notification_logs",
    )
    op.drop_column("notification_logs", "read_at")
