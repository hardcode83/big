"""merge platform admin api staff messaging

This is the SECOND merge revision whose lineage passes through
`c22b8ae01096` + `r3v1ew5a03`, and that is not a mistake: `platform-admin-api`
and `main` each merged those two parallel heads independently while the branch
was open (`936fef59b1d4` here, `a1b2c3d4e5f6` on `main`). Merging the base back
in therefore left two heads — `3488de4c4f49` (staff-messaging, via `main`) and
`936fef5a01b1` (`uq_tenants_name`, this change) — and `alembic upgrade head`
refuses to run with more than one. This revision joins them so the `migrate`
container of `docker-compose.deploy.yml` has a single target again. It carries
no schema operation: both branches were already applied on their own side.

Revision ID: 4ba1f499f7c2
Revises: 3488de4c4f49, 936fef5a01b1
Create Date: 2026-09-03 16:25:48.606372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ba1f499f7c2'
down_revision: Union[str, Sequence[str], None] = ('3488de4c4f49', '936fef5a01b1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
