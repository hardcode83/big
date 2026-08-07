"""properties: pms_external_id unique per tenant

Adds `uq_properties_tenant_id_pms_external_id` as a PARTIAL unique index, so that at most one
property per tenant can claim a given external PMS id (design D5 of `properties-crud`).

**Why the write path forces this now.** `specs/reservations.md` requires the PMS sync to FAIL
rather than pick one when two properties of a tenant share a `pms_external_id`: adjudicating the
booking to either would tie the guest to the wrong home. Until now nothing could create that
state, because `properties` had no write path at all. `POST`/`PATCH /api/v1/properties` is exactly
such a path, so the ambiguity moves from "impossible in practice" to "one request away", and an
application-level pre-check would not close it — two concurrent requests would both pass the
check and one would surface as a 500. The index is the only race-free place to enforce it.

**Why PARTIAL and not a plain UNIQUE.** `pms_external_id` is nullable and most properties will
carry no external id at all: Postgres treats NULLs as distinct in a UNIQUE constraint, so a total
unique index would technically allow many NULL rows — but it would also index every one of them
for nothing. `WHERE pms_external_id IS NOT NULL` keeps the index to the rows the invariant is
about. Same reasoning and same shape as `uq_pms_credentials_account_scope` in `c3f81a5d7e42`.

**No data migration, and no rewriting of existing rows.** `properties` is empty in every
environment (`PropertyModel` is instantiated in tests only, never in `app/`, `alembic/versions/`,
`scripts/` or a Makefile target), so creating a unique index cannot fail on pre-existing
duplicates. Stated rather than omitted, because a unique index over populated data is exactly the
kind of migration that fails in the environment nobody checked.

**Reversible.** `downgrade` drops the index and nothing else; no type is created here, so there is
no enum to leak. CI runs `alembic check` and `alembic downgrade base`, so both directions are
verified on every push.

**What this deliberately does NOT touch**: the pre-existing non-unique
`ix_properties_tenant_id_pms_external_id`. The new index would serve the same lookups, so the old
one is arguably redundant — but removing it is a separate judgement about read paths this change
does not otherwise touch, and it is flagged for review rather than bundled in silently.

Revision ID: f2b9c7a41d38
Revises: c3f81a5d7e42
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b9c7a41d38'
down_revision: Union[str, Sequence[str], None] = 'c3f81a5d7e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_properties_tenant_id_pms_external_id"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "properties",
        ["tenant_id", "pms_external_id"],
        unique=True,
        postgresql_where=sa.text("pms_external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="properties")
