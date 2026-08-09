"""Fixtures for the access tests.

Same arrangement as `tests/cleaning/conftest.py`: reuse `tests/auth/conftest.py`, which seeds
a user per role in two tenants. The neighbour tenant is not optional — an isolation test with
nothing to fail to reach proves nothing (DoD §28.18).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.access.infrastructure.models import AccessRecordModel
from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.main import create_app
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "e" * 64


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


async def insert_property(session, tenant, *, code="REDES11") -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant.id,
        name=f"Property {code}",
        internal_code=code,
        pms_external_id=f"PMS-{code}-{uuid.uuid4().hex[:6]}",
        max_guests=4,
    )
    session.add(prop)
    await session.flush()
    return prop


async def insert_reservation(
    session, tenant, prop, *, status=ReservationStatus.CONFIRMED, days_ahead=3
) -> ReservationModel:
    check_in = datetime.now(UTC).date() + timedelta(days=days_ahead)
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        status=status,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=2),
        nights=2,
    )
    session.add(reservation)
    await session.flush()
    return reservation


async def insert_access_record(
    session, tenant, prop, *, reservation=None, status=None, valid_to=None
) -> AccessRecordModel:
    from app.access.domain.enums import AccessRecordStatus

    record = AccessRecordModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        reservation_id=reservation.id if reservation is not None else None,
        status=status or AccessRecordStatus.PENDING,
        valid_to=valid_to,
    )
    session.add(record)
    await session.flush()
    return record


@pytest_asyncio.fixture
async def property_a(db_session, tenant_a) -> PropertyModel:
    return await insert_property(db_session, tenant_a, code="REDES11")


@pytest_asyncio.fixture
async def property_b(db_session, tenant_b) -> PropertyModel:
    return await insert_property(db_session, tenant_b, code="PAJARITOS8")
