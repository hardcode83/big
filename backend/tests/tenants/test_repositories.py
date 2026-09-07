"""Integration tests for the tenants adapters (R5.1, R5.7, design D13).

Against real Postgres, because what is being checked is the upsert of a missing configuration
row and which columns the adapters refuse to write.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_session_to_tenant
from app.core.tenancy import TenantMarkedSessionError
from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.enums import StorageType, TenantStatus
from app.tenants.domain.exceptions import TenantAlreadyExistsError
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
@pytest.mark.asyncio
async def test_checkin_window_hours_reads_the_tenants_own_value(db_session) -> None:
    tenant = await insert_tenant(db_session, name="MAGNO")
    repo = SqlAlchemyTenantConfigRepository(db_session)
    await repo.get_or_create(tenant.id, utc_now())
    await repo.apply_changes(tenant.id, {"checkin_window_hours_before": 7})

    assert await repo.checkin_window_hours(tenant.id) == 7

@pytest.mark.asyncio
async def test_checkin_window_hours_defaults_without_a_row_and_writes_nothing(db_session) -> None:
    """The reason this method exists: a `GET` must not create the configuration row.

    `get_or_create` would insert one here, which on `GET /api/v1/blocked-transitions` is a write
    performed by a role that does not hold `MANAGE_TENANT_SETTINGS` (design D5).
    """
    tenant = await insert_tenant(db_session, name="MAGNO", with_notification_config=False)
    repo = SqlAlchemyTenantConfigRepository(db_session)

    hours = await repo.checkin_window_hours(tenant.id)

    assert hours == 2
    rows = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert rows == []

@pytest.mark.asyncio
async def test_checkin_window_hours_never_reads_another_tenants_configuration(db_session) -> None:
    """Rule 1 of `steering/security.md`, on the fourth read of the blocked-transitions endpoint.

    Only the neighbour has a row, and theirs is not the default. Without the tenant predicate this
    tenant would compute its check-in window from someone else's settings — a cross-tenant value
    silently steering its own operational output, which is worse than a visible leak.
    """
    mine = await insert_tenant(db_session, name="MAGNO")
    theirs = await insert_tenant(db_session, name="NEIGHBOUR")
    repo = SqlAlchemyTenantConfigRepository(db_session)
    await repo.get_or_create(theirs.id, utc_now())
    await repo.apply_changes(theirs.id, {"checkin_window_hours_before": 9})

    assert await repo.checkin_window_hours(mine.id) == 2


# --- `add` (R1.2, R-2) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_persists_both_rows_for_a_free_name(db_session) -> None:
    """Happy path: a free name writes one `tenants` row and one `tenant_configs` row."""
    now = utc_now()
    tenant = Tenant.create(
        name="Magno", billing_email="ops@magno.example", now=now
    )
    config = TenantConfig.with_defaults(tenant_id=tenant.id, now=now)
    repo = SqlAlchemyTenantRepository(db_session)

    await repo.add(tenant, config)

    tenant_row = (
        await db_session.execute(
            select(TenantModel).where(TenantModel.id == tenant.id)
        )
    ).scalar_one()
    assert tenant_row.name == "Magno"
    assert tenant_row.status is TenantStatus.ACTIVE

    config_row = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant.id)
        )
    ).scalar_one()
    assert config_row.id == config.id
    assert config_row.owner_approval_threshold_eur == Decimal("100.00")


@pytest.mark.asyncio
async def test_add_translates_a_duplicate_name_into_TenantAlreadyExistsError(
    db_session,
) -> None:
    """R-2: the unique constraint the migration introduces maps to a domain error.

    The first `add` succeeds; the second, with a tenant that reuses the same name, must
    raise `TenantAlreadyExistsError` — and only one row of either kind may remain. The
    `db_session` rolls back automatically, but the assertion about a single row is what
    proves the violation was caught at flush time, not at commit time (which is what the
    repository's explicit `flush` exists to make observable here).
    """
    now = utc_now()
    existing = await insert_tenant(db_session, name="Magno")
    # Commit the seed before exercising `add`: a failure inside `add` will roll the
    # whole transaction back otherwise, and the post-rollback count would see nothing.
    await db_session.commit()
    repo = SqlAlchemyTenantRepository(db_session)

    duplicate = Tenant.create(
        name="Magno", billing_email="other@magno.example", now=now
    )
    duplicate_config = TenantConfig.with_defaults(tenant_id=duplicate.id, now=now)

    with pytest.raises(TenantAlreadyExistsError):
        await repo.add(duplicate, duplicate_config)
    await db_session.rollback()

    rows = (
        await db_session.execute(
            select(TenantModel).where(TenantModel.name == "Magno")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == existing.id


@pytest.mark.asyncio
async def test_add_does_not_translate_unrelated_integrity_errors(db_session) -> None:
    """A bad foreign key on the configuration is a programmer error, not a domain conflict.

    The repository's contract is "this name is free"; shielding the database from every
    failure mode would map a programming mistake into a `409` the router cannot justify,
    which is the kind of mapping the section-3 panel would catch. The `IntegrityError`
    re-raises untouched, with a config whose `tenant_id` points at a row that does not exist.
    """
    now = utc_now()
    tenant = Tenant.create(
        name="Orphan", billing_email="ops@orphan.example", now=now
    )
    # Hand the repository a config whose `tenant_id` does NOT match the tenant we are
    # adding — Postgres rejects the FK at flush time.
    bad_config = TenantConfig.with_defaults(
        tenant_id=uuid.uuid4(), now=now
    )
    repo = SqlAlchemyTenantRepository(db_session)

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await repo.add(tenant, bad_config)


# --- list_page (super-admin-console R2.1-R2.3) --------------------------------------

async def _seed_tenant_at(
    db_session: AsyncSession, *, name: str, created_at: datetime
) -> TenantModel:
    """A tenant + its config, `created_at` pinned so ordering assertions do not race `now()`.

    `TenantModel.created_at` is `server_default=func.now()`: two tenants inserted in the
    same transaction — the common case with this suite's shared `db_session` — would
    otherwise get the SAME timestamp (Postgres' `now()` is transaction-time, not
    statement-time), leaving `created_at DESC` undefined between them. Passing
    `created_at` explicitly overrides the server default the same way any mapped column
    can be set at construction time.
    """
    tenant = TenantModel(
        id=uuid.uuid4(),
        name=name,
        billing_email=f"{name.lower()}@example.com",
        status=TenantStatus.ACTIVE,
        created_at=created_at,
    )
    db_session.add(tenant)
    await db_session.flush()
    db_session.add(TenantConfigModel(tenant_id=tenant.id))
    await db_session.flush()
    return tenant


@pytest.mark.asyncio
async def test_list_page_on_an_empty_table_returns_no_rows_and_zero_total(
    db_session,
) -> None:
    repo = SqlAlchemyTenantRepository(db_session)

    rows, total = await repo.list_page(page=1, per_page=20)

    assert rows == ()
    assert total == 0


@pytest.mark.asyncio
async def test_list_page_orders_by_created_at_descending_with_the_right_total(
    db_session,
) -> None:
    base = utc_now()
    oldest = await _seed_tenant_at(db_session, name="Oldest", created_at=base)
    middle = await _seed_tenant_at(
        db_session, name="Middle", created_at=base + timedelta(minutes=1)
    )
    newest = await _seed_tenant_at(
        db_session, name="Newest", created_at=base + timedelta(minutes=2)
    )
    repo = SqlAlchemyTenantRepository(db_session)

    rows, total = await repo.list_page(page=1, per_page=20)

    assert total == 3
    assert [tenant.id for tenant, _config in rows] == [
        newest.id,
        middle.id,
        oldest.id,
    ]
    # Each row is paired with its own configuration, not a placeholder.
    assert all(config.tenant_id == tenant.id for tenant, config in rows)


@pytest.mark.asyncio
async def test_list_page_slices_by_page_and_per_page(db_session) -> None:
    base = utc_now()
    seeded = [
        await _seed_tenant_at(
            db_session, name=f"Tenant{i}", created_at=base + timedelta(minutes=i)
        )
        for i in range(5)
    ]
    expected_order = [tenant.id for tenant in reversed(seeded)]
    repo = SqlAlchemyTenantRepository(db_session)

    first_page, total = await repo.list_page(page=1, per_page=2)
    second_page, _ = await repo.list_page(page=2, per_page=2)
    third_page, _ = await repo.list_page(page=3, per_page=2)

    assert total == 5
    assert [tenant.id for tenant, _config in first_page] == expected_order[0:2]
    assert [tenant.id for tenant, _config in second_page] == expected_order[2:4]
    assert [tenant.id for tenant, _config in third_page] == expected_order[4:5]


@pytest.mark.asyncio
async def test_list_page_refuses_a_marked_session(db_session, tenant_a) -> None:
    """`list_page` joins `tenant_configs`, which DOES carry a `tenant_id` column (unlike
    `tenants` itself) — on a marked session the global filter would silently narrow that
    side of the join to one tenant instead of raising, which is indistinguishable from a
    legitimately short page. Asserting the raise, not the rows, for the same reason
    `test_find_by_email_globally_refuses_a_marked_session` does.
    """
    await _seed_tenant_at(db_session, name="Seeded", created_at=utc_now())
    bind_session_to_tenant(db_session, tenant_a.id)
    repo = SqlAlchemyTenantRepository(db_session)

    with pytest.raises(TenantMarkedSessionError, match="list_page"):
        await repo.list_page(page=1, per_page=20)
