"""Fixtures for the timeline API tests: the real app over ASGI, two tenants, five roles.

Reuses the tenant/user helpers of `tests/auth/conftest.py` rather than re-seeding them, the
way `tests/properties/conftest.py` and `tests/reservations/conftest.py` already do — two
tenants with a user per role is what the authorisation matrix and the isolation tests both
need, and a second copy would drift from the original.
"""

import uuid

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

SECRET = "t" * 64


@pytest_asyncio.fixture
async def api(db_session):
    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        yield client


def auth_header(client, user: UserModel) -> dict[str, str]:
    """A real access token for `user`, issued by the same codec the app verifies with."""
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def property_a(db_session, tenant_a) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant_a.id, name="Redes 11", internal_code="REDES11", max_guests=4
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


@pytest_asyncio.fixture
async def property_b(db_session, tenant_b) -> PropertyModel:
    """A property of the NEIGHBOUR tenant, inserted directly and not through the API.

    Deliberate, for the reason `tests/properties/conftest.py` records: these tests share ONE
    session, and `get_authenticated_request` binds it to the tenant of whoever calls. A
    request as tenant B would rebind it and make the next call as tenant A answer `401`
    instead of the `404` under test.
    """
    prop = PropertyModel(
        tenant_id=tenant_b.id, name="Pajaritos 8", internal_code="PAJARITOS8", max_guests=2
    )
    db_session.add(prop)
    await db_session.flush()
    return prop
