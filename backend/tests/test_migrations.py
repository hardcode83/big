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


@pytest.mark.asyncio
async def test_the_models_match_the_migrations(migrations_database) -> None:
    """An empty autogenerate diff: no model change left without a migration."""
    url = migrations_database
    assert _alembic("upgrade", "head", database_url=url).returncode == 0

    check = _alembic("check", database_url=url)

    assert check.returncode == 0, f"models and migrations diverged:\n{check.stdout}{check.stderr}"
