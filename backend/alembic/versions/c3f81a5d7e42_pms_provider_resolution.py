"""pms provider resolution: per-property provider and encrypted credentials

Creates `pms_credentials` and adds `properties.pms_provider` (ADR 0006 decision 7).

**No data migration, and that is a property worth stating rather than an omission.** Both
columns are born empty and `properties.pms_provider` is nullable, meaning "the bootstrap
default" — so no existing row needs rewriting and nothing has to be re-encrypted. That will not
be true again: once a credential is stored, changing `ENCRYPTION_KEY` orphans it, and this repo
has no precedent for a migration that transforms existing rows.

**`secret_encrypted` holds Fernet ciphertext from this migration onwards.** R3.1 admits no
intermediate schema version in which it accepts plaintext, which is why the column arrives with
the encryption primitive already in place rather than "to be encrypted later" — the mistake
`domain-foundation-core` made deliberately for `wifi_password_encrypted` and that this change
does not repeat for credentials.

**Reversible, and verified both ways.** Two enum types are created explicitly here, which
autogenerate would NOT have done for `properties.pms_provider`: a type is created as a side
effect of the first `CREATE TABLE` that references it, and an `ADD COLUMN` is not one. They are
dropped explicitly in `downgrade` for the same reason the four earlier migrations do it —
Postgres keeps a native enum type after its table is gone, so a later `upgrade` would fail with
"type already exists". CI runs `alembic check` and `alembic downgrade base`, so a leaked type is
a red build, not a latent mess.

Revision ID: c3f81a5d7e42
Revises: b7c41d92e5a3
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3f81a5d7e42'
down_revision: Union[str, Sequence[str], None] = 'b7c41d92e5a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Created by hand below and dropped by hand on the way back. `pms_provider` is used by TWO
# tables, so it must outlive `pms_credentials` in `downgrade` until the column on `properties`
# is gone as well — the order in `downgrade` is not cosmetic.
_ENUM_TYPE_NAMES = ["pms_provider", "pms_credential_scope"]

_PMS_PROVIDER = postgresql.ENUM(
    'MOCK', 'CHANNEX', 'BEDS24', name='pms_provider', create_type=False
)
_PMS_CREDENTIAL_SCOPE = postgresql.ENUM(
    'PROPERTY', 'ACCOUNT', 'ORGANIZATION', name='pms_credential_scope', create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    # Explicitly, and before anything references them: `op.add_column` never creates a type.
    _PMS_PROVIDER.create(bind, checkfirst=True)
    _PMS_CREDENTIAL_SCOPE.create(bind, checkfirst=True)

    op.create_table(
        'pms_credentials',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('provider', _PMS_PROVIDER, nullable=False),
        sa.Column('scope', _PMS_CREDENTIAL_SCOPE, nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=True),
        sa.Column('secret_encrypted', sa.Text(), nullable=False),
        sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'provider', 'scope', 'property_id', name='uq_pms_credentials_tenant_provider_scope_property'),
        # Added before any row exists, which is the only cheap moment: `property_id` is set
        # exactly when the scope is PROPERTY. Without it an ACCOUNT row carrying a property id
        # escapes the partial unique index below and survives rotation forever.
        sa.CheckConstraint("(scope = 'PROPERTY') = (property_id IS NOT NULL)", name='ck_pms_credentials_property_id_matches_scope'),
    )
    op.create_index(op.f('ix_pms_credentials_tenant_id'), 'pms_credentials', ['tenant_id'], unique=False)
    # Partial, and it is what actually enforces "at most one account credential per provider":
    # Postgres treats NULLs as distinct in a UNIQUE constraint, so the constraint above does not
    # constrain the rows whose `property_id` is NULL — which is every account- and
    # organization-scoped credential, i.e. the dangerous ones.
    op.create_index(
        'uq_pms_credentials_account_scope',
        'pms_credentials',
        ['tenant_id', 'provider', 'scope'],
        unique=True,
        postgresql_where=sa.text('property_id IS NULL'),
    )

    op.add_column('properties', sa.Column('pms_provider', _PMS_PROVIDER, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('properties', 'pms_provider')
    op.drop_index('uq_pms_credentials_account_scope', table_name='pms_credentials')
    op.drop_index(op.f('ix_pms_credentials_tenant_id'), table_name='pms_credentials')
    op.drop_table('pms_credentials')
    # After both users are gone, never before.
    for type_name in _ENUM_TYPE_NAMES:
        postgresql.ENUM(name=type_name).drop(op.get_bind(), checkfirst=True)
