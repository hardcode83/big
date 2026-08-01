"""session_revoked_reason: two administrative revocation reasons

`user-management` revokes somebody else's sessions: deactivating an account (R3.7) and
resetting its password (R4.2) both have to kill every refresh family of the affected
user. `LOGOUT` and `REUSE_DETECTED` would both be lies — in neither case is the
session's owner the actor.

Why revoking is necessary at all, and not just belt-and-braces: `auth-tenancy`
revalidates the user and its tenant on every authenticated request, so a deactivated
account is rejected with 401 when it presents an ACCESS token. But
`POST /api/v1/auth/refresh` does not go through `get_authenticated_request` (it is
anonymous by construction — the refresh token IS the credential), so without this a
deactivated user keeps rotating fresh pairs for the whole 7-day refresh lifetime.

Two values rather than one `ADMIN_REVOKED` (design D7, D18): `revoked_reason` exists to
diagnose, and "you were deactivated" and "your password was reset" are different answers
to the same complaint.

NOT REVERSIBLE. PostgreSQL cannot remove a value from an enum type; the only way back is
recreating the type, rewriting every column that uses it and remapping the rows that
carry the value being dropped. `downgrade` is therefore a documented no-op rather than a
lie that half-works: leaving two unused labels in a type is harmless, and
`alembic downgrade base` (which CI runs) drops the whole type in the revision that
created it anyway.

`ADD VALUE` inside Alembic's transaction is fine on PostgreSQL 12+ — what is forbidden
is USING the new value in the same transaction that adds it, and this revision only
adds them. `IF NOT EXISTS` so re-running against a database where a previous attempt
half-applied is not an error.

Revision ID: b7c41d92e5a3
Revises: 96d526599bc1
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c41d92e5a3'
down_revision: Union[str, Sequence[str], None] = '96d526599bc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUM_NAME = 'session_revoked_reason'
NEW_VALUES = ('USER_DEACTIVATED', 'PASSWORD_RESET')


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Deliberately empty — see the module docstring.

    Removing an enum label is not expressible in PostgreSQL. Recreating the type to drop
    two unused labels would rewrite `user_sessions.revoked_reason` and would have to
    decide what to do with rows already carrying them, which is a data decision this
    revision has no basis to make. Two extra labels nobody writes cost nothing.
    """
