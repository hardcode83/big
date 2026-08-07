"""Fixtures for the property API tests: the real app over ASGI, two tenants, five roles.

Reuses the tenant/user helpers of `tests/auth/conftest.py` rather than re-seeding them: they
already create a user per role in each of two tenants, which is exactly what the authorisation
matrix (R6.8) and the isolation tests (R7.6) need. The neighbour tenant is never optional here —
an isolation test with nothing to fail to reach proves nothing.
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

# Registered for this package the same way `tests/reservations/conftest.py` does it: two tenants
# with a user per role is the fixture set both the matrix and the isolation tests need, and a
# second copy would drift from the original.
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "p" * 64


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
async def property_b(db_session, tenant_b) -> PropertyModel:
    """A property of the NEIGHBOUR tenant, inserted directly and not through the API.

    Deliberate, and the reason is not convenience: `get_authenticated_request` calls
    `bind_session_to_tenant` on the session, and these tests share ONE session across every
    request. A first call as tenant B would bind it to B, and the next call as tenant A would
    then fail to load its own user and answer `401` instead of the `404` under test. Seeding the
    row directly keeps the binding to the tenant whose isolation is being probed —
    `tests/reservations/conftest.py` does the same for the same reason.
    """
    prop = PropertyModel(
        tenant_id=tenant_b.id,
        name="Pajaritos 8",
        internal_code="PAJARITOS8",
        max_guests=2,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


@pytest.fixture
def create_payload():
    """The minimum body PRD §27 implies, plus overrides.

    Only `name` and `internal_code` are required by the schema; §27's seed rows carry the address
    and the occupancy, so the default here matches what a real caller would send.
    """

    def _payload(**overrides):
        payload = {
            "name": "Redes 11",
            "internal_code": "REDES11",
            "address_line1": "Calle Redes 11",
            "city": "Madrid",
            "province": "Madrid",
            "max_guests": 4,
            "bedrooms": 2,
            "bathrooms": 1,
        }
        payload.update(overrides)
        return payload

    return _payload
