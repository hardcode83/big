"""whatsapp cloud adapter: the phone_number_id-to-tenant association (section 6)

Creates `whatsapp_phone_numbers` (`whatsapp-cloud-adapter` R6.1-R6.3, design D3/D8).

**Rewritten mid-run, and this table is the rewrite's whole footprint**: Meta admits one
App/WABA for the whole platform (built in section 1 with the global `WHATSAPP_ACCESS_TOKEN`/
`WHATSAPP_APP_SECRET`), and every tenant brings its own `phone_number_id` under that App. So
there is no per-tenant secret to mint — this table holds only the association, with no
encrypted column, unlike `webhook_endpoints` (`a4d17e83b6c1`).

One row per tenant (`uq_whatsapp_phone_numbers_tenant_id`). `phone_number_id` is globally
unique (`ix_whatsapp_phone_numbers_phone_number_id`, `index=True, unique=True` rather than a
bare `UniqueConstraint`, for the same `alembic check` reason `webhook_endpoints.token_hash`
is spelled that way) — it is the column section 7's inbound webhook resolves the tenant FROM,
with no tenant in hand yet, so global uniqueness is what makes "at most one tenant" a schema
guarantee rather than an assumption of the caller (R6.2).

`default_property_id` is `NOT NULL` (design D8 addendum, 2026-09-02): `Conversation
.property_id` can never be `None` (`guest-portal-messaging` D19), so `ConversationRepository
.ensure_whatsapp` needs somewhere to anchor a thread whose sender resolves to no stay.
`ondelete="RESTRICT"` against `properties.id`, same as `conversations.property_id`.

Declared a second time in `WhatsAppPhoneNumberModel` (`app/messaging/infrastructure/
models.py`): the test suite builds its schema via `Base.metadata.create_all` and never runs
these migrations (`sdd/steering/testing.md`), same precedent as `f1a9c73e5b28` and
`b282614d54b4`. `alembic upgrade head` was not run for the same reason.

Revision ID: c25fc5f449c1
Revises: f1a9c73e5b28
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c25fc5f449c1'
down_revision: Union[str, Sequence[str], None] = 'f1a9c73e5b28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'whatsapp_phone_numbers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('phone_number_id', sa.String(length=32), nullable=False),
        sa.Column('display_phone_number', sa.String(length=32), nullable=True),
        sa.Column('default_property_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['default_property_id'], ['properties.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', name='uq_whatsapp_phone_numbers_tenant_id'),
    )
    op.create_index(
        op.f('ix_whatsapp_phone_numbers_tenant_id'), 'whatsapp_phone_numbers', ['tenant_id'], unique=False
    )
    # Globally unique, not per tenant: section 7's inbound webhook queries this column with no
    # tenant in hand, because the number is what resolves the tenant.
    op.create_index(
        op.f('ix_whatsapp_phone_numbers_phone_number_id'),
        'whatsapp_phone_numbers',
        ['phone_number_id'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('whatsapp_phone_numbers')
