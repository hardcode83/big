import asyncio
import os
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.db_names import scoped_name

# Every domain module's infrastructure/models.py must be imported so Base.metadata
# is fully populated regardless of which test file runs — cross-module FKs
# (e.g. PropertyStateTransitionModel.triggered_by_user_id -> users.id) need their
# target table registered before create_all, not just a correct type. The list lives
# in one place now (app/core/models_registry.py), which the application imports too.
import app.core.models_registry  # noqa: F401

from app.core.config import settings
from app.core.db import Base

# Redis has no per-run namespace the way Postgres has a per-run database, and the suite
# uses PRODUCTION key names on purpose: `tests/scheduler/test_dispatch_task.py` takes the
# real `dispatch_notifications` lock, and another test demands to find that same lock free.
# Run those in two xdist workers against one Redis and they cross.
#
# Every client in the suite — and `get_redis()` itself — is built from `settings.redis_url`,
# so one logical database per worker is enough, and it is rewritten here, before any client
# can be created.
_REDIS_LOGICAL_DATABASES = 16  # 0-15: Redis' default `databases 16`


def _redis_url_for_this_worker(url: str) -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return url
    if not (worker.startswith("gw") and worker[2:].isdigit()):
        raise RuntimeError(f"unexpected pytest-xdist worker id {worker!r}")

    index = int(worker[2:])
    # Fails in the face rather than wrapping around or silently sharing database 0, which
    # would put the collision back without saying so.
    if index >= _REDIS_LOGICAL_DATABASES:
        raise RuntimeError(
            f"worker {worker} needs Redis logical database {index}, but Redis serves only "
            f"{_REDIS_LOGICAL_DATABASES} (0-{_REDIS_LOGICAL_DATABASES - 1}) by default. "
            f"Run with -n {_REDIS_LOGICAL_DATABASES} or fewer, or raise `databases` in Redis."
        )
    return urlunparse(urlparse(url)._replace(path=f"/{index}"))


settings.redis_url = _redis_url_for_this_worker(settings.redis_url)

# Tests get their own database, never the one `make up`/`migrate` manage — otherwise
# the suite wipes the dev stack's schema (tables gone, `alembic_version` still claims
# head). The name carries a per-run suffix so two concurrent pytest runs on one
# Postgres don't drop each other's tables; see tests/db_names.py.
_DEV_DB_URL = make_url(settings.database_url)
_TEST_DB_NAME = scoped_name(_DEV_DB_URL.database or "postgres", "test")
_TEST_DB_URL = _DEV_DB_URL.set(database=_TEST_DB_NAME).render_as_string(hide_password=False)

# One statement that empties every table, because the schema is now built once per run
# (see `_the_run_database`) and isolation between tests is deletion of rows rather than
# DDL: 21ms against the 361ms that create_all + drop_all cost per test.
#
# A single statement and not one DELETE per table: asyncpg refuses several commands in a
# prepared statement, and the data-modifying CTEs run exactly once each whether or not the
# primary query reads them. They share one snapshot and foreign keys are checked when the
# statement ends, so the order between tables does not matter. No sequences to reset: every
# primary key in the tree is a UUID (`app/core/db.py`).
#
# The list comes from the metadata, the same source `create_all` uses, so a new table joins
# the wipe on its own — and a table absent from the metadata does not exist in this database
# either.
_WIPE_EVERY_TABLE = "WITH " + ", ".join(
    f'd{index} AS (DELETE FROM "{table.name}")'
    for index, table in enumerate(Base.metadata.sorted_tables)
) + " SELECT 1"


async def _admin_connection():
    return await asyncpg.connect(
        user=_DEV_DB_URL.username,
        password=_DEV_DB_URL.password,
        host=_DEV_DB_URL.host,
        port=_DEV_DB_URL.port,
        database="postgres",
    )


async def _drop_test_database() -> None:
    conn = await _admin_connection()
    try:
        # FORCE (Postgres 13+) so a connection this suite failed to dispose of cannot
        # leave the database behind for the next run to inherit tables from.
        await conn.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}" WITH (FORCE)')
    finally:
        await conn.close()


async def _build_the_run_database() -> None:
    await _drop_test_database()
    conn = await _admin_connection()
    try:
        await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()

    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _the_run_database():
    """Builds `<db>_test_<suffix>` from nothing at the start of the run, and drops it after.

    Dropping first is what makes "from nothing" true. Creating only if missing was
    harmless while every test recreated the whole schema, but the schema is now built
    once here, so inheriting a database left behind by a dead run would mean inheriting
    *its* schema — and the case is real in CI, where `PYTEST_DB_SUFFIX: ci` pins the name
    and makes it reusable. Without the final drop, every local run would leave a
    `<db>_test_<pid>` behind for ever.

    Deliberately a sync fixture running `asyncio.run`: a session-scoped ASYNC fixture
    would need pytest-asyncio's session loop scope, and mixing loop scopes is what
    produced the "attached to a different loop" failures this file already works
    around. A fresh loop that closes before any test starts has no such problem.
    """
    asyncio.run(_build_the_run_database())
    yield
    asyncio.run(_drop_test_database())


@pytest_asyncio.fixture
async def test_engine():
    """Engine on the test database, whose tables are emptied before the test runs.

    A dedicated engine per test (NullPool: no connection kept across checkouts)
    avoids reusing a pooled asyncpg connection across pytest-asyncio's per-test
    event loops, which raises "attached to a different loop" / "another operation
    is in progress" once more than one DB-touching test runs in the same session.

    The schema itself is built once per run by `_the_run_database`; what happens here is
    the wipe. `lock_timeout` turns a previous test that left a transaction open into an
    immediate, readable error instead of a hang — the failure mode that emptying rows has
    and dropping the schema did not.
    """
    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)

    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '10s'"))
        await conn.execute(text(_WIPE_EVERY_TABLE))

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        yield session
