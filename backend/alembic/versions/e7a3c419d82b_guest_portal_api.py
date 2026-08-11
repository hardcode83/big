"""guest portal api: per-stay access tokens, a guest audit actor and a check-in event

Three additive changes, one revision (`guest-portal-api` design D2, D11, D12):

- `guest_access_tokens` — the opaque per-stay credential of R1.1, with its globally unique
  `token_hash` and the partial unique index that makes R1.5 ("never two live tokens for one
  stay") an invariant of the schema instead of discipline in the use case.
- `audit_logs.actor_guest_token_hash` — the anonymous actor of R6.1. A **declared
  divergence from PRD §7.25**, which enumerates that table's columns and does not include
  it; §23 declares an anonymous guest surface and rule 9 of `steering/security.md` requires
  knowing who touched the data, and the two are only compatible with a column.
- `timeline_event_type.GUEST_CHECKIN_COMPLETED` — R6.3, D12.

**On `ALTER TYPE ... ADD VALUE` and `autocommit_block()`.** Design D12's Risks section
anticipated wrapping the enum change in `op.get_context().autocommit_block()`, on the
grounds that "un valor de enum añadido no puede usarse en la misma transacción que lo
añade". The premise is right and the remedy is not needed here, which is what the precedent
it cites — `b7c41d92e5a3_session_revoked_reason_administrative.py` — had already worked out
and documented: on PostgreSQL 12+ the restriction is on *using* the new label in the adding
transaction, not on adding it. This revision only adds it; nothing here writes a
`timeline_events` row.

Using an autocommit block would actively cost something rather than being free insurance.
`alembic/env.py` wraps the whole run in one `context.begin_transaction()`, so an autocommit
block would commit every revision applied before it and give up the all-or-nothing property
of `alembic upgrade head`. Verified both ways against PostgreSQL 16 before choosing.

`IF NOT EXISTS` on the label so re-running against a database where a previous attempt
half-applied is not an error.

**The two composite foreign keys validate existing rows on the way in.** `ADD CONSTRAINT`
without `NOT VALID` scans the table, so on a populated database a pre-existing mismatched
pair — a token whose tenant disagrees with its reservation's, or a stay linked to another
tenant's guest — aborts the upgrade rather than being grandfathered in. That is the wanted
behaviour and it is fail-closed, but it is worth knowing before a deploy window rather than
during one: the fix would be to find and correct the offending rows, never to weaken the
constraint. Both tables are empty in every environment today (`guest_access_tokens` is
created here; `reservations.guest_id` has no cross-tenant writer), so the scan is a no-op.

**The enum label is not removed on the way down, and `downgrade` says so rather than
pretending.** PostgreSQL cannot drop a value from an enum type; the only route is
recreating the type, rewriting every column that uses it and deciding what to do with rows
already carrying the value — a data decision this revision has no basis to make. An unused
label costs nothing, and `alembic downgrade base` (which CI runs) drops the whole type in
the revision that created it anyway. The table and the column *are* dropped.

Revision ID: e7a3c419d82b
Revises: a4d17e83b6c1
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a3c419d82b'
down_revision: Union[str, Sequence[str], None] = 'a4d17e83b6c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIMELINE_EVENT_TYPE_ENUM = 'timeline_event_type'
GUEST_CHECKIN_COMPLETED = 'GUEST_CHECKIN_COMPLETED'


def upgrade() -> None:
    """Upgrade schema."""
    # Redundant as a constraint (`id` is already the primary key) and load-bearing as an FK
    # **target**: PostgreSQL only lets a composite foreign key reference a declared unique
    # key, and `guest_access_tokens` needs one to tie a token's tenant to its stay's tenant.
    op.create_unique_constraint(
        'uq_reservations_tenant_id_id', 'reservations', ['tenant_id', 'id']
    )

    # The same remedy for `reservations.guest_id`, which this change gives its first writer
    # driven from an anonymous surface (`LegalRegistrationStayStore.set_guest`, OQ3). Three
    # reviewers of section 3 independently reproduced a stay of tenant A linked to a guest of
    # tenant B before this existed. `guest_id` is nullable and MATCH SIMPLE means the
    # constraint does not apply when it is NULL — which is wanted, since a booking with no
    # guest is legal.
    #
    # `property_id` deliberately keeps its single-column FK: this change does not write it,
    # and hardening it would reach into the reservations CRUD and the PMS sync.
    op.create_unique_constraint('uq_guests_tenant_id_id', 'guests', ['tenant_id', 'id'])
    op.drop_constraint('reservations_guest_id_fkey', 'reservations', type_='foreignkey')
    op.create_foreign_key(
        'fk_reservations_guest_within_tenant',
        'reservations',
        'guests',
        ['tenant_id', 'guest_id'],
        ['tenant_id', 'id'],
        ondelete='RESTRICT',
    )

    op.create_table(
        'guest_access_tokens',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('reservation_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # **Composite**, and the only composite FK in the schema. Two independent FKs would
        # let a row pair tenant A with a reservation owned by tenant B, and the guest portal
        # authorises on a session that is deliberately not yet marked with a tenant — the
        # token row is what resolves it — so the global filter of `app/core/db.py` is off at
        # exactly the moment such a pair would be read, and the request would then be bound
        # to the wrong tenant. Rule 3(c) of `steering/security.md`: a scoping failure here
        # does not disclose data, it grants control. Both the security and the tenancy panel
        # of section 1 demonstrated the mismatched row being accepted before this existed.
        #
        # RESTRICT, not CASCADE: a live token is a reason not to delete the stay silently.
        sa.ForeignKeyConstraint(
            ['tenant_id', 'reservation_id'],
            ['reservations.tenant_id', 'reservations.id'],
            ondelete='RESTRICT',
            name='fk_guest_access_tokens_reservation_within_tenant',
        ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_guest_access_tokens_tenant_id'), 'guest_access_tokens', ['tenant_id'], unique=False)
    # Globally unique, not per tenant: the authorising path queries this column with no
    # tenant in hand, because the token is what resolves the tenant. Uniqueness across the
    # whole table is what makes "exactly one row" a schema guarantee (D2).
    op.create_index(op.f('ix_guest_access_tokens_token_hash'), 'guest_access_tokens', ['token_hash'], unique=True)
    # R1.5. Partial, because the revoked rows are the history of who was given access and a
    # plain UNIQUE on `reservation_id` would forbid keeping them.
    op.create_index(
        'uq_guest_access_tokens_live_per_reservation',
        'guest_access_tokens',
        ['reservation_id'],
        unique=True,
        postgresql_where=sa.text('revoked_at IS NULL'),
    )

    op.add_column(
        'audit_logs',
        sa.Column('actor_guest_token_hash', sa.String(length=64), nullable=True),
    )
    # R1.2/R6.4 enforced by the database, not only by `AuditLogFactory`. The realistic
    # accident is writing the **token** instead of its digest: `secrets.token_urlsafe(32)` is
    # 43 characters, so `VARCHAR(64)` accepts it and this append-only table would then hold
    # live portal credentials. `AuditLog` is a plain mutable dataclass, so nothing forces a
    # writer through the factory — the same reasoning that puts the cross-tenant guard in the
    # repository. Raised by the security panel of section 1.
    op.create_check_constraint(
        'ck_audit_logs_actor_guest_token_hash_is_a_digest',
        'audit_logs',
        "actor_guest_token_hash IS NULL OR actor_guest_token_hash ~ '^[0-9a-f]{64}$'",
    )

    op.execute(
        f"ALTER TYPE {TIMELINE_EVENT_TYPE_ENUM} ADD VALUE IF NOT EXISTS "
        f"'{GUEST_CHECKIN_COMPLETED}'"
    )


def downgrade() -> None:
    """Downgrade schema.

    The enum label stays — see the module docstring. Everything else is undone.
    """
    # The CHECK goes with the column it constrains, so dropping the column suffices.
    op.drop_column('audit_logs', 'actor_guest_token_hash')
    op.drop_index('uq_guest_access_tokens_live_per_reservation', table_name='guest_access_tokens')
    op.drop_index(op.f('ix_guest_access_tokens_token_hash'), table_name='guest_access_tokens')
    op.drop_index(op.f('ix_guest_access_tokens_tenant_id'), table_name='guest_access_tokens')
    op.drop_table('guest_access_tokens')
    # Restore the single-column guest FK before dropping the unique key its composite
    # replacement depends on.
    op.drop_constraint('fk_reservations_guest_within_tenant', 'reservations', type_='foreignkey')
    op.create_foreign_key(
        'reservations_guest_id_fkey',
        'reservations',
        'guests',
        ['guest_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.drop_constraint('uq_guests_tenant_id_id', 'guests', type_='unique')
    # After the table, never before: the composite FK depends on this unique key, and
    # Postgres refuses to drop a constraint another one references.
    op.drop_constraint('uq_reservations_tenant_id_id', 'reservations', type_='unique')
