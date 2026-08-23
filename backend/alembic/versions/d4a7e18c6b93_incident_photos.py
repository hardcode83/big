"""incident_photos: the second consumer of the shared object storage

Creates the `incident_photo_stage` enum type and the `incident_photos` table, and adds
`uq_incidents_tenant_id_id` to `incidents` (change `incident-photos`, design D2/D3, R1).

**Two tables, and the one on `incidents` is what needs explaining.** `incident_photos` carries
its own `tenant_id` (R1.3) *and* references its incident through a COMPOSITE foreign key on
`(tenant_id, incident_id)`. Postgres requires the referenced pair to be a declared unique key,
which `incidents` did not have — hence the `UNIQUE (tenant_id, id)` added here. With two
independent single-column foreign keys instead, a row pairing tenant A with an incident of
tenant B is perfectly legal and only the repository stands between that and the database; the
review panels of `guest-portal-api` reproduced exactly that row for its own case, which is why
this change buys the invariant in the schema. Precedent, down to the constraint name shape:
`uq_reservations_tenant_id_id`, which exists so `guest_access_tokens` can point at it.

**The `UNIQUE` cannot fail on existing data.** `incidents.id` is already the primary key, so
`(tenant_id, id)` is unique for free — this index can never find a duplicate, whatever is in the
table. In dev the table is nearly empty and it is instantaneous; on a populated database it is a
`CREATE UNIQUE INDEX` over a pair whose uniqueness is already guaranteed.

**No `updated_at` on `incident_photos`**, deliberately, and it is a conscious deviation from
`steering/backend.md`'s "toda entidad con `tenant_id`, `created_at`, `updated_at`": the row is
immutable after insert (the port declares `add` and `list_for_incident`, no `save`), so the
column could only ever equal `created_at` and would invite a reader to trust it as evidence of
an edit that cannot happen. `cleaning_photos` omits it for the same reason.

**No `server_default` on `created_at`**, which is where this table is stricter than
`cleaning_photos`. Postgres `now()` is the *transaction* timestamp, so a burst of photos
inserted together would share one instant and the listing's ordering would fall through to a
random `uuid4`. The use case supplies the real upload time (R3.1).

**No `UNIQUE (incident_id, stage)`**: R1.4 requires several photos of the same stage — a
technician photographs two angles of one fault.

Revision ID: d4a7e18c6b93
Revises: c8e1f4a92b70
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4a7e18c6b93'
# Renumbered onto `tech-cycle-completion`, which landed first and also migrates `incidents`
# (it adds `eta_at`/`materials`; this revision creates `incident_photos` and the
# `UNIQUE (tenant_id, id)` the composite foreign key needs). No DDL overlap, so the rebase was
# a pointer change: the repository keeps a strictly linear chain and `alembic upgrade head` —
# which is what CI runs — refuses two heads.
down_revision: Union[str, None] = 'c8e1f4a92b70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The pair the composite foreign key below has to reference. Added before the table that
    # needs it, or the FK creation fails.
    op.create_unique_constraint(
        'uq_incidents_tenant_id_id', 'incidents', ['tenant_id', 'id']
    )

    # The ENUM type is created implicitly by `create_table` below, which is this repository's
    # established pattern (see `a1a72da30f8e_domain_foundation_ops.py` and the other three
    # baseline revisions): plain `sa.Enum(...)` in the column, and an explicit
    # `postgresql.ENUM(name=...).drop(...)` in `downgrade`, because dropping a table does NOT
    # drop the type it used.
    #
    # An earlier draft of this revision created the type explicitly first and passed
    # `create_type=False` in the column. That silently does nothing: `create_type` is a kwarg of
    # `postgresql.ENUM`, not of generic `sa.Enum`, so the type was created twice in one
    # transaction and the migration failed with `DuplicateObjectError`. Recorded because the
    # broken version reads as correct.
    op.create_table(
        'incident_photos',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('incident_id', sa.Uuid(), nullable=False),
        sa.Column('uploaded_by', sa.Uuid(), nullable=False),
        sa.Column(
            'stage',
            sa.Enum('BEFORE', 'AFTER', name='incident_photo_stage'),
            nullable=False,
        ),
        sa.Column('storage_key', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        # The invariant: the photo's tenant and its incident's tenant cannot diverge.
        sa.ForeignKeyConstraint(
            ['tenant_id', 'incident_id'],
            ['incidents.tenant_id', 'incidents.id'],
            name='fk_incident_photos_incident_within_tenant',
            ondelete='RESTRICT',
        ),
        # RESTRICT, not SET NULL: the column is NOT NULL, and a photo is a record of who did
        # the work.
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='RESTRICT'),
    )
    # `TenantScopedMixin` declares `tenant_id` with `index=True`, so the model expects this.
    op.create_index(
        op.f('ix_incident_photos_tenant_id'), 'incident_photos', ['tenant_id'], unique=False
    )
    op.create_index(
        'ix_incident_photos_tenant_id_incident_id',
        'incident_photos',
        ['tenant_id', 'incident_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_incident_photos_tenant_id_incident_id', table_name='incident_photos')
    op.drop_index(op.f('ix_incident_photos_tenant_id'), table_name='incident_photos')
    op.drop_table('incident_photos')
    # Dropping the table does not drop its ENUM type, so the next upgrade would fail with
    # "type already exists". Same call the four baseline revisions use.
    postgresql.ENUM(name='incident_photo_stage').drop(op.get_bind(), checkfirst=True)
    # Last, because the composite foreign key above depended on it.
    op.drop_constraint('uq_incidents_tenant_id_id', 'incidents', type_='unique')
