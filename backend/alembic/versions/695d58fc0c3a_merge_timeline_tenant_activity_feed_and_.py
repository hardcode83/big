"""merge timeline tenant activity feed and whatsapp cloud adapter platform admin merge

Revision ID: 695d58fc0c3a
Revises: b041f7385dc9, ecc25b9ad299
Create Date: 2026-09-04 08:08:10.161660

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '695d58fc0c3a'
down_revision: Union[str, Sequence[str], None] = ('b041f7385dc9', 'ecc25b9ad299')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
