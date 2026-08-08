"""cleaning: one live cleaning task per reservation

`cleaning` R2.5 asks that a second run of `process_checkouts` over the same reservation
not create a second task. The job runs every five minutes under a Redis lock, so the
read-then-write check in `ProvisionCleaningTaskUseCase` is the fast path, not the
guarantee — this partial unique index is.

Partial on purpose, and both halves of the predicate carry weight:

- `reservation_id IS NOT NULL` — a manual task created without a booking (PRD §23's
  `POST /cleaning-tasks`) has nothing to be unique against.
- the status list — a `REJECTED` task must be able to coexist with the replacement its
  rejection creates (design D3), and a `COMPLETED` one with a later cleaning of the same
  booking. The set is the same as `LIVE_STATUSES` in
  `app/cleaning/domain/entities.py`, and `tests/cleaning/test_live_task_index.py` pins
  them together by parsing this predicate out of the model rather than retyping it.

`PENDING_REVIEW` is **not** in the list, and that is the point of agreement with
`ContextualStateResolver` (`app/properties/domain/state_resolution.py:143-147`), which
does not treat it as pending cleaning either. Including it would let a task block the
creation of its successor while the property reports having no cleaning pending.

Reversible: dropping the index is always safe, and re-upgrading only fails if duplicate
live tasks were created while it was down.

Revision ID: d4b0c7a91f38
Revises: c3f81a5d7e42
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b0c7a91f38'
down_revision: Union[str, Sequence[str], None] = 'c3f81a5d7e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'uq_cleaning_tasks_live_reservation',
        'cleaning_tasks',
        ['tenant_id', 'reservation_id'],
        unique=True,
        postgresql_where=sa.text(
            "reservation_id IS NOT NULL AND status IN "
            "('CREATED', 'ASSIGNED', 'ACCEPTED', 'IN_PROGRESS')"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_cleaning_tasks_live_reservation', table_name='cleaning_tasks')
