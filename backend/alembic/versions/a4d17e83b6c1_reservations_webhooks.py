"""reservations webhooks: per-tenant endpoint material and a durable retry queue

Creates `webhook_endpoints` (rule 12(a)/(b) of `steering/security.md`, design D2) and adds
`webhook_events.attempts` / `webhook_events.next_attempt_at` (design D9).

**Additive, and safe for a reason worth naming rather than assuming: `webhook_events` was empty
in every environment when this migration was applied.** Nothing had written to it between
`domain-foundation-financial`, which created the table, and this change, which brings its first
writer — so the two new columns land on no existing rows and their `server_default` is never
actually exercised by the backfill. It is still declared, because the default is what makes the
column meaningful for every row inserted *afterwards* by a statement that does not mention it.
(Stated as the fact it is. This used to cite the model's docstring as evidence, which was the
wrong kind of support twice over: a docstring is not a record of what was in the table, and that
one no longer says it.)

**The two new columns are a deliberate deviation from PRD §7.26**, recorded in design D9 and left
open for ratification in the change's `BLOCKED.md`. They add retry accounting the PRD's entity
does not declare, and change the meaning of nothing it does.

**`header_secret_encrypted` holds Fernet ciphertext from this migration onwards**, the same
contract `c3f81a5d7e42` established for `pms_credentials.secret_encrypted`: R2.2 admits no
intermediate schema version in which the column accepts plaintext.

**No enum type is created here, and that is the interesting half of the reversibility story.**
`webhook_endpoints.provider` reuses the `pms_provider` type that `c3f81a5d7e42` already created,
so this migration must NOT create it — and, more importantly, must not drop it on the way back:
`pms_credentials` and `properties.pms_provider` still use it. Dropping a shared type is how a
`downgrade` succeeds and the next `upgrade` fails with "type does not exist". CI runs
`alembic check` and `alembic downgrade base`, so getting this wrong is a red build.

Revision ID: a4d17e83b6c1
Revises: f2b9c7a41d38
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a4d17e83b6c1'
down_revision: Union[str, Sequence[str], None] = 'f2b9c7a41d38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `create_type=False`: the type already exists, owned by `c3f81a5d7e42`. This migration is a
# consumer of it, not its author, which is exactly why `downgrade` leaves it alone.
_PMS_PROVIDER = postgresql.ENUM(
    'MOCK', 'CHANNEX', 'BEDS24', name='pms_provider', create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'webhook_endpoints',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('provider', _PMS_PROVIDER, nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('header_name', sa.String(length=100), nullable=False),
        sa.Column('header_secret_encrypted', sa.Text(), nullable=False),
        sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'provider', name='uq_webhook_endpoints_tenant_provider'),
    )
    op.create_index(op.f('ix_webhook_endpoints_tenant_id'), 'webhook_endpoints', ['tenant_id'], unique=False)
    # Globally unique, not per tenant: the receiving path queries this column with no tenant in
    # hand, because the token is what resolves the tenant. Uniqueness across the whole table is
    # what makes "exactly one row" a schema guarantee.
    op.create_index(op.f('ix_webhook_endpoints_token_hash'), 'webhook_endpoints', ['token_hash'], unique=True)

    op.add_column('webhook_events', sa.Column('attempts', sa.SmallInteger(), server_default='0', nullable=False))
    op.add_column('webhook_events', sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('webhook_events', 'next_attempt_at')
    op.drop_column('webhook_events', 'attempts')
    op.drop_index(op.f('ix_webhook_endpoints_token_hash'), table_name='webhook_endpoints')
    op.drop_index(op.f('ix_webhook_endpoints_tenant_id'), table_name='webhook_endpoints')
    op.drop_table('webhook_endpoints')
    # `pms_provider` is deliberately NOT dropped: `pms_credentials.provider` and
    # `properties.pms_provider` still reference it, and this migration did not create it.
