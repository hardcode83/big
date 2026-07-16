import asyncpg
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

# Import every domain module's infrastructure/models.py so Base.metadata is
# fully populated regardless of which test file runs — cross-module FKs
# (e.g. PropertyStateTransitionModel.triggered_by_user_id -> users.id) need
# their target table registered before create_all, not just a correct type.
import app.tenants.infrastructure.models  # noqa: F401
import app.auth.infrastructure.models  # noqa: F401
import app.properties.infrastructure.models  # noqa: F401
import app.guests.infrastructure.models  # noqa: F401
import app.reservations.infrastructure.models  # noqa: F401
import app.timeline.infrastructure.models  # noqa: F401

from app.core.config import settings
from app.core.db import Base

# Tests get their own database (dev DB name + "_test"), never the one
# `make up`/`migrate` manage — otherwise `Base.metadata.drop_all` wipes the
# dev stack's schema (tables gone, `alembic_version` still claims head).
_DEV_DB_URL = make_url(settings.database_url)
_TEST_DB_NAME = f"{_DEV_DB_URL.database}_test"
_TEST_DB_URL = _DEV_DB_URL.set(database=_TEST_DB_NAME).render_as_string(hide_password=False)


async def _ensure_test_database_exists() -> None:
    conn = await asyncpg.connect(
        user=_DEV_DB_URL.username,
        password=_DEV_DB_URL.password,
        host=_DEV_DB_URL.host,
        port=_DEV_DB_URL.port,
        database="postgres",
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def db_session():
    await _ensure_test_database_exists()

    # A dedicated engine per test (NullPool: no connection kept across
    # checkouts) avoids reusing a pooled asyncpg connection across
    # pytest-asyncio's per-test event loops, which raises "attached to a
    # different loop" / "another operation is in progress" once more than
    # one DB-touching test runs in the same session.
    test_engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_engine.dispose()
