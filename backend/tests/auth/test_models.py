import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.infrastructure.models import PasswordResetTokenModel, UserModel
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


# --- `auth-account-recovery` R4.1, R5.1 --------------------------------------------


async def _tenant_and_user(db_session) -> tuple[TenantModel, UserModel]:
    tenant = TenantModel(name="Owner", billing_email=f"o-{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    user = UserModel(
        tenant_id=tenant.id,
        name="Ana",
        email=f"ana-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        role="TENANT_OWNER",
    )
    db_session.add(user)
    await db_session.flush()
    return tenant, user


@pytest.mark.asyncio
async def test_a_user_does_not_owe_a_password_change_by_default(db_session) -> None:
    """R5.1: the column arrives with `server_default false`, so no deployment locks anybody
    out and existing accounts keep behaving exactly as before."""
    _tenant, user = await _tenant_and_user(db_session)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(UserModel).where(UserModel.id == user.id))
    ).scalar_one()
    assert fetched.must_change_password is False


@pytest.mark.asyncio
async def test_a_reset_token_roundtrips(db_session) -> None:
    tenant, user = await _tenant_and_user(db_session)
    token = PasswordResetTokenModel(
        tenant_id=tenant.id,
        user_id=user.id,
        token_hash="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(token)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.id == token.id)
        )
    ).scalar_one()
    assert fetched.token_hash == "a" * 64
    assert fetched.used_at is None
    assert fetched.revoked_at is None


@pytest.mark.asyncio
async def test_a_token_hash_is_unique_across_the_whole_installation(db_session) -> None:
    """The UNIQUE index is what makes the conditional UPDATE of design D1 address at most
    one row, so `rowcount` is a decision rather than a count."""
    tenant, user = await _tenant_and_user(db_session)
    expires = datetime.now(UTC) + timedelta(minutes=30)
    db_session.add(
        PasswordResetTokenModel(
            tenant_id=tenant.id, user_id=user.id, token_hash="b" * 64, expires_at=expires
        )
    )
    await db_session.commit()

    db_session.add(
        PasswordResetTokenModel(
            tenant_id=tenant.id, user_id=user.id, token_hash="b" * 64, expires_at=expires
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


def test_the_reset_token_table_is_covered_by_the_global_tenant_filter() -> None:
    """Regla 1 of `steering/security.md`. The consuming query is deliberately unscoped
    (design D3), so it matters that every OTHER access to this table is caught by the net."""
    from app.core.db import tenant_scoped_classes

    assert "password_reset_tokens" in {
        entity.__tablename__ for entity in tenant_scoped_classes()
    }
