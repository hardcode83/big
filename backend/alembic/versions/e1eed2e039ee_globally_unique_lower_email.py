"""globally unique lower(email): email becomes the login identity

PRD §7.3 specifies UNIQUE(tenant_id, email). With login by email only and no tenant
discriminator that is not enough to identify an account: an admin of tenant B who
knows the address of tenant A's owner could create a user with it, and in a product
with no public sign-up and no unlock endpoint that owner is locked out for good.
Decision taken on PR #25 review (ADR 0005): the normalised email is unique across
the whole installation, guaranteed by the database rather than by application code,
compared case-insensitively. A single identity belonging to several tenants will be
modelled later as a global identity plus memberships, never as a repeated address.

Replaces the per-tenant constraint instead of adding to it: two constraints for one
rule drift apart, and global uniqueness already implies the per-tenant one.

`lower(email)` rather than `email`: `uq_users_tenant_id_email` was case-sensitive, so
`Jose@x.com` and `jose@x.com` could coexist while the login lookup treats them as the
same address (design D19).

NOT reversible without data loss risk: `downgrade` restores per-tenant uniqueness,
which is a WEAKER constraint, so it always succeeds — but re-upgrading afterwards
fails if duplicate addresses were created while it was down. If `upgrade` fails on an
existing database, two tenants already share an address; resolve it by hand first
(RUNBOOK §6.4 has the query).

Revision ID: e1eed2e039ee
Revises: 8ff62a7cb50c
Create Date: 2026-07-30 07:22:22.460047

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1eed2e039ee'
down_revision: Union[str, Sequence[str], None] = '8ff62a7cb50c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'uq_users_lower_email', 'users', [sa.literal_column('lower(email)')], unique=True
    )
    # Dropped only after the stronger index exists, so no window without uniqueness.
    op.drop_constraint('uq_users_tenant_id_email', 'users', type_='unique')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_unique_constraint('uq_users_tenant_id_email', 'users', ['tenant_id', 'email'])
    op.drop_index('uq_users_lower_email', table_name='users')
