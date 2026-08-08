"""properties: pms_external_id unique per provider within a tenant

Adds `uq_properties_tenant_id_pms_external_id` as a PARTIAL, EXPRESSION unique index over
`(tenant_id, coalesce(pms_provider, 'MOCK'), pms_external_id)` (design D5 of `properties-crud`).

**Why the write path forces this now.** `specs/reservations.md` requires the PMS sync to FAIL
rather than pick one when two properties share a `pms_external_id`: adjudicating the booking to
either would tie the guest to the wrong home. Until now nothing could create that state, because
`properties` had no write path at all. `POST`/`PATCH /api/v1/properties` is exactly such a path,
so the ambiguity moves from "impossible in practice" to "one request away", and an
application-level pre-check would not close it — two concurrent requests would both pass the
check and one would surface as a 500. The index is the only race-free place to enforce it.

**Why the scope is the PROVIDER and not the tenant.** External ids are unique only WITHIN a
provider. A tenant mid-migration legitimately has one property on Beds24 and another on Channex
that happen to carry the same id — the scenario ADR 0006 decision 7 exists for, and the sync
already handles it by restricting matching to the provider group being synced
(`tests/integrations/test_sync.py::test_a_reservation_cannot_attach_to_a_property_of_another_provider`
asserts exactly that). The first version of this migration keyed on `(tenant_id,
pms_external_id)` alone and broke three tests by forbidding that legitimate state. Recorded here
rather than quietly amended, because the tenant-wide reading of `specs/reservations.md:128` is
the one that looks right on paper.

**Why `coalesce` instead of just adding the column to the key.** `pms_provider` is nullable and
NULL means "the bootstrap default", which `pms_factory.DEFAULT_PROVIDER` defines as `MOCK`.
Postgres treats NULLs as DISTINCT inside an index key, so `(tenant_id, pms_provider,
pms_external_id)` would still admit two provider-less properties claiming one id — the exact
ambiguity this index exists to prevent, left open by the obvious fix. Folding NULL to `MOCK`
closes it and is also what the values *mean*: both are served by the mock adapter, so they are
one group. The precedent for indexing an expression rather than a raw column is
`uq_users_lower_email` in `e1eed2e039ee`.

**A state that was previously constructible and no longer is, on purpose.** Inserting a property
with no provider and then moving it to another one passes through the forbidden state, so a
caller that wants two properties on different providers sharing an id must set the provider **at
insert time**. Two existing tests built their scenario the first way and were adjusted; that is a
behaviour change of the write path, not a test fix.

**Why PARTIAL.** Most properties carry no external id at all, and rows the invariant says
nothing about do not belong in the index. Same shape as `uq_pms_credentials_account_scope` in
`c3f81a5d7e42`.

**No data migration, and no rewriting of existing rows.** `properties` is empty in every
environment (`PropertyModel` is instantiated in tests only, never in `app/`, `alembic/versions/`,
`scripts/` or a Makefile target), so creating a unique index cannot fail on pre-existing
duplicates. Stated rather than omitted, because a unique index over populated data is exactly the
kind of migration that fails in the environment nobody checked.

**Reversible.** `downgrade` drops the index and nothing else; no type is created here, so there is
no enum to leak. CI runs `alembic check` and `alembic downgrade base`, so both directions are
verified on every push.

**What this deliberately does NOT touch**: the pre-existing non-unique
`ix_properties_tenant_id_pms_external_id`. It still serves the tenant-wide lookup of
`find_by_pms_external_id`, which this index does not cover because its leading expression differs
— so it is not redundant, which is what an earlier draft of this note assumed.

Revision ID: f2b9c7a41d38
Revises: c3f81a5d7e42
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b9c7a41d38'
# Re-pointed from `c3f81a5d7e42` to `cleaning`'s revision when this branch was merged with
# `main`. Both had been written against the same parent, so the files merged without a textual
# conflict while leaving Alembic with TWO heads — which `alembic upgrade head` refuses, and CI
# runs exactly that. This repository keeps a strictly linear chain and has no merge revisions, so
# the fix is to linearise rather than to add one. Safe to re-point: this migration only creates an
# index and had not been applied anywhere but a development database.
down_revision: Union[str, Sequence[str], None] = 'd4b0c7a91f38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_properties_tenant_id_pms_external_id"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "properties",
        [
            "tenant_id",
            # Written as an expression, matching the model, so both sides of `alembic check`
            # derive the key from the same construct instead of from two hand-kept strings.
            #
            # `CAST(pms_provider AS TEXT)` was the first attempt and Postgres rejects it —
            # "functions in index expression must be marked IMMUTABLE", because an enum-to-text
            # cast is only STABLE (labels can be renamed). Coalescing to an enum literal has no
            # function call at all, so it is accepted.
            sa.func.coalesce(sa.column("pms_provider"), sa.text("'MOCK'")),
            "pms_external_id",
        ],
        unique=True,
        postgresql_where=sa.text("pms_external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="properties")
