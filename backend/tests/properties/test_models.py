import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.tenants.infrastructure.models import TenantModel


@pytest.mark.asyncio
async def test_property_and_state_transition_roundtrip(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    db_session.add(prop)
    await db_session.flush()

    transition = PropertyStateTransitionModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        to_state=PropertyOperationalState.AWAITING_CHECKIN,
        triggered_by=StateTransitionTriggeredBy.SYSTEM,
    )
    db_session.add(transition)
    await db_session.commit()

    result = await db_session.execute(select(PropertyModel).where(PropertyModel.id == prop.id))
    fetched = result.scalar_one()
    assert fetched.current_operational_state == PropertyOperationalState.VACANT_READY
    assert fetched.internal_code == "redes11"

    result = await db_session.execute(
        select(PropertyStateTransitionModel).where(PropertyStateTransitionModel.property_id == prop.id)
    )
    fetched_transition = result.scalar_one()
    assert fetched_transition.to_state == PropertyOperationalState.AWAITING_CHECKIN
    assert fetched_transition.from_state is None


@pytest.mark.asyncio
async def test_internal_code_unique_per_tenant(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    db_session.add(PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11"))
    await db_session.commit()

    db_session.add(PropertyModel(tenant_id=tenant.id, name="REDES11 dup", internal_code="redes11"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


def test_the_external_id_index_agrees_with_the_default_provider() -> None:
    """`uq_properties_tenant_id_pms_external_id` folds a NULL provider to `MOCK`.

    That literal is only correct while `MOCK` is what a NULL `pms_provider` resolves to, and the
    definition of that default lives in another module (`pms_factory.DEFAULT_PROVIDER`). Nothing
    connects the two at runtime, so this test is the connection: if the default provider ever
    changes, the index silently starts grouping rows under a provider nobody uses, and the
    duplicate it is meant to catch slips through. Failing here points at the migration and the
    model that have to change with it.
    """
    from app.integrations.domain.enums import PMSProvider
    from app.integrations.infrastructure.pms_factory import DEFAULT_PROVIDER

    assert DEFAULT_PROVIDER is PMSProvider.MOCK, (
        "the default PMS provider changed; uq_properties_tenant_id_pms_external_id coalesces a "
        "NULL pms_provider to 'MOCK' and must be migrated to the new default"
    )
