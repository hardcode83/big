"""whatsapp cloud adapter: the inbound delivery queue (section 7)

Creates `whatsapp_inbound_events` (`whatsapp-cloud-adapter` R3.3, R3.4, R3.5, design D7).

The row that survives the queue boundary between the anonymous receiving route and the
`process_inbound_whatsapp_message` task it dispatches. Its sibling is `webhook_events`
(`a4d17e83b6c1`), one provider over, and it borrows that table's one unusual property:
**`tenant_id` is nullable**. R3.3 as amended on 2026-09-02 splits two outcomes that would
otherwise look alike — a delivery whose signature does not verify writes nothing at all,
while a validly signed delivery for a `phone_number_id` no tenant has provisioned is an
operator's unfinished setup and is recorded rather than dropped (R4.3's criterion). With no
tenant resolved there is no `tenant_id` to write, and R4.1 forbids inventing one.

`default_property_id` is nullable in lockstep with `tenant_id` — both come from the same
`whatsapp_phone_numbers` row, so a row has either both or neither, enforced by
`InboundWhatsAppEvent.__post_init__` rather than by a CHECK, the same way the rest of this
module's invariants live in the entity.

The unique index on `provider_message_id` is R3.5 as a schema guarantee rather than a caller's
promise: Meta redelivers on any non-2xx, and a redelivery must not become a second message in
the guest's thread. `unique=True` on the index (rather than a `UniqueConstraint`) for the same
`alembic check` reason `ix_whatsapp_phone_numbers_phone_number_id` is spelled that way.

Declared a second time in `WhatsAppInboundEventModel` (`app/messaging/infrastructure/
models.py`): the test suite builds its schema via `Base.metadata.create_all` and never runs
these migrations (`sdd/steering/testing.md`), same precedent as `c25fc5f449c1`. `alembic
upgrade head` was not run for the same reason.

Revision ID: d38ba71c04e9
Revises: c25fc5f449c1
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd38ba71c04e9'
down_revision: Union[str, Sequence[str], None] = 'c25fc5f449c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'whatsapp_inbound_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=True),
        sa.Column('default_property_id', sa.Uuid(), nullable=True),
        sa.Column('phone_number_id', sa.String(length=32), nullable=False),
        sa.Column('provider_message_id', sa.String(length=128), nullable=False),
        sa.Column('sender_phone', sa.String(length=32), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['default_property_id'], ['properties.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_whatsapp_inbound_events_tenant_id'),
        'whatsapp_inbound_events',
        ['tenant_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_whatsapp_inbound_events_phone_number_id'),
        'whatsapp_inbound_events',
        ['phone_number_id'],
        unique=False,
    )
    # R3.5: one row per provider message id, across the whole platform. The receiver's
    # `INSERT ... ON CONFLICT DO NOTHING` is keyed on exactly this index.
    op.create_index(
        op.f('ix_whatsapp_inbound_events_provider_message_id'),
        'whatsapp_inbound_events',
        ['provider_message_id'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('whatsapp_inbound_events')
