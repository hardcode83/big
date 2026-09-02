"""guest portal messaging: the `PORTAL` channel and one portal thread per stay

Two statements, one revision (`guest-portal-messaging` design D6, D7):

- `conversation_channel.PORTAL` — R3.1. The guest's own browser on `/guest/[token]` is a
  channel of its own and not `MANUAL`: on `MANUAL` the row is the delivery *for an operator
  watching the panel*, and here the reader is the guest. `IF NOT EXISTS` on the label so
  re-running against a database where a previous attempt half-applied is not an error.
- `uq_conversations_portal_reservation` — R3.4. At most one `PORTAL` conversation per stay,
  so two simultaneous messages from the same guest cannot open two threads.
  `ConversationRepository.ensure_portal` does `INSERT … ON CONFLICT DO NOTHING` and then
  `SELECT`; this index is what that conflict names. Partial on `(tenant_id, reservation_id)`
  and not unique on `(tenant_id, reservation_id, channel)`, which would forbid two `MANUAL`
  threads for one stay — legal today.

**This is the first revision of the project that has to USE the enum label it just added, and
that is what forces the autocommit block.** `b7c41d92e5a3`, `e7a3c419d82b` and `c8e1f4a92b70`
each worked out that on PostgreSQL 12+ the restriction is on *using* a new label inside the
transaction that adds it, not on adding it — and all three could stop there, because none of
them used it. This one needs it in an index predicate. Both routes without an autocommit block
were measured against the real database on 2026-08-29, and both fail:

- `WHERE channel = 'PORTAL'` in the same transaction as the `ALTER TYPE`:
  `ERROR: unsafe use of new value "PORTAL" of enum type conversation_channel`,
  `HINT: New enum values must be committed before they can be used.`
- `WHERE channel::text = 'PORTAL'`, which D7 originally chose precisely to dodge that read:
  `ERROR: functions in index predicate must be marked IMMUTABLE`. The enum→text cast goes
  through `enum_out`, which is `STABLE` and not `IMMUTABLE` — a label can be renamed — and an
  index predicate admits only immutable functions. The cast is not expensive here; it is **not
  declarable at all**.

**So the `ALTER TYPE` runs inside `op.get_context().autocommit_block()`, and that costs
something real.** `alembic/env.py` wraps the whole run in one `context.begin_transaction()`, so
entering the block **commits every revision applied before it** and then runs the `ALTER TYPE`
outside any transaction. `alembic upgrade head` therefore stops being all-or-nothing from this
revision onwards: a failure in a later revision leaves everything up to and including this one
applied. `c8e1f4a92b70` priced that cost and avoided it; here there was nothing to avoid it
with. An operator whose upgrade dies mid-run must check which revisions actually landed rather
than assume the run rolled back.

What the block buys back: with the label committed, the predicate can be a plain enum
comparison, so the planner **can** use this index for a `WHERE channel = 'PORTAL'` — which the
`::text` form would have prevented.

**The same index is declared a second time**, in `ConversationModel.__table_args__`
(`app/messaging/infrastructure/models.py`), with the same predicate. The test suite builds its
schema with `create_all` from the metadata and never runs these migrations
(`sdd/steering/testing.md`), so without that second declaration the index would not exist in
the tests and the concurrency test of R3.4 would prove nothing while still passing. No
autocommit block is needed there: `create_all` **creates** the type rather than extending it,
and PostgreSQL 12+ allows using the labels of an enum created in the same transaction.
Precedent for the double declaration: `uq_cleaning_tasks_live_reservation`.

**The enum label is not removed on the way down, and `downgrade` says so rather than
pretending.** PostgreSQL cannot drop a value from an enum type; the only route is recreating
the type, rewriting every column that uses it and deciding what to do with rows already
carrying the value — a data decision this revision has no basis to make. An unused label costs
nothing, and `alembic downgrade base` (which CI runs) drops the whole type in the revision that
created it anyway. The index *is* dropped, and re-upgrading only fails if two portal threads
for one stay were created while it was down.

Revision ID: 80ea2e544b36
Revises: e5c9b1f47a28
Create Date: 2026-08-29 00:00:00.000000

**Re-encadenada al sincronizar la base (2026-08-31).** Nació colgando de `d4a7e18c6b93`, pero
`main` colgó de ese mismo padre `e5c9b1f47a28` (`notification_logs.read_at`) mientras esta rama
estaba en revisión, y dos cabezas rompen `tests/test_migrations.py`. Se re-encadenó ésta detrás de
aquélla; son ortogonales —`conversations` y el enum aquí, `notification_logs` allí— así que el
orden no cambia el resultado.

**Y por eso el `revision` cambió de `f3c7a2b81d54` a `80ea2e544b36` en la misma operación.** El panel de QA
del 2026-08-31 midió lo que pasa si se re-encadena conservando el id: una BD ya sellada con el id
viejo le parece a Alembic que está en cabeza, `upgrade head` **no hace nada** y se salta para
siempre el DDL de `e5c9b1f47a28` —la tabla se queda sin `read_at` ni sus dos índices y
`downgrade base` revienta con `UndefinedObjectError`—. Comprobado sobre la BD de dev de un
worktree, que quedó exactamente así.

Ese modo de fallo es **silencio**, y documentarlo no lo arregla para quien no lea esto. Con el id
nuevo, la misma BD falla **en alto** —`Can't locate revision identified by 'f3c7a2b81d54'`— y obliga a
recrearla, que es lo que hay que hacer: `make down` borrando volúmenes, `make up`,
`make bootstrap`, `make seed-demo`. Ni `main` ni `dev` se ven afectados en ninguno de los dos
casos: nunca tuvieron esta revisión sellada, y sobre BD limpia el ciclo completo pasa.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80ea2e544b36'
down_revision: Union[str, Sequence[str], None] = 'e5c9b1f47a28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONVERSATION_CHANNEL_ENUM = 'conversation_channel'
PORTAL = 'PORTAL'
PORTAL_INDEX = 'uq_conversations_portal_reservation'


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE {CONVERSATION_CHANNEL_ENUM} ADD VALUE IF NOT EXISTS '{PORTAL}'"
        )
    op.create_index(
        PORTAL_INDEX,
        'conversations',
        ['tenant_id', 'reservation_id'],
        unique=True,
        postgresql_where=sa.text(f"channel = '{PORTAL}'"),
    )


def downgrade() -> None:
    """Downgrade schema.

    The enum label stays — see the module docstring. The index is dropped.
    """
    op.drop_index(PORTAL_INDEX, table_name='conversations')
