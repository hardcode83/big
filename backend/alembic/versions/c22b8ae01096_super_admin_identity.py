"""super_admin_identity: users.tenant_id and user_sessions.tenant_id become nullable

`SUPER_ADMIN` is a platform identity, not a tenant's — R1 requires the schema to admit an
account, and a session for it, with no `tenant_id` at all (`super-admin-identity` design D1).

**No backfill.** Every existing row already has a concrete `tenant_id` (R1.3): relaxing a
`NOT NULL` constraint on Postgres 16 is a metadata-only change and does not rewrite the
table, so this is safe on populated data without a data migration step.

**`downgrade()` refuses to reinstate `NOT NULL` over data that already violates it (R1.4).**
Once a `SUPER_ADMIN` account exists, its row's `tenant_id IS NULL` — and any `user_sessions`
row a `SUPER_ADMIN` login created is `NULL` too. Reintroducing the constraint blind would fail
at the `ALTER TABLE` with an opaque "column contains null values" from Postgres, or — worse,
if the deployment happened to have none of those rows at that exact moment — would silently
succeed and only fail the NEXT insert. Both tables are checked, by name, before either column
is touched.

**`ck_users_super_admin_tenant_id_null` closes a gap the review panel found (R1.2).** Relaxing
`users.tenant_id` to nullable relaxes it for every role's row, not only `SUPER_ADMIN`'s — R1.2
requires the other four roles to keep a concrete tenant, and nothing at the schema level held
that pairing without this constraint. A `TENANT_OWNER`/`PROPERTY_MANAGER`/`CLEANER`/`TECHNICIAN`
row that ever acquired `tenant_id IS NULL` (a bad migration, a manual edit, a future bug) would
authenticate with the session left unmarked by `get_authenticated_request` — the same unmarked
state R3 scopes to `SUPER_ADMIN` only — while still holding that role's full operational
permissions, since the session-marking decision keys on `tenant_id` nullity, not on `role`.
`(role = 'SUPER_ADMIN') = (tenant_id IS NULL)` makes the pairing a database invariant instead of
an unenforced comment, mirroring the existing precedent
`ck_pms_credentials_property_id_matches_scope`
(`c3f81a5d7e42_pms_provider_resolution.py`). Scoped to `users` only: `user_sessions` carries no
`role` column of its own to check against.

Revision ID: c22b8ae01096
Revises: e5c9b1f47a28
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c22b8ae01096'
down_revision: Union[str, Sequence[str], None] = 'e5c9b1f47a28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('users', 'user_sessions')


_SUPER_ADMIN_TENANT_ID_CHECK = "ck_users_super_admin_tenant_id_null"


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        op.alter_column(table, 'tenant_id', existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        _SUPER_ADMIN_TENANT_ID_CHECK,
        'users',
        "(role = 'SUPER_ADMIN') = (tenant_id IS NULL)",
    )


def downgrade() -> None:
    """Downgrade schema.

    Raises instead of altering the column back to `NOT NULL` if either table still has a
    row with `tenant_id IS NULL` — that row would violate the constraint the moment it is
    reinstated, and PostgreSQL's own error for it names the column, not the reason.
    """
    bind = op.get_bind()
    offending = []
    for table in _TABLES:
        count = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL")
        ).scalar_one()
        if count:
            offending.append(f"{table} ({count} row(s))")

    if offending:
        raise RuntimeError(
            "Cannot downgrade c22b8ae01096: tenant_id IS NULL rows still exist in "
            + ", ".join(offending)
            + " — reinstating NOT NULL would corrupt data that already violates it. "
            "Remove or reassign those rows (e.g. deactivate/delete the SUPER_ADMIN "
            "account and its sessions) before downgrading."
        )

    op.drop_constraint(_SUPER_ADMIN_TENANT_ID_CHECK, 'users', type_='check')
    for table in _TABLES:
        op.alter_column(table, 'tenant_id', existing_type=sa.Uuid(), nullable=False)
