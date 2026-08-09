"""Shared auth fixtures: two tenants and a user per role in each.

Two tenants are the default rather than an extra, because the tenant-isolation
tests (R4.4) need a neighbour to fail to reach.
"""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.tenants.domain.enums import TenantStatus
from app.tenants.infrastructure.models import TenantModel

# Cheap rounds on purpose: the real default of 12 would dominate the suite runtime.
TEST_BCRYPT_ROUNDS = 4
PASSWORD = "correct horse battery staple"


@pytest.fixture
def hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher(rounds=TEST_BCRYPT_ROUNDS)


async def insert_tenant(
    session: AsyncSession, *, name: str | None = None, status: TenantStatus = TenantStatus.ACTIVE
) -> TenantModel:
    tenant = TenantModel(
        id=uuid.uuid4(),
        name=name or f"tenant-{uuid.uuid4().hex[:8]}",
        billing_email="ops@example.com",
        status=status,
    )
    session.add(tenant)
    await session.flush()
    return tenant


async def insert_user(
    session: AsyncSession,
    *,
    tenant: TenantModel,
    role: UserRole = UserRole.PROPERTY_MANAGER,
    email: str | None = None,
    password: str = PASSWORD,
    status: UserStatus = UserStatus.ACTIVE,
    hasher: BcryptPasswordHasher | None = None,
    normalize: bool = True,
    preferred_language: str = "es",
) -> UserModel:
    """Creates a user the way production does: with the email normalised (D19).

    `normalize=False` writes the address verbatim, to exercise what happens when a
    writer forgets — which is what `uq_users_lower_email` has to catch.

    Addresses default to a random one per user because emails are unique across the
    WHOLE installation now (design D16, ADR 0005): a fixed default would make any
    test that seeds two users collide, in a different tenant just as much as in the
    same one.
    """
    raw_email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Test User",
        email=normalize_email(raw_email) if normalize else raw_email,
        password_hash=await (hasher or BcryptPasswordHasher(rounds=TEST_BCRYPT_ROUNDS)).hash(
            password
        ),
        role=role,
        status=status,
        preferred_language=preferred_language,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def tenant_a(db_session: AsyncSession) -> TenantModel:
    return await insert_tenant(db_session, name="tenant-a")


@pytest_asyncio.fixture
async def tenant_b(db_session: AsyncSession) -> TenantModel:
    return await insert_tenant(db_session, name="tenant-b")


@pytest_asyncio.fixture
async def users_by_role_a(db_session: AsyncSession, tenant_a: TenantModel) -> dict:
    return {
        role: await insert_user(db_session, tenant=tenant_a, role=role) for role in UserRole
    }


@pytest_asyncio.fixture
async def users_by_role_b(db_session: AsyncSession, tenant_b: TenantModel) -> dict:
    return {
        role: await insert_user(db_session, tenant=tenant_b, role=role) for role in UserRole
    }


def utc_now() -> datetime:
    return datetime.now(UTC)


# --- shared API fixture (added by `user-management`) --------------------------------
#
# `tests/auth/test_api.py` keeps its own `api` fixture, which shadows this one for that
# module: it needs an in-memory throttle to exercise the login limits. This one is for the
# administration endpoints, where the throttle is irrelevant and the real Redis adapter would
# be an unnecessary dependency of every test.


@pytest_asyncio.fixture
async def api(db_session):
    """The real app with only the outermost adapters swapped for test ones."""
    from httpx import ASGITransport, AsyncClient

    from app.auth.api.dependencies import (
        get_login_throttle,
        get_password_hasher,
        get_token_codec,
    )
    from app.auth.infrastructure.token_codec import JwtTokenCodec
    from app.core.db import get_db_session
    from app.main import create_app
    from tests.auth.doubles import UnlimitedLoginThrottle

    app = create_app()
    codec = JwtTokenCodec(secret="u" * 64, access_minutes=15, refresh_days=7)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_login_throttle] = lambda: UnlimitedLoginThrottle()
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        yield client


def auth_header(client, user) -> dict[str, str]:
    """A real access token for `user`, issued by the same codec the app verifies with."""
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    return {"Authorization": f"Bearer {token}"}
