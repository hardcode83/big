"""The per-request session must never leak a half-written transaction (R6.3)."""

import uuid

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import db as core_db
from app.core.db import get_db_session
from app.main import create_app
from app.tenants.infrastructure.models import TenantModel


def _tenant() -> TenantModel:
    return TenantModel(
        id=uuid.uuid4(),
        name=f"tenant-{uuid.uuid4().hex[:8]}",
        billing_email="ops@example.com",
    )


@pytest.fixture
def bound_factory(monkeypatch: pytest.MonkeyPatch, test_engine):
    """Point the real dependency at the test database, not the dev one."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(core_db, "async_session_factory", factory)
    return factory


@pytest.mark.asyncio
async def test_uncommitted_writes_are_rolled_back_when_the_request_fails(
    bound_factory, test_engine
) -> None:
    app = create_app()

    @app.post("/write-then-fail")
    async def write_then_fail(session: AsyncSession = Depends(get_db_session)) -> None:
        session.add(_tenant())
        await session.flush()
        raise RuntimeError("boom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/write-then-fail")

    assert response.status_code == 500

    async with AsyncSession(test_engine) as verify:
        assert await verify.scalar(select(func.count()).select_from(TenantModel)) == 0


@pytest.mark.asyncio
async def test_the_session_is_closed_after_a_successful_request(bound_factory) -> None:
    app = create_app()
    captured: list[AsyncSession] = []

    @app.get("/ok")
    async def ok(session: AsyncSession = Depends(get_db_session)) -> dict[str, bool]:
        captured.append(session)
        # Opens a transaction, so that "still open afterwards" is observable.
        session.add(_tenant())
        await session.flush()
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/ok")).status_code == 200

    assert captured, "the endpoint must have received a session"
    assert not captured[0].in_transaction(), "close() must release the open transaction"


@pytest.mark.asyncio
async def test_the_dependency_does_not_commit_on_its_own(bound_factory, test_engine) -> None:
    """The use case owns the commit (design D10); the dependency must not add one."""
    app = create_app()

    @app.post("/write-without-commit")
    async def write_without_commit(session: AsyncSession = Depends(get_db_session)) -> dict[str, bool]:
        session.add(_tenant())
        await session.flush()
        return {"written": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/write-without-commit")).status_code == 200

    async with AsyncSession(test_engine) as verify:
        assert await verify.scalar(select(func.count()).select_from(TenantModel)) == 0
