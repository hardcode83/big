import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.infrastructure.models import UserModel
from app.tenants.infrastructure.models import TenantModel


@pytest.mark.asyncio
async def test_user_roundtrip(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    user = UserModel(
        tenant_id=tenant.id,
        name="Manager",
        email="manager@example.com",
        password_hash="hashed",
        role="PROPERTY_MANAGER",
    )
    db_session.add(user)
    await db_session.commit()

    result = await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    fetched = result.scalar_one()
    assert fetched.email == "manager@example.com"
    assert fetched.status.value == "ACTIVE"


@pytest.mark.asyncio
async def test_user_email_unique_per_tenant_but_reusable_across_tenants(db_session) -> None:
    tenant_a = TenantModel(name="Owner A", billing_email="a@example.com")
    tenant_b = TenantModel(name="Owner B", billing_email="b@example.com")
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    db_session.add(
        UserModel(
            tenant_id=tenant_a.id,
            name="Manager",
            email="shared@example.com",
            password_hash="hashed",
            role="PROPERTY_MANAGER",
        )
    )
    await db_session.commit()

    # Same email, different tenant: allowed.
    db_session.add(
        UserModel(
            tenant_id=tenant_b.id,
            name="Manager B",
            email="shared@example.com",
            password_hash="hashed",
            role="PROPERTY_MANAGER",
        )
    )
    await db_session.commit()

    # Same email, same tenant: rejected.
    db_session.add(
        UserModel(
            tenant_id=tenant_a.id,
            name="Manager duplicate",
            email="shared@example.com",
            password_hash="hashed",
            role="CLEANER",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
