import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.tenants.infrastructure.models import TenantConfigModel, TenantModel


@pytest.mark.asyncio
async def test_tenant_and_tenant_config_roundtrip(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    config = TenantConfigModel(tenant_id=tenant.id)
    db_session.add(config)
    await db_session.commit()

    result = await db_session.execute(select(TenantModel).where(TenantModel.id == tenant.id))
    fetched = result.scalar_one()
    assert fetched.name == "Owner A"
    assert fetched.status.value == "ACTIVE"

    result = await db_session.execute(
        select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant.id)
    )
    fetched_config = result.scalar_one()
    assert fetched_config.storage_type.value == "LOCAL"


@pytest.mark.asyncio
async def test_tenant_config_tenant_id_is_unique(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    db_session.add(TenantConfigModel(tenant_id=tenant.id))
    await db_session.commit()

    db_session.add(TenantConfigModel(tenant_id=tenant.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
