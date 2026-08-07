"""`SqlAlchemyPropertyRepository` — resolution and tenant scoping (R1.4, R3.4, R4, R5.1).

The cross-tenant cases are not an extra: they are what makes `404` (design D6) reachable
instead of a leak, so each lookup has a neighbour it must fail to find.

`list_by_state`, `save` and `SqlAlchemyPropertyStateTransitionRepository` arrive with
`celery-jobs` (its R2, R3), which is the first writer of operational state.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.tenancy import CrossTenantWriteError
from app.integrations.domain.enums import PMSProvider
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import (
    PropertyOperationalState,
    StateTransitionTriggeredBy,
)
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError

from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.tenants.infrastructure.models import TenantModel


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _property(
    db_session,
    tenant: TenantModel,
    *,
    internal_code: str,
    pms_external_id: str | None = None,
    state: PropertyOperationalState = PropertyOperationalState.VACANT_READY,
    pms_provider: PMSProvider | None = None,
) -> PropertyModel:
    model = PropertyModel(
        tenant_id=tenant.id,
        name=internal_code,
        internal_code=internal_code,
        pms_external_id=pms_external_id,
        pms_provider=pms_provider,
        current_operational_state=state,
    )
    db_session.add(model)
    await db_session.flush()
    return model


@pytest.mark.asyncio
async def test_get_finds_the_property_of_its_tenant(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")

    found = await SqlAlchemyPropertyRepository(db_session).get(tenant.id, model.id)

    assert found is not None
    assert found.id == model.id
    assert found.internal_code == "REDES11"


@pytest.mark.asyncio
async def test_get_does_not_reach_another_tenants_property(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="PAJARITOS8")

    found = await SqlAlchemyPropertyRepository(db_session).get(tenant_a.id, theirs.id)

    assert found is None


@pytest.mark.asyncio
async def test_get_of_an_unknown_id_is_none_not_an_error(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")

    found = await SqlAlchemyPropertyRepository(db_session).get(tenant.id, uuid.uuid4())

    assert found is None


@pytest.mark.asyncio
async def test_find_by_internal_code_within_the_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, internal_code="REDES11")
    # Same code in the neighbour tenant: allowed by the schema (the constraint is
    # per tenant), and exactly the case a missing filter would confuse.
    await _property(db_session, tenant_b, internal_code="REDES11")

    repository = SqlAlchemyPropertyRepository(db_session)

    assert (await repository.find_by_internal_code(tenant_a.id, "REDES11")).id == mine.id
    assert await repository.find_by_internal_code(tenant_a.id, "UNKNOWN") is None


@pytest.mark.asyncio
async def test_find_by_internal_code_ignores_surrounding_whitespace(db_session) -> None:
    """A CSV cell arrives with whatever the spreadsheet left in it (R4)."""
    tenant = await _tenant(db_session, "TenantA")
    mine = await _property(db_session, tenant, internal_code="REDES11")

    found = await SqlAlchemyPropertyRepository(db_session).find_by_internal_code(
        tenant.id, "  REDES11 "
    )

    assert found is not None
    assert found.id == mine.id


@pytest.mark.asyncio
async def test_find_by_pms_external_id_within_the_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, internal_code="REDES11", pms_external_id="PMS-1")
    await _property(db_session, tenant_b, internal_code="OTHER", pms_external_id="PMS-1")

    repository = SqlAlchemyPropertyRepository(db_session)

    assert (await repository.find_by_pms_external_id(tenant_a.id, "PMS-1")).id == mine.id
    assert await repository.find_by_pms_external_id(tenant_a.id, "PMS-9") is None


@pytest.mark.asyncio
async def test_an_ambiguous_pms_external_id_fails_closed(db_session) -> None:
    """Two properties, one external id: refuse rather than attach a guest to a coin flip.

    It refuses with a DOMAIN error, so the PMS sync can report the row without catching a
    SQLAlchemy exception inside `application/` (design D16).

    **The two properties are on different providers, and that is load-bearing.**
    `properties-crud` (design D5) added the partial unique index
    `uq_properties_tenant_id_pms_external_id`, keyed on `coalesce(pms_provider, 'MOCK')` — so
    within one provider this ambiguity can no longer be created, which is the point: the new
    write path could otherwise produce it one request at a time. Across providers it stays legal,
    because external ids are unique only WITHIN a provider and a tenant mid-migration
    legitimately has the same id on two of them (ADR 0006 decision 7).

    That is exactly why this guard is still reachable rather than dead: `find_by_pms_external_id`
    looks up tenant-wide, without a provider, so a legitimate cross-provider pair returns two rows
    and it must refuse instead of picking one.
    """
    tenant = await _tenant(db_session, "TenantA")
    await _property(
        db_session,
        tenant,
        internal_code="REDES11",
        pms_external_id="PMS-DUP",
        pms_provider=PMSProvider.BEDS24,
    )
    await _property(
        db_session,
        tenant,
        internal_code="PAJARITOS8",
        pms_external_id="PMS-DUP",
        pms_provider=PMSProvider.CHANNEX,
    )

    with pytest.raises(AmbiguousPropertyExternalIdError):
        await SqlAlchemyPropertyRepository(db_session).find_by_pms_external_id(
            tenant.id, "PMS-DUP"
        )


@pytest.mark.asyncio
async def test_list_by_state_returns_only_the_requested_states(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    vacant = await _property(
        db_session, tenant, internal_code="REDES11", state=PropertyOperationalState.VACANT_READY
    )
    awaiting = await _property(
        db_session,
        tenant,
        internal_code="PAJARITOS8",
        state=PropertyOperationalState.AWAITING_CHECKIN,
    )
    await _property(
        db_session,
        tenant,
        internal_code="OCCUPIED1",
        state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )

    found = await SqlAlchemyPropertyRepository(db_session).list_by_state(
        tenant.id,
        [PropertyOperationalState.VACANT_READY, PropertyOperationalState.AWAITING_CHECKIN],
    )

    assert {p.id for p in found} == {vacant.id, awaiting.id}


@pytest.mark.asyncio
async def test_list_by_state_does_not_reach_another_tenant(db_session) -> None:
    """The isolation test rule 1 of `steering/security.md` requires for this query.

    A scheduled job iterates tenants in one process, so a missing filter here would not
    leak a read — it would transition a neighbour's flat.
    """
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, internal_code="REDES11")
    await _property(db_session, tenant_b, internal_code="THEIRS")

    found = await SqlAlchemyPropertyRepository(db_session).list_by_state(
        tenant_a.id, [PropertyOperationalState.VACANT_READY]
    )

    assert [p.id for p in found] == [mine.id]


@pytest.mark.asyncio
async def test_list_by_state_without_states_returns_empty_without_querying(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    await _property(db_session, tenant, internal_code="REDES11")

    assert await SqlAlchemyPropertyRepository(db_session).list_by_state(tenant.id, []) == []


@pytest.mark.asyncio
async def test_save_persists_the_operational_state(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    repository = SqlAlchemyPropertyRepository(db_session)

    entity = await repository.get(tenant.id, model.id)
    entity.current_operational_state = PropertyOperationalState.AWAITING_CHECKIN
    await repository.save(tenant.id, entity)

    reloaded = await repository.get(tenant.id, model.id)
    assert reloaded.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN


@pytest.mark.asyncio
async def test_save_leaves_every_other_column_alone(db_session) -> None:
    """`save` is deliberately narrow (design D6): only the operational state travels."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    repository = SqlAlchemyPropertyRepository(db_session)

    entity = await repository.get(tenant.id, model.id)
    entity.current_operational_state = PropertyOperationalState.AWAITING_CHECKIN
    entity.name = "renamed in memory"
    entity.max_guests = 99
    await repository.save(tenant.id, entity)

    reloaded = await repository.get(tenant.id, model.id)
    assert reloaded.name == "REDES11"
    assert reloaded.max_guests == 2


