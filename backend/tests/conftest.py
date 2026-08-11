import asyncio

import asyncpg
import pytest
import pytest_asyncio
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
from app.core.redis import close_redis

# Tests get their own database, never the one `make up`/`migrate` manage — otherwise
# `Base.metadata.drop_all` wipes the dev stack's schema (tables gone,
# `alembic_version` still claims head). The name carries a per-run suffix so two
# concurrent pytest runs on one Postgres don't drop each other's tables; see
# tests/db_names.py.
_DEV_DB_URL = make_url(settings.database_url)
_TEST_DB_NAME = scoped_name(_DEV_DB_URL.database or "postgres", "test")
_TEST_DB_URL = _DEV_DB_URL.set(database=_TEST_DB_NAME).render_as_string(hide_password=False)


async def _admin_connection():
    return await asyncpg.connect(
        user=_DEV_DB_URL.username,
        password=_DEV_DB_URL.password,
        host=_DEV_DB_URL.host,
        port=_DEV_DB_URL.port,
        database="postgres",
    )


async def _ensure_test_database_exists() -> None:
    conn = await _admin_connection()
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()


async def _drop_test_database() -> None:
    conn = await _admin_connection()
    try:
        # FORCE (Postgres 13+) so a connection this suite failed to dispose of cannot
        # leave the database behind for the next run to inherit tables from.
        await conn.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}" WITH (FORCE)')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _remove_the_run_database_at_the_end():
    """Without this, every run would leave a `<db>_test_<pid>` behind for ever.

    Deliberately a sync fixture running `asyncio.run`: a session-scoped ASYNC fixture
    would need pytest-asyncio's session loop scope, and mixing loop scopes is what
    produced the "attached to a different loop" failures this file already works
    around. A fresh loop for one DROP has no such problem.
    """
    yield
    asyncio.run(_drop_test_database())


@pytest_asyncio.fixture
async def test_engine():
    """Engine on the test database, schema created and dropped around the test.

    A dedicated engine per test (NullPool: no connection kept across checkouts)
    avoids reusing a pooled asyncpg connection across pytest-asyncio's per-test
    event loops, which raises "attached to a different loop" / "another operation
    is in progress" once more than one DB-touching test runs in the same session.
    """
    await _ensure_test_database_exists()

    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def _close_the_redis_client_between_tests():
    """`app/core/redis.py::get_redis` caches one client in a module global; loops are per-test.

    So whichever test builds it first leaves a client bound to **its** event loop in the
    global, and the next test to reuse it dies with "Event loop is closed" from inside
    `redis.asyncio`. The failure is order-dependent and lands on an innocent file: measured
    twice on `guest-portal-api`, once as `tests/guests` poisoning
    `tests/integrations/test_webhook_receiver_api.py`, and once the other way round —
    `pytest tests/integrations tests/guests` was red while `tests/guests tests/integrations`
    was green, purely because collection order decided who built the client.

    It lives here rather than beside either test because the global belongs to neither: seven
    suites reach Redis, and a per-file teardown protects that file's successors while leaving
    the file itself at the mercy of whoever ran before it. Recorded as a roadmap candidate in
    that change's `proposal.md` while it looked like a local nuisance; promoted to a fix when
    the QA panel of section 6 showed it as a real red under an ordinary invocation.

    `close_redis()` no-ops when nothing built a client, which is the overwhelming majority of
    tests, so the cost is one attribute check per test.
    """
    yield
    await close_redis()
