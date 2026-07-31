"""`SqlAlchemyPropertyRepository` — resolution and tenant scoping (R1.4, R3.4, R4, R5.1).

The cross-tenant cases are not an extra: they are what makes `404` (design D6) reachable
instead of a leak, so each lookup has a neighbour it must fail to find.
"""

import uuid

import pytest
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError

from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
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
) -> PropertyModel:
    model = PropertyModel(
        tenant_id=tenant.id,
        name=internal_code,
        internal_code=internal_code,
        pms_external_id=pms_external_id,
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

    `ix_properties_tenant_id_pms_external_id` is an index, not a unique constraint, so
    this state is reachable — the repository must not silently pick one. It refuses with a
    DOMAIN error, so the PMS sync can report the row without catching a SQLAlchemy
    exception inside `application/` (design D16).
    """
    tenant = await _tenant(db_session, "TenantA")
    await _property(db_session, tenant, internal_code="REDES11", pms_external_id="PMS-DUP")
    await _property(db_session, tenant, internal_code="PAJARITOS8", pms_external_id="PMS-DUP")

    with pytest.raises(AmbiguousPropertyExternalIdError):
        await SqlAlchemyPropertyRepository(db_session).find_by_pms_external_id(
            tenant.id, "PMS-DUP"
        )
