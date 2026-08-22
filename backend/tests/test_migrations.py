"""The migration chain must run forwards and backwards (R2.1, design Risks).

`tests/conftest.py` builds the schema with `Base.metadata.create_all`, so a broken
Alembic revision would not show up anywhere else in the suite. This runs the real
`alembic` command an operator runs, against a throwaway database.
"""

import os
import subprocess
import sys

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url

from app.core.config import settings
from tests.db_names import scoped_name

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEV_URL = make_url(settings.database_url)
# Per-run name: this fixture opens with DROP DATABASE, so a fixed name means a second
# concurrent run drops the database this one is mid-test in (see tests/db_names.py).
_MIGRATIONS_DB = scoped_name(_DEV_URL.database or "postgres", "migrations")
_MIGRATIONS_URL = _DEV_URL.set(database=_MIGRATIONS_DB).render_as_string(hide_password=False)


async def _postgres_connection():
    return await asyncpg.connect(
        user=_DEV_URL.username,
        password=_DEV_URL.password,
        host=_DEV_URL.host,
        port=_DEV_URL.port,
        database="postgres",
    )


@pytest_asyncio.fixture
async def migrations_database():
    admin = await _postgres_connection()
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{_MIGRATIONS_DB}"')
        await admin.execute(f'CREATE DATABASE "{_MIGRATIONS_DB}"')
    finally:
        await admin.close()

    yield _MIGRATIONS_URL

    admin = await _postgres_connection()
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{_MIGRATIONS_DB}"')
    finally:
        await admin.close()


def _alembic(*args: str, database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


async def _table_exists(url: str, table: str) -> bool:
    parsed = make_url(url)
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )
    try:
        return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table))
    finally:
        await conn.close()


async def _enum_exists(url: str, type_name: str) -> bool:
    parsed = make_url(url)
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )
    try:
        return bool(await conn.fetchval("SELECT 1 FROM pg_type WHERE typname = $1", type_name))
    finally:
        await conn.close()


async def _index_exists(url: str, index_name: str) -> bool:
    parsed = make_url(url)
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )
    try:
        return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", index_name))
    finally:
        await conn.close()


