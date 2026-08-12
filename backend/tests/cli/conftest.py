"""A tenant that `make bootstrap` has already prepared — the seed's precondition (R1.3)."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.enums import UserRole
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.tenants.infrastructure.models import TenantModel
from tests.auth.conftest import insert_tenant, insert_user
from tests.conftest import TEST_BCRYPT_ROUNDS

BOOTSTRAPPED_TENANT_NAME = "Adamar Inmuebles"


@pytest.fixture
def hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher(rounds=TEST_BCRYPT_ROUNDS)


@pytest_asyncio.fixture
async def bootstrapped_tenant(db_session: AsyncSession) -> TenantModel:
    """What `make bootstrap` leaves behind: the tenant and its two administrative accounts.

    Their addresses are deliberately NOT the ones PRD §27 lists — the seed resolves them by
    role, and a fixture that used §27's addresses would let a lookup by email pass (design D4).
    """
    tenant = await insert_tenant(db_session, name=BOOTSTRAPPED_TENANT_NAME)
    await insert_user(
        db_session, tenant=tenant, role=UserRole.TENANT_OWNER, email="chosen-owner@example.com"
    )
    await insert_user(
        db_session,
        tenant=tenant,
        role=UserRole.PROPERTY_MANAGER,
        email="chosen-manager@example.com",
    )
    await db_session.flush()
    return tenant
