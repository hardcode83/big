"""Fixtures for the platform API tests.

Re-registers the fixtures of `tests/auth/conftest.py` so this package has access to the
two-tenant fixture pair, the `auth_header` helper, and the `api` client. The section-4
tests need a `super_admin` token; the auth conftest does not yet expose one (section 5
will add it), so the helper `super_admin_user` here seeds one inline using the same
pattern the section-2 and section-3 integration tests use.
"""

from tests.auth.conftest import (  # noqa: F401
    PASSWORD,
    TEST_BCRYPT_ROUNDS,
    api,
    auth_header,
    hasher,
    insert_tenant,
    insert_user,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

from app.auth.domain.enums import UserRole  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
import uuid  # noqa: E402


@pytest_asyncio.fixture
async def super_admin(db_session: AsyncSession):
    """A `SUPER_ADMIN` user the platform tests authenticate as (R5, R6.1).

    Inline seed rather than a fixture in `tests/auth/conftest.py` because the
    `super_admin` fixture is section 5's scope, per the section-1/2/3 implementation notes.
    The seeded row uses `tenant=None`, the contract `super-admin-identity` R1.1 declares
    and the database enforces with `ck_users_super_admin_tenant_id_null`.
    """
    return await insert_user(
        db_session,
        tenant=None,
        role=UserRole.SUPER_ADMIN,
    )


@pytest_asyncio.fixture
async def api_session_per_request(test_engine):
    """A client whose every request gets its OWN session on its OWN connection.

    The suite's default `api` fixture hands every request of a test the SAME
    `db_session` (see `request_session_override` in `tests/conftest.py`, which explains
    why: flushed-but-uncommitted setup rows have to stay visible to the app, and
    session-per-request would red 249 tests in `auth` and `cleaning` alone).

    That sharing is precisely what makes a concurrency test impossible on `api`: two
    requests on one session are one transaction on one connection, so the second INSERT
    cannot race the first — it just sees it. Here each request opens its own session, so
    two `asyncio.gather`-ed requests are two transactions on two connections, and the
    `uq_tenants_name` index is what arbitrates between them.

    The cost of the swap is paid by the test that asks for it: setup rows must be
    COMMITTED before the requests run, or the per-request sessions will not see them.
    Scoped to this package on purpose — it is not a replacement for `api`.
    """
    from httpx import ASGITransport, AsyncClient

    from app.auth.api.dependencies import (
        get_login_throttle,
        get_password_hasher,
        get_token_codec,
    )
    from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
    from app.auth.infrastructure.token_codec import JwtTokenCodec
    from app.core.db import get_db_session
    from app.main import create_app
    from tests.auth.doubles import UnlimitedLoginThrottle

    app = create_app()
    codec = JwtTokenCodec(secret="u" * 64, access_minutes=15, refresh_days=7)

    async def _session_per_request():
        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db_session] = _session_per_request
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_login_throttle] = lambda: UnlimitedLoginThrottle()
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        yield client
