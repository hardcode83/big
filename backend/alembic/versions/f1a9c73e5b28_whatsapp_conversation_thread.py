"""whatsapp cloud adapter: the business number a thread was opened on, and one thread per guest+property

Two statements, one revision (`whatsapp-cloud-adapter` R4.5, design D4):

- `conversations.business_phone_number` — Meta's `phone_number_id` for the tenant's own
  number, the one the guest wrote **to**. Nullable, and it stays nullable: it means nothing on
  a `PORTAL`, `EMAIL`, `MANUAL` or `PHONE_TRANSCRIPT` row, and `Conversation.__post_init__`
  refuses a value on any channel but `WHATSAPP` rather than a CHECK doing it — the same
  division of labour D19 of `guest-portal-messaging` chose for `property_id`. `VARCHAR(32)`
  because a Graph API phone number id is a digit string of about 15 characters; it is an
  identifier, not a dialable number.

- `uq_conversations_whatsapp_guest_property` — R4.5. At most one `WHATSAPP` conversation per
  guest **and property**, which is what `ConversationRepository.ensure_whatsapp`'s
  `INSERT ... ON CONFLICT DO NOTHING` infers. Per property and not per guest for life
  (confirmed with the user, D4): a message about property B must not surface property A's
  unrelated history. Not keyed on `reservation_id` like its `PORTAL` sibling, because on the
  inbound path the reservation is frequently unknown (R4.3, R4.4) while the thread must exist
  anyway.

  `guest_id` and `property_id` are nullable, and PostgreSQL treats NULLs as distinct in a
  unique index, so the unresolved rows of R4.3 do not dedupe against each other — an
  unresolved sender opens a new row per message. Accepted in D4 and in the design's Risks
  rather than adding a second index shape for it; if it turns out common, a follow-up can key
  the unresolved case on `guest_id` alone.

No `autocommit_block` here, unlike `2b28c6b3f82a`: that revision had to add a *new* label to
`conversation_channel` before using it in an index predicate. `WHATSAPP` is an original label
of that type, so the predicate below needs nothing but the type as it already exists.

Both objects are declared a second time in `ConversationModel` (`app/messaging/
infrastructure/models.py`): the test suite builds its schema via `Base.metadata.create_all`
and never runs these migrations (`sdd/steering/testing.md`), so without that second
declaration neither the column nor the index would exist under test — and the concurrency
guarantee `ensure_whatsapp` rests on would prove nothing while still passing. Same precedent
as `uq_conversations_portal_reservation` and `ix_guests_tenant_id_phone`.

Revision ID: f1a9c73e5b28
Revises: b282614d54b4
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a9c73e5b28'
down_revision: Union[str, Sequence[str], None] = 'b282614d54b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WHATSAPP = 'WHATSAPP'
WHATSAPP_INDEX = 'uq_conversations_whatsapp_guest_property'


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'conversations',
        sa.Column('business_phone_number', sa.String(length=32), nullable=True),
    )
    op.create_index(
        WHATSAPP_INDEX,
        'conversations',
        ['tenant_id', 'guest_id', 'property_id'],
        unique=True,
        postgresql_where=sa.text(f"channel = '{WHATSAPP}'"),
    )


def downgrade() -> None:
    """Downgrade schema.

    Both objects are this revision's own, so both go — unlike `2b28c6b3f82a`, which had to
    leave an enum label behind.
    """
    op.drop_index(WHATSAPP_INDEX, table_name='conversations')
    op.drop_column('conversations', 'business_phone_number')
