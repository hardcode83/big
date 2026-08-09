"""Fixtures for the dashboard endpoint tests: the real app over ASGI, two tenants, five roles.

Reuses the tenant/user helpers of `tests/auth/conftest.py` the way every other module's
conftest does. The neighbour tenant is never optional here — an isolation test with nothing
to fail to reach proves nothing (task 6.5, DoD §28.18).
"""

import uuid
from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.main import create_app
from app.properties.infrastructure.models import PropertyModel

from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "d" * 64

#: The day the endpoint judges "current or next" against. Fixed so a test's seeded stay
#: does not drift out of the window on the day this suite happens to run.
TODAY = date(2026, 8, 9)
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def api(db_session):
    from app.dashboard.api.router import _today

    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )
    app.dependency_overrides[_today] = lambda: TODAY

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        yield client


def auth_header(client, user: UserModel) -> dict[str, str]:
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    return {"Authorization": f"Bearer {token}"}


async def insert_property(db_session, tenant, *, code: str = "REDES11") -> PropertyModel:
    model = PropertyModel(
        tenant_id=tenant.id, name=code, internal_code=code, max_guests=4
    )
    db_session.add(model)
    await db_session.flush()
    return model


@pytest_asyncio.fixture
async def property_a(db_session, tenant_a) -> PropertyModel:
    return await insert_property(db_session, tenant_a, code="REDES11")


@pytest_asyncio.fixture
async def property_b(db_session, tenant_b) -> PropertyModel:
    """The neighbour's property, seeded directly through the ORM.

    Same reason `tests/properties/conftest.py` records: these tests share one session, and a
    request as tenant B would leave it bound to B, so the next call as tenant A would answer
    `401` instead of the `404` under test.
    """
    return await insert_property(db_session, tenant_b, code="PAJARITOS8")
