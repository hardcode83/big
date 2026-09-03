"""cleaning_task_messages_and_incident_messages

Two twin tables — `cleaning_task_messages` (domain `cleaning`) and `incident_messages`
(domain `maintenance`) — created in one revision (`staff-messaging` design D1, "un solo
change"), and the unique constraint on `cleaning_tasks` the first one's composite foreign
key needs.

**Same shape as `d4a7e18c6b93_incident_photos.py`, applied twice.** Each table carries its
own `tenant_id` and a COMPOSITE foreign key on `(tenant_id, task_id)` / `(tenant_id,
incident_id)` into its parent, `ON DELETE RESTRICT`. Postgres requires the referenced pair
to be a declared unique key: `incidents` already has `uq_incidents_tenant_id_id` (added by
`incident_photos`), but `cleaning_tasks` does not, so this revision adds
`uq_cleaning_tasks_tenant_id_id` before creating `cleaning_task_messages` — the same device,
for the same reason, and it cannot fail on existing data since `cleaning_tasks.id` is
already the primary key.

**`author_role` is a plain `VARCHAR(32)`, not the native `user_role` Postgres enum type**
(design D2, task 1.5's note): `Enum(UserRole, native_enum=False, length=32)` on the model
compiles to a bare `VARCHAR` with no `CHECK` constraint (confirmed by compiling the mapped
table's DDL before writing this migration) — reusing the native type across a second table
is complexity this design does not ask for.

**No `updated_at` on either table, and no `server_default` on `created_at`**, for the same
reason `incident_photos` gives: both rows are immutable after insert (`add`/`list_for_...`,
no `save`), and Postgres `now()` is the *transaction* timestamp, so a burst of messages
inserted together would collapse the chronological order the thread is read in. The use
case supplies the real write time.

Revision ID: 3488de4c4f49
Revises: 2b28c6b3f82a
Create Date: 2026-09-02 17:38:51.210642

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3488de4c4f49'
down_revision: Union[str, Sequence[str], None] = '2b28c6b3f82a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The pair `cleaning_task_messages`'s composite foreign key needs. `incidents` already
    # carries its own equivalent (`uq_incidents_tenant_id_id`, from `incident_photos`).
    op.create_unique_constraint(
        'uq_cleaning_tasks_tenant_id_id', 'cleaning_tasks', ['tenant_id', 'id']
    )

    op.create_table(
        'cleaning_task_messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('author_id', sa.Uuid(), nullable=False),
        sa.Column('author_role', sa.String(length=32), nullable=False),
        sa.Column('content', sa.String(length=2000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        # The invariant: the message's tenant and its task's tenant cannot diverge.
        sa.ForeignKeyConstraint(
            ['tenant_id', 'task_id'],
            ['cleaning_tasks.tenant_id', 'cleaning_tasks.id'],
            name='fk_cleaning_task_messages_task_within_tenant',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='RESTRICT'),
    )
    # `TenantScopedMixin` declares `tenant_id` with `index=True`, so the model expects this.
    op.create_index(
        op.f('ix_cleaning_task_messages_tenant_id'),
        'cleaning_task_messages',
        ['tenant_id'],
        unique=False,
    )
    op.create_index(
        'ix_cleaning_task_messages_tenant_id_task_id',
        'cleaning_task_messages',
        ['tenant_id', 'task_id'],
        unique=False,
    )

    op.create_table(
        'incident_messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('incident_id', sa.Uuid(), nullable=False),
        sa.Column('author_id', sa.Uuid(), nullable=False),
        sa.Column('author_role', sa.String(length=32), nullable=False),
        sa.Column('content', sa.String(length=2000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        # The invariant: the message's tenant and its incident's tenant cannot diverge.
        sa.ForeignKeyConstraint(
            ['tenant_id', 'incident_id'],
            ['incidents.tenant_id', 'incidents.id'],
            name='fk_incident_messages_incident_within_tenant',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='RESTRICT'),
    )
    op.create_index(
        op.f('ix_incident_messages_tenant_id'),
        'incident_messages',
        ['tenant_id'],
        unique=False,
    )
    op.create_index(
        'ix_incident_messages_tenant_id_incident_id',
        'incident_messages',
        ['tenant_id', 'incident_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_incident_messages_tenant_id_incident_id', table_name='incident_messages')
    op.drop_index(op.f('ix_incident_messages_tenant_id'), table_name='incident_messages')
    op.drop_table('incident_messages')

    op.drop_index('ix_cleaning_task_messages_tenant_id_task_id', table_name='cleaning_task_messages')
    op.drop_index(op.f('ix_cleaning_task_messages_tenant_id'), table_name='cleaning_task_messages')
    op.drop_table('cleaning_task_messages')

    # Last, because the composite foreign key above depended on it.
    op.drop_constraint('uq_cleaning_tasks_tenant_id_id', 'cleaning_tasks', type_='unique')
