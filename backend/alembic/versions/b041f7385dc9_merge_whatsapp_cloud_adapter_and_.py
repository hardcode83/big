"""merge whatsapp_cloud_adapter and platform_admin_api_staff_messaging

Revision ID: b041f7385dc9
Revises: 4ba1f499f7c2, d38ba71c04e9
Create Date: 2026-09-03 23:16:09.022586

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b041f7385dc9'
down_revision: Union[str, Sequence[str], None] = ('4ba1f499f7c2', 'd38ba71c04e9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