async def _constraint_exists(url: str, constraint_name: str) -> bool:
    """Checked in `pg_constraint`, not by index name.

    A UNIQUE constraint is backed by an index of the same name, so looking it up with
    `to_regclass` would also pass for a plain index — and the revision that drops
    `uq_users_tenant_id_email` (ADR 0005) has to drop the CONSTRAINT, since an index
    left behind under that name would make the downgrade fail on a name clash.
    """
    parsed = make_url(url)
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )
    try:
        return bool(
            await conn.fetchval("SELECT 1 FROM pg_constraint WHERE conname = $1", constraint_name)
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_the_chain_upgrades_to_head_and_unwinds_revision_by_revision(
    migrations_database,
) -> None:
    """Each new revision is undone on its own, not as a batch.

    Targeting revisions explicitly instead of counting steps: a `downgrade -1` means
    something different every time a migration is added, which is how this test
    silently stopped covering `user_sessions` when the index revision landed.
    """
    url = migrations_database

    upgraded = _alembic("upgrade", "head", database_url=url)
    assert upgraded.returncode == 0, upgraded.stderr
    # domain-foundation-financial: one of its 10 tables and one of its 10 ENUM types.
    # The type is the load-bearing half — Alembic never emits DROP TYPE on its own, and
    # an orphan left behind breaks the NEXT upgrade with "type already exists".
    assert await _table_exists(url, "audit_logs") is True
    assert await _enum_exists(url, "expense_category") is True
    assert await _table_exists(url, "user_sessions") is True
    assert await _enum_exists(url, "session_revoked_reason") is True
    # Global email uniqueness replaces the per-tenant constraint (ADR 0005): the new
    # index exists AND the old constraint is gone. Asserting only the first would let
    # a revision that added the index without dropping the constraint pass, and the
    # two together are what make the email one contract instead of two.
    assert await _index_exists(url, "uq_users_lower_email") is True
    assert await _constraint_exists(url, "uq_users_tenant_id_email") is False

    # Undo domain-foundation-financial only; everything before it must survive.
    down_financial = _alembic("downgrade", "e1eed2e039ee", database_url=url)
    assert down_financial.returncode == 0, down_financial.stderr
    assert await _table_exists(url, "audit_logs") is False
    assert await _enum_exists(url, "expense_category") is False
    assert await _index_exists(url, "uq_users_lower_email") is True
    assert await _table_exists(url, "user_sessions") is True

    # Undo the email revision only.
    down_index = _alembic("downgrade", "8ff62a7cb50c", database_url=url)
    assert down_index.returncode == 0, down_index.stderr
    assert await _index_exists(url, "uq_users_lower_email") is False
    assert await _constraint_exists(url, "uq_users_tenant_id_email") is True
    assert await _table_exists(url, "user_sessions") is True

    # Undo user_sessions.
    down_sessions = _alembic("downgrade", "a1a72da30f8e", database_url=url)
    assert down_sessions.returncode == 0, down_sessions.stderr
    assert await _table_exists(url, "user_sessions") is False
    # Postgres keeps a native enum after its table is dropped; leaving it behind
    # would make the next upgrade fail with "type already exists".
    assert await _enum_exists(url, "session_revoked_reason") is False
    # Everything before these revisions must still be there.
    assert await _table_exists(url, "users") is True


@pytest.mark.asyncio
async def test_the_revisions_can_be_reapplied_after_a_downgrade(migrations_database) -> None:
    url = migrations_database

    assert _alembic("upgrade", "head", database_url=url).returncode == 0
    assert _alembic("downgrade", "a1a72da30f8e", database_url=url).returncode == 0

    reapplied = _alembic("upgrade", "head", database_url=url)

    assert reapplied.returncode == 0, reapplied.stderr
    # Re-applying is where an orphaned ENUM type would surface: the CREATE TABLE that
    # re-creates it fails with "type already exists" if the downgrade skipped DROP TYPE.
    assert await _table_exists(url, "audit_logs") is True
    assert await _enum_exists(url, "expense_category") is True
    assert await _table_exists(url, "user_sessions") is True
    assert await _index_exists(url, "uq_users_lower_email") is True
    # The re-upgrade has to drop the constraint its own downgrade recreated; if it
    # left it behind, the schema would carry both rules and drift from the models.
    assert await _constraint_exists(url, "uq_users_tenant_id_email") is False


async def _column_shape(url: str, table: str, column: str) -> tuple[str, int | None] | None:
    """`(data_type, character_maximum_length)` as the **real** DDL has it, not as a model says.

    Needed because neither of the two things that look like they cover it does:
    `tests/conftest.py` builds the suite's schema with `Base.metadata.create_all`, so every
    other test in the tree measures the model; and `alembic check` compares presence and
    nullability but **not** type, because `alembic/env.py` does not pass `compare_type=True`
    and Alembic's default is `False`. So a revision declaring a different width from its model
    kept the whole suite green. Raised by the QA panel of `tech-incident-context` sections 1-2.

    **The type comes back with the width, and that is the second round of the same lesson.**
    A first version returned the width alone, and the QA panel of the final round pointed out
    that `sa.CHAR(length=2000)` reports `character_maximum_length = 2000` just like
    `VARCHAR(2000)` — so a revision that silently became `CHAR` would have kept these tests
    green while padding every stored value with trailing spaces. Asserting the width without
    the type is measuring the half that cannot tell the two apart.

    Returns `None` when the column does not exist, so a caller can tell "dropped" from
    "present with an unexpected shape" instead of both looking like a `None` width.
    """
    parsed = make_url(url)
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )
    try:
        row = await conn.fetchrow(
            "SELECT data_type, character_maximum_length FROM information_schema.columns "
            "WHERE table_name = $1 AND column_name = $2",
            table,
            column,
        )
        return None if row is None else (row["data_type"], row["character_maximum_length"])
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_the_declared_column_widths_reach_the_real_ddl(migrations_database) -> None:
    """A bound that lives in the model and not in the database is half a bound — and a width
    without its type is half a measurement.

    `tech-incident-context` D6 states the rule this asserts — "la cota vive en la base **y** en
    el esquema, no sólo en el segundo" — and `properties-crud` R2.4 is the change that had to
    repair four columns which shipped bounded on one side only.

    Read from `information_schema` after a real `alembic upgrade head`, which is the only place
    in this suite where the migration's own DDL is what answers. The **type** is asserted
    alongside the width because `CHAR(2000)` reports the same `character_maximum_length` as
    `VARCHAR(2000)` and would pad every stored value with trailing spaces (QA panel, final
    round).
    """
    url = migrations_database
    assert _alembic("upgrade", "head", database_url=url).returncode == 0

    assert await _column_shape(url, "incidents", "assignment_note") == (
        "character varying",
        2000,
    )
    # A second column, so the helper is not pinned to one case: `incidents.title` is
    # `String(300)` in the model and the baseline revision declares the same.
    assert await _column_shape(url, "incidents", "title") == ("character varying", 300)


