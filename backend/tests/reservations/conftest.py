"""Fixtures for the reservation API tests: the real app over ASGI, two tenants, five roles.

Reuses the tenant/user helpers of `tests/auth/conftest.py` rather than re-seeding them:
they already create a user per role in each of two tenants, which is exactly what the
authorisation matrix (R5.7) and the isolation tests (R5.1) need. The neighbour tenant is
never optional here — an isolation test with nothing to fail to reach proves nothing.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.main import create_app
from app.properties.infrastructure.models import PropertyModel
# The tenant/role fixtures live in `tests/auth/conftest.py`, which only applies under
# `tests/auth/`. Importing them here re-registers them for this package: two tenants with a
# user per role is exactly the fixture set the authorisation matrix and the isolation tests
# need, and duplicating it would let the two copies drift.
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "r" * 64


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
        tenant_id=tenant_a.id,
        name="Redes 11",
        internal_code="REDES11",
        pms_external_id="PMS-REDES11",
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


@pytest_asyncio.fixture
async def property_b(db_session, tenant_b) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant_b.id,
        name="Pajaritos 8",
        internal_code="PAJARITOS8",
        pms_external_id="PMS-PAJARITOS8",
        max_guests=2,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


@pytest.fixture
def create_payload(property_a):
    def _payload(**overrides):
        payload = {
            "property_id": str(property_a.id),
            "channel": "DIRECT",
            "check_in_date": "2026-08-01",
            "check_out_date": "2026-08-04",
            "adults": 2,
        }
        payload.update(overrides)
        return payload

    return _payload
