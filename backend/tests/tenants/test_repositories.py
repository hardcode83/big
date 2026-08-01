"""Integration tests for the tenants adapters (R5.1, R5.7, design D13).

Against real Postgres, because what is being checked is the upsert of a missing configuration
row and which columns the adapters refuse to write.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.tenants.domain.enums import StorageType, TenantStatus
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from app.tenants.infrastructure.repositories import (
    SqlAlchemyTenantConfigRepository,
    SqlAlchemyTenantRepository,
)
from tests.auth.conftest import insert_tenant


def utc_now() -> datetime:
    return datetime.now(UTC)


@pytest.mark.asyncio
async def test_a_tenant_round_trips(db_session) -> None:
    tenant = await insert_tenant(db_session, name="MAGNO")
    repo = SqlAlchemyTenantRepository(db_session)

    found = await repo.get(tenant.id)

    assert found is not None
    assert (found.id, found.name, found.status) == (tenant.id, "MAGNO", TenantStatus.ACTIVE)


@pytest.mark.asyncio
async def test_an_unknown_tenant_is_none(db_session) -> None:
    repo = SqlAlchemyTenantRepository(db_session)

    assert await repo.get(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_applying_changes_writes_only_the_named_columns(db_session) -> None:
    tenant = await insert_tenant(db_session, name="MAGNO")
    repo = SqlAlchemyTenantRepository(db_session)

    await repo.apply_changes(tenant.id, {"name": "MAGNO SL"})

    found = await repo.get(tenant.id)
    assert found is not None
    assert found.name == "MAGNO SL"
    assert found.timezone == "Europe/Madrid"  # untouched


@pytest.mark.asyncio
async def test_the_status_of_a_tenant_is_not_writable(db_session) -> None:
    """R5.3, enforced at the adapter as well as at the entity."""
    tenant = await insert_tenant(db_session)
    repo = SqlAlchemyTenantRepository(db_session)

    with pytest.raises(ValueError):
        await repo.apply_changes(tenant.id, {"status": TenantStatus.SUSPENDED})

    row = (
        await db_session.execute(select(TenantModel).where(TenantModel.id == tenant.id))
    ).scalar_one()
    assert row.status is TenantStatus.ACTIVE


@pytest.mark.asyncio
async def test_applying_changes_to_an_unknown_tenant_fails_loudly(db_session) -> None:
    repo = SqlAlchemyTenantRepository(db_session)

    with pytest.raises(ValueError):
        await repo.apply_changes(uuid.uuid4(), {"name": "Ghost"})


@pytest.mark.asyncio
async def test_the_config_is_created_with_its_defaults_when_missing(db_session) -> None:
    """R5.7: the API must not depend on the bootstrap having created the row."""
    tenant = await insert_tenant(db_session)
    repo = SqlAlchemyTenantConfigRepository(db_session)

    config = await repo.get_or_create(tenant.id, utc_now())

    assert config.tenant_id == tenant.id
    assert config.owner_approval_threshold_eur == Decimal("100.00")
    assert config.storage_type is StorageType.LOCAL
    stored = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant.id)
        )
    ).scalar_one()
    assert stored.id == config.id


@pytest.mark.asyncio
async def test_the_config_is_returned_when_it_already_exists(db_session) -> None:
    tenant = await insert_tenant(db_session)
    repo = SqlAlchemyTenantConfigRepository(db_session)
    first = await repo.get_or_create(tenant.id, utc_now())

    second = await repo.get_or_create(tenant.id, utc_now())

    assert second.id == first.id
    rows = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_config_changes_write_only_the_named_columns(db_session) -> None:
    tenant = await insert_tenant(db_session)
    repo = SqlAlchemyTenantConfigRepository(db_session)
    await repo.get_or_create(tenant.id, utc_now())

    await repo.apply_changes(tenant.id, {"sla_high_minutes": 45})

    config = await repo.get_or_create(tenant.id, utc_now())
    assert config.sla_high_minutes == 45
    assert config.sla_critical_minutes == 5  # untouched


@pytest.mark.asyncio
async def test_the_storage_type_is_not_writable(db_session) -> None:
    """R5.4: switching it points already-uploaded photos at a backend without them."""
    tenant = await insert_tenant(db_session)
    repo = SqlAlchemyTenantConfigRepository(db_session)
    await repo.get_or_create(tenant.id, utc_now())

    with pytest.raises(ValueError):
        await repo.apply_changes(tenant.id, {"storage_type": StorageType.S3})


@pytest.mark.asyncio
async def test_a_decimal_threshold_round_trips_without_losing_precision(db_session) -> None:
    tenant = await insert_tenant(db_session)
    repo = SqlAlchemyTenantConfigRepository(db_session)
    await repo.get_or_create(tenant.id, utc_now())

    await repo.apply_changes(
        tenant.id,
        {
            "owner_approval_threshold_eur": Decimal("250.50"),
            "ai_confidence_threshold": Decimal("0.90"),
        },
    )

    config = await repo.get_or_create(tenant.id, utc_now())
    assert config.owner_approval_threshold_eur == Decimal("250.50")
    assert config.ai_confidence_threshold == Decimal("0.90")


@pytest.mark.asyncio
async def test_neither_adapter_commits(db_session) -> None:
    """R6.4: the change and its audit row must roll back together."""
    tenant = await insert_tenant(db_session)
    tenants = SqlAlchemyTenantRepository(db_session)
    configs = SqlAlchemyTenantConfigRepository(db_session)
    await configs.get_or_create(tenant.id, utc_now())

    await tenants.apply_changes(tenant.id, {"name": "Rolled back"})
    await db_session.rollback()

    assert (
        await db_session.execute(select(TenantModel).where(TenantModel.id == tenant.id))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_two_tenants_keep_their_own_configuration(db_session) -> None:
    first = await insert_tenant(db_session, name="first")
    second = await insert_tenant(db_session, name="second")
    repo = SqlAlchemyTenantConfigRepository(db_session)
    await repo.get_or_create(first.id, utc_now())
    await repo.get_or_create(second.id, utc_now())

    await repo.apply_changes(first.id, {"sla_high_minutes": 45})

    assert (await repo.get_or_create(first.id, utc_now())).sla_high_minutes == 45
    assert (await repo.get_or_create(second.id, utc_now())).sla_high_minutes == 15
