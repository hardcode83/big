"""In-memory doubles for the ports `AdvancePropertyStatesUseCase` depends on.

The property, reservation, timeline and unit-of-work fakes are the shared ones from
`tests/reservations/doubles.py` — re-exported here so a properties test does not have to
know where they live, and so there is one fake per port in the codebase rather than two
that can disagree. Only the two ports nothing else uses yet are defined here.
"""

import uuid
from collections.abc import Collection
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

    async def applied_clock_triggers(
        self, tenant_id: uuid.UUID, reservation_ids: Collection[uuid.UUID]
    ) -> set[tuple[uuid.UUID, str]]:
        """Derived from the rows actually appended, not from a separate list to keep in sync.

        The real adapter reads `metadata->>'reservation_id'` and `metadata->>'trigger'` out of
        the stored JSON, so this reads the same two keys off the same metadata dict — a fake that
        answered from a hand-set field could agree with a test and disagree with Postgres, which
        is the failure `fixtures-and-real-writers-disagree` records.
        """
        wanted = {str(reservation_id) for reservation_id in reservation_ids}
        if not wanted:
            return set()
        found: set[tuple[uuid.UUID, str]] = set()
        for transition in self.transitions:
            if transition.tenant_id != tenant_id:
                continue
            reservation_id = (transition.metadata or {}).get("reservation_id")
            trigger = (transition.metadata or {}).get("trigger")
            if reservation_id is None or trigger is None:
                continue
            # Loud, because the alternative is quiet in the wrong direction. `metadata` is
            # JSON, so `PropertyStateMachine.evaluate` writes `str(reservation_id)`; a raw UUID
            # would never match this fake's string keys and the row would simply be dropped —
            # reporting "not applied" for a stay that had in fact transitioned. The real adapter
            # cannot drift that way (Postgres would reject the value), so the fake must not be
            # the more forgiving of the two.
            if not isinstance(reservation_id, str) or not isinstance(trigger, str):
                raise TypeError(
                    "property_state_transitions.metadata must hold reservation_id and trigger "
                    f"as strings, got {type(reservation_id).__name__}/{type(trigger).__name__}"
                )
            if reservation_id not in wanted:
                continue
            found.add((uuid.UUID(reservation_id), trigger))
        return found

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

    async def checkin_window_hours(self, tenant_id: uuid.UUID) -> int:
        """Deliberately does **not** create the row, so a test can catch a write on a read path.

        A fake that stored a default here would agree with a use case calling `get_or_create` by
        mistake, which is the whole distinction this method exists to keep.
        """
        config = self.configs.get(tenant_id)
        if config is None:
            return TenantConfig.checkin_window_hours_before
        return config.checkin_window_hours_before


def _default_config(tenant_id: uuid.UUID, now: datetime) -> TenantConfig:
    return TenantConfig(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        created_at=now,
        updated_at=now,
        owner_approval_threshold_eur=Decimal("100.00"),
    )
