"""guests phone index

`ix_guests_tenant_id_phone` (`whatsapp-cloud-adapter` design D5, R4.2/R4.4): the webhook
handler looks up a guest by phone, scoped to the tenant the route token already resolved
(`GuestRepository.find_by_phone`). Same shape as the existing `ix_guests_tenant_id_email`
(added by the baseline migration) — a plain, non-unique per-tenant index, since more than
one guest legitimately sharing a phone is exactly the signal `find_by_phone` returns a list
for rather than a single row.

The same index is declared a second time, in `GuestModel.__table_args__`
(`app/guests/infrastructure/models.py`): the test suite builds its schema via
`Base.metadata.create_all` and never runs these migrations (`sdd/steering/testing.md`), so
without that second declaration the index would not exist under test. Same precedent as
`uq_conversations_portal_reservation` / `ix_incident_photos_tenant_id_incident_id`.

Revision ID: b282614d54b4
Revises: 2b28c6b3f82a
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b282614d54b4'
down_revision: Union[str, Sequence[str], None] = '2b28c6b3f82a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'ix_guests_tenant_id_phone', 'guests', ['tenant_id', 'phone'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_guests_tenant_id_phone', table_name='guests')
