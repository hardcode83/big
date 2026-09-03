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
