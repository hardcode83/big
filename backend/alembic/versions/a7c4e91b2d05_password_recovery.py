"""password recovery: password_reset_tokens table and users.must_change_password

Two additions, both from `auth-account-recovery`:

**`password_reset_tokens`** (R3.1, R4.1, design D1). One row per recovery link. `token_hash` is
the SHA-256 digest of the token in hexadecimal — the cleartext is never stored, because R4.1
requires that the row not permit reconstructing it. The digest is deterministic rather than
salted, and that is load-bearing: it is the only thing that makes the single conditional
`UPDATE ... WHERE token_hash = :h AND used_at IS NULL AND revoked_at IS NULL AND expires_at >
:now` of R3.2 possible. With bcrypt the row could not be found by the presented value at all, so
consuming a token would degrade into read-then-write — the race R3.2 exists to forbid.

`uq_password_reset_tokens_token_hash` is **UNIQUE**, not merely an index, and that is what makes
`rowcount` on that UPDATE a decision instead of a count: at most one row can ever match.
`ix_password_reset_tokens_tenant_id_user_id` serves `count_live` (the per-account cap of design
D7) and `revoke_other_live`.

**`users.must_change_password`** (R5.1). `NOT NULL` with `server_default false`, and
**deliberately no backfill**: existing accounts keep today's behaviour. A backfill here would
lock every current user out of every endpoint but three on the deployment that ran it — the
opposite of what a recovery feature is for. `users` is small and the column arrives with a
default, so in Postgres 16 this is a metadata-only `ALTER` with no table rewrite.

**Reversible.** `downgrade` drops the column and the table, including both indexes (dropping a
table takes its indexes with it; `op.drop_index` before `op.drop_table` would be redundant and
would fail if the table were already gone). No enum type is created here, so there is none to
leak. CI runs `alembic upgrade head`, `alembic check` and `alembic downgrade base`, so both
directions are verified on every push.

Revision ID: a7c4e91b2d05
Revises: a4d17e83b6c1
Create Date: 2026-08-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c4e91b2d05'
down_revision: Union[str, Sequence[str], None] = 'a4d17e83b6c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # `TenantScopedMixin` declares `tenant_id` with `index=True`, so this one comes from the
    # mixin rather than from `__table_args__`. Omitting it is what `alembic check` catches.
    op.create_index(
        "ix_password_reset_tokens_tenant_id",
        "password_reset_tokens",
        ["tenant_id"],
    )
    op.create_index(
        "uq_password_reset_tokens_token_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_tenant_id_user_id",
        "password_reset_tokens",
        ["tenant_id", "user_id"],
    )

    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
    op.drop_table("password_reset_tokens")
