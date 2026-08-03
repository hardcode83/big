"""Fixtures for the integration tests: the real app, two tenants, and seed properties.

The property codes match `MockPMSAdapter`'s expectations (`PMS-REDES11`) so the sync has
something to resolve, and the `internal_code` is the one a person would type into a CSV.
"""

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.integrations.infrastructure.mock_pms import SEED_PROPERTY_CODE
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

SECRET = "i" * 64

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "channex"


def channex_fixture(name: str) -> dict:
    """Load a payload captured from the real Channex staging API (task 2.5).

    The first on-disk fixture directory in this repo — the CSV tests build their content
    inline, which stops being readable at the size of a real booking payload. These files come
    from `scripts/channex_probe.py`, which anonymises at capture time (R4.2), so what is
    versioned here has never contained personal data.

    Reading them is what keeps the mapping tests offline (R2.5) while still asserting against
    field names the provider really uses, rather than the ones its documentation claims.
    """
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def channex_booking(*, ota_name: str) -> dict:
    """One booking element from the captured collection, picked by its OTA.

    Two were seeded on purpose (`scripts/channex_bootstrap.py`): `Booking.com`, which reports
    a commission, and `Offline`, which does not — the two branches R2.6 has to tell apart.
    """
    for row in channex_fixture("bookings")["data"]:
        if (row.get("attributes") or {}).get("ota_name") == ota_name:
            return row
    raise AssertionError(f"no captured booking for ota_name={ota_name!r}")


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
        pms_external_id=SEED_PROPERTY_CODE,
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
