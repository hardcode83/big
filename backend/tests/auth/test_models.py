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
async def test_user_email_is_unique_across_the_whole_installation(db_session) -> None:
    """Deliberate deviation from PRD §7.3's UNIQUE(tenant_id, email) — ADR 0005.

    Login takes an email and nothing else, so per-tenant uniqueness would mean the
    address does not identify the account: an admin of tenant B could create a user
    with the address of tenant A's owner and lock that owner out of a product with no
    unlock endpoint. The guarantee is in the database, not in application code,
    because a Python-side check is only as good as every future writer remembering it.
    """
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

    # Same email, DIFFERENT tenant: rejected too. This is the case PRD §7.3 allowed.
    db_session.add(
        UserModel(
            tenant_id=tenant_b.id,
            name="Manager B",
            email="shared@example.com",
            password_hash="hashed",
            role="PROPERTY_MANAGER",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_the_uniqueness_of_an_email_ignores_its_case(db_session) -> None:
    """The index is on `lower(email)`, so case variants cannot smuggle a duplicate in.

    A case-SENSITIVE unique index would leave `Jose@x.com` and `jose@x.com` coexisting
    while the login lookup treats them as one address — which is the lockout above
    with an extra step, not a different bug (design D19).
    """
    tenant_a = TenantModel(name="Owner A", billing_email="a@example.com")
    tenant_b = TenantModel(name="Owner B", billing_email="b@example.com")
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    db_session.add(
        UserModel(
            tenant_id=tenant_a.id,
            name="Manager",
            email="clash@example.com",
            password_hash="hashed",
            role="PROPERTY_MANAGER",
        )
    )
    await db_session.commit()

    db_session.add(
        UserModel(
            tenant_id=tenant_b.id,
            name="Manager B",
            email="Clash@Example.COM",
            password_hash="hashed",
            role="PROPERTY_MANAGER",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