@pytest.mark.asyncio
async def test_save_refuses_a_property_of_another_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="THEIRS")

    entity = await SqlAlchemyPropertyRepository(db_session).get(tenant_b.id, theirs.id)

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyPropertyRepository(db_session).save(tenant_a.id, entity)


def _transition(tenant_id, property_id, **overrides) -> PropertyStateTransition:
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        from_state=PropertyOperationalState.VACANT_READY,
        to_state=PropertyOperationalState.AWAITING_CHECKIN,
        triggered_by=StateTransitionTriggeredBy.SYSTEM,
        created_at=datetime(2026, 8, 4, 10, 0, tzinfo=UTC),
        reason="check-in window opened",
        metadata={"trigger": "CHECKIN_WINDOW_OPENED"},
    )
    return PropertyStateTransition(**{**defaults, **overrides})


@pytest.mark.asyncio
async def test_transition_add_persists_every_field(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    transition = _transition(tenant.id, model.id)

    await SqlAlchemyPropertyStateTransitionRepository(db_session).add(tenant.id, transition)

    stored = (
        await db_session.execute(
            select(PropertyStateTransitionModel).where(
                PropertyStateTransitionModel.id == transition.id
            )
        )
    ).scalar_one()
    assert stored.from_state is PropertyOperationalState.VACANT_READY
    assert stored.to_state is PropertyOperationalState.AWAITING_CHECKIN
    assert stored.triggered_by is StateTransitionTriggeredBy.SYSTEM
    assert stored.triggered_by_user_id is None
    assert stored.reason == "check-in window opened"
    # The column is `metadata` in Postgres, reached through `metadata_` in the model.
    assert stored.metadata_ == {"trigger": "CHECKIN_WINDOW_OPENED"}
    assert stored.created_at == datetime(2026, 8, 4, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_transition_add_refuses_another_tenants_transition(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="THEIRS")

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyPropertyStateTransitionRepository(db_session).add(
            tenant_a.id, _transition(tenant_b.id, theirs.id)
        )