@pytest.mark.asyncio
async def test_an_added_column_unwinds_and_reapplies_over_existing_rows(
    migrations_database,
) -> None:
    """`incidents.assignment_note` down and up again, with a row already in the table.

    The chain test above walks revisions that create and drop whole tables; this walks the
    other shape — an `ADD COLUMN` on a **populated** table — which is what
    `tech-incident-context` R3.1 adds and what the dev database has been exposed to since it
    got rows on 2026-08-10. Three things are proven that an empty-table run cannot: that the
    `ADD COLUMN` does not fail on existing rows, that `downgrade` really drops the column
    rather than leaving it behind, and that the re-upgrade brings it back `NULL` for the row
    that was already there.

    Written after the QA panel of sections 1-2 pointed out that no test executed the new
    revision's `downgrade()` at all. It is what task 10.2 asks for, as a test rather than as a
    manual pass.
    """
    url = migrations_database
    assert _alembic("upgrade", "head", database_url=url).returncode == 0

    parsed = make_url(url)
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )
    try:
        tenant_id = await conn.fetchval(
            "INSERT INTO tenants (id, name, billing_email) "
            "VALUES (gen_random_uuid(), 'MigrationTenant', 'm@example.com') RETURNING id"
        )
        property_id = await conn.fetchval(
            "INSERT INTO properties (id, tenant_id, name, internal_code) "
            "VALUES (gen_random_uuid(), $1, 'Redes 11', 'REDES11') RETURNING id",
            tenant_id,
        )
        incident_id = await conn.fetchval(
            "INSERT INTO incidents "
            "(id, tenant_id, property_id, source, title, description, assignment_note) "
            "VALUES (gen_random_uuid(), $1, $2, 'GUEST', 'Broken boiler', "
            "'No hot water.', 'Portal code 4821.') RETURNING id",
            tenant_id,
            property_id,
        )
    finally:
        await conn.close()

    unwound = _alembic("downgrade", "e7a3c419d82b", database_url=url)
    assert unwound.returncode == 0, unwound.stderr
    assert await _column_shape(url, "incidents", "assignment_note") is None

    reapplied = _alembic("upgrade", "head", database_url=url)
    assert reapplied.returncode == 0, reapplied.stderr
    assert await _column_shape(url, "incidents", "assignment_note") == (
        "character varying",
        2000,
    )

    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )
    try:
        # The row survived the round trip, and its note did not: a `DROP COLUMN` loses the
        # data, which is what the revision's docstring says it means.
        assert await conn.fetchval(
            "SELECT assignment_note IS NULL FROM incidents WHERE id = $1", incident_id
        ) is True
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_the_models_match_the_migrations(migrations_database) -> None:
    """An empty autogenerate diff: no model change left without a migration."""
    url = migrations_database
    assert _alembic("upgrade", "head", database_url=url).returncode == 0

    check = _alembic("check", database_url=url)

    assert check.returncode == 0, f"models and migrations diverged:\n{check.stdout}{check.stderr}"
