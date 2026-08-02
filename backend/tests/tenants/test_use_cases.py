"""The two tenant use cases, against in-memory fakes (R5, design D12, D13, D15)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.audit.domain import actions
from app.tenants.application.use_cases import (
    GetTenantSettingsUseCase,
    UpdateTenantSettingsUseCase,
)
from app.tenants.domain.entities import Tenant, TenantConfig
from app.tenants.domain.exceptions import TenantNotFoundError, TenantValidationError
from tests.auth.doubles import FakeAuditLogRepository, FakeUnitOfWork

TENANT = uuid.uuid4()
ACTOR = uuid.uuid4()
IP = "203.0.113.8"


def utc_now() -> datetime:
    return datetime.now(UTC)


class FakeTenantRepository:
    def __init__(self, tenant: Tenant | None) -> None:
        self._tenant = tenant
        self.applied: list[tuple] = []

    async def get(self, tenant_id):
        return self._tenant if self._tenant and self._tenant.id == tenant_id else None

    async def apply_changes(self, tenant_id, values):
        self.applied.append((tenant_id, dict(values)))


class FakeTenantConfigRepository:
    def __init__(self, config: TenantConfig | None = None) -> None:
        self._config = config
        self.applied: list[tuple] = []
        self.created = 0

    async def get_or_create(self, tenant_id, now):
        if self._config is None:
            self._config = TenantConfig.with_defaults(tenant_id=tenant_id, now=now)
            self.created += 1
        return self._config

    async def apply_changes(self, tenant_id, values):
        self.applied.append((tenant_id, dict(values)))


def _tenant(**overrides) -> Tenant:
    now = utc_now()
    values = {
        "id": TENANT,
        "name": "MAGNO",
        "billing_email": "billing@example.com",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Tenant(**values)


@pytest.fixture
def ports():
    return {
        "tenants": FakeTenantRepository(_tenant()),
        "configs": FakeTenantConfigRepository(),
        "audit": FakeAuditLogRepository(),
        "uow": FakeUnitOfWork(),
    }


def _get(ports) -> GetTenantSettingsUseCase:
    return GetTenantSettingsUseCase(tenants=ports["tenants"], configs=ports["configs"])


def _update(ports) -> UpdateTenantSettingsUseCase:
    return UpdateTenantSettingsUseCase(
        tenants=ports["tenants"],
        configs=ports["configs"],
        audit=ports["audit"],
        uow=ports["uow"],
    )


# --- read (R5.1, R5.7, R7.9) -------------------------------------------------------


@pytest.mark.asyncio
async def test_reading_returns_the_tenant_with_its_config(ports) -> None:
    settings = await _get(ports).execute(
        tenant_id=TENANT, requested_id=TENANT, now=utc_now()
    )

    assert settings.tenant.id == TENANT
    assert settings.config.owner_approval_threshold_eur == Decimal("100.00")


@pytest.mark.asyncio
async def test_a_missing_config_is_created_with_its_defaults(ports) -> None:
    """R5.7: the API does not depend on the bootstrap having created the row."""
    await _get(ports).execute(tenant_id=TENANT, requested_id=TENANT, now=utc_now())

    assert ports["configs"].created == 1


@pytest.mark.asyncio
async def test_asking_for_another_tenant_is_a_not_found(ports) -> None:
    """R7.9 / design D12: `404` and not `403`, so the answer never confirms it exists."""
    with pytest.raises(TenantNotFoundError):
        await _get(ports).execute(
            tenant_id=TENANT, requested_id=uuid.uuid4(), now=utc_now()
        )


@pytest.mark.asyncio
async def test_the_check_happens_before_any_query(ports) -> None:
    """`tenants` is not covered by the global session filter, so the order matters.

    A repository that answered for any id would leak the neighbour's data if the comparison
    ran afterwards. Here the repository is deliberately given a DIFFERENT tenant, so if the
    comparison were skipped the use case would happily return it.
    """
    ports["tenants"] = FakeTenantRepository(_tenant(id=uuid.uuid4(), name="Somebody else"))

    with pytest.raises(TenantNotFoundError):
        await _get(ports).execute(
            tenant_id=TENANT, requested_id=uuid.uuid4(), now=utc_now()
        )


# --- update (R5.2, R5.5, R5.8) -----------------------------------------------------


@pytest.mark.asyncio
async def test_updating_the_tenant_writes_and_audits_it(ports) -> None:
    await _update(ports).execute(
        tenant_id=TENANT,
        requested_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        tenant_changes={"name": "MAGNO SL"},
        config_changes={},
        now=utc_now(),
    )

    assert ports["tenants"].applied[0][1] == {"name": "MAGNO SL"}
    entry = ports["audit"].entries[0][1]
    assert entry.action == actions.TENANT_UPDATED
    assert entry.entity_type == actions.ENTITY_TENANT
    assert entry.changes["name"] == {"old": "MAGNO", "new": "MAGNO SL"}
    assert ports["uow"].commits == 1


@pytest.mark.asyncio
async def test_updating_the_config_audits_it_separately(ports) -> None:
    """Two entities, two rows: `entity_id` points at one row and cannot name both."""
    await _update(ports).execute(
        tenant_id=TENANT,
        requested_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        tenant_changes={"name": "MAGNO SL"},
        config_changes={"sla_high_minutes": 30},
        now=utc_now(),
    )

    actions_written = [entry.action for _, entry in ports["audit"].entries]
    assert actions_written == [actions.TENANT_UPDATED, actions.TENANT_CONFIG_UPDATED]
    assert ports["configs"].applied[0][1] == {"sla_high_minutes": 30}
    # Still ONE transaction for the whole operation.
    assert ports["uow"].commits == 1


@pytest.mark.asyncio
async def test_the_approval_threshold_change_is_audited(ports) -> None:
    """R5.8: it is the control behind principle 4 of steering/product.md."""
    await _update(ports).execute(
        tenant_id=TENANT,
        requested_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        tenant_changes={},
        config_changes={"owner_approval_threshold_eur": Decimal("250.00")},
        now=utc_now(),
    )

    entry = ports["audit"].entries[0][1]
    assert entry.action == actions.TENANT_CONFIG_UPDATED
    assert entry.changes["owner_approval_threshold_eur"] == {
        "old": "100.00",
        "new": "250.00",
    }


@pytest.mark.asyncio
async def test_a_patch_that_changes_nothing_writes_nothing(ports) -> None:
    """Design D15."""
    await _update(ports).execute(
        tenant_id=TENANT,
        requested_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=IP,
        tenant_changes={"name": "MAGNO"},
        config_changes={"sla_high_minutes": 15},
        now=utc_now(),
    )

    assert ports["tenants"].applied == []
    assert ports["configs"].applied == []
    assert ports["audit"].entries == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_an_invalid_value_is_refused_before_anything_is_written(ports) -> None:
    with pytest.raises(TenantValidationError):
        await _update(ports).execute(
            tenant_id=TENANT,
            requested_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            tenant_changes={"timezone": "Europe/Madridd"},
            config_changes={},
            now=utc_now(),
        )

    assert ports["tenants"].applied == []
    assert ports["audit"].entries == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_updating_another_tenant_is_a_not_found(ports) -> None:
    with pytest.raises(TenantNotFoundError):
        await _update(ports).execute(
            tenant_id=TENANT,
            requested_id=uuid.uuid4(),
            actor_user_id=ACTOR,
            actor_ip=IP,
            tenant_changes={"name": "Hacked"},
            config_changes={},
            now=utc_now(),
        )

    assert ports["tenants"].applied == []


@pytest.mark.asyncio
async def test_a_failing_audit_write_leaves_the_change_uncommitted(ports) -> None:
    """R6.4."""
    ports["audit"].fail = True

    with pytest.raises(RuntimeError):
        await _update(ports).execute(
            tenant_id=TENANT,
            requested_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=IP,
            tenant_changes={"name": "MAGNO SL"},
            config_changes={},
            now=utc_now(),
        )

    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_the_update_check_also_happens_before_any_query(ports) -> None:
    """The same poisoned-repository proof the read path has (QA panel of sections 7-8).

    The ordering in `UpdateTenantSettingsUseCase` was correct by inspection but untested, so a
    regression that moved the comparison after the lookup would not have failed anything.
    """
    ports["tenants"] = FakeTenantRepository(_tenant(id=uuid.uuid4(), name="Somebody else"))

    with pytest.raises(TenantNotFoundError):
        await _update(ports).execute(
            tenant_id=TENANT,
            requested_id=uuid.uuid4(),
            actor_user_id=ACTOR,
            actor_ip=IP,
            tenant_changes={"name": "Hijacked"},
            config_changes={},
            now=utc_now(),
        )

    assert ports["tenants"].applied == []
    assert ports["configs"].created == 0
    assert ports["audit"].entries == []
