"""merge platform-admin-api pre-revision

Revision ID: 936fef59b1d4
Revises: c22b8ae01096, r3v1ew5a03
Create Date: 2026-09-02 15:57:59.743448

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '936fef59b1d4'
down_revision: Union[str, Sequence[str], None] = ('c22b8ae01096', 'r3v1ew5a03')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
