"""In-memory doubles for the ports `AdvancePropertyStatesUseCase` depends on.

The property, reservation, timeline and unit-of-work fakes are the shared ones from
`tests/reservations/doubles.py` — re-exported here so a properties test does not have to
know where they live, and so there is one fake per port in the codebase rather than two
that can disagree. Only the two ports nothing else uses yet are defined here.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.core.tenancy import CrossTenantWriteError
from app.properties.domain.entities import PropertyStateTransition
from app.tenants.domain.entities import TenantConfig
from tests.reservations.doubles import (  # noqa: F401  (re-exported for the tests)
    FakePropertyRepository,
    FakeReservationRepository,
    FakeTimelineEventRepository,
    FakeUnitOfWork,
)


@dataclass
class FakePropertyStateTransitionRepository:
    transitions: list[PropertyStateTransition] = field(default_factory=list)
    fail_with: Exception | None = None

    async def add(self, tenant_id: uuid.UUID, transition: PropertyStateTransition) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        if transition.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property state transition",
                entity_tenant_id=transition.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self.transitions.append(transition)


@dataclass
class FakeTenantConfigRepository:
    """`get_or_create` with the schema's own defaults, so a test that does not care about
    configuration gets `checkin_window_hours_before = 2` exactly like a fresh tenant."""

    configs: dict[uuid.UUID, TenantConfig] = field(default_factory=dict)

    def set_checkin_window_hours(self, tenant_id: uuid.UUID, hours: int) -> None:
        config = self.configs.get(tenant_id)
        if config is None:
            config = _default_config(tenant_id, datetime.now())
            self.configs[tenant_id] = config
        config.checkin_window_hours_before = hours

    async def get_or_create(self, tenant_id: uuid.UUID, now: datetime) -> TenantConfig:
        if tenant_id not in self.configs:
            self.configs[tenant_id] = _default_config(tenant_id, now)
        return self.configs[tenant_id]


def _default_config(tenant_id: uuid.UUID, now: datetime) -> TenantConfig:
    return TenantConfig(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        created_at=now,
        updated_at=now,
        owner_approval_threshold_eur=Decimal("100.00"),
    )
