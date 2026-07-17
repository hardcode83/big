from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.auth.infrastructure.models import UserModel
from app.maintenance.domain.enums import IncidentSource
from app.maintenance.infrastructure.models import IncidentModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationChannel
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel


async def _tenant_property(db_session):
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    db_session.add(prop)
    await db_session.flush()
    return tenant, prop


@pytest.mark.asyncio
async def test_incident_roundtrip(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    incident = IncidentModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        title="Broken AC",
        description="The AC unit in the living room is not cooling.",
    )
    db_session.add(incident)
    await db_session.commit()

    result = await db_session.execute(select(IncidentModel).where(IncidentModel.id == incident.id))
    fetched = result.scalar_one()
    assert fetched.category.value == "OTHER"
    assert fetched.severity.value == "MEDIUM"
    assert fetched.status.value == "OPEN"
    assert fetched.owner_approval_required is False


@pytest.mark.asyncio
async def test_incident_property_restrict_on_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    db_session.add(
        IncidentModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            source=IncidentSource.SYSTEM,
            title="Water leak",
            description="Leak detected under the kitchen sink.",
        )
    )
    await db_session.commit()

    await db_session.delete(prop)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_incident_assigned_technician_set_null_on_user_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    technician = UserModel(
        tenant_id=tenant.id,
        name="Tech Tom",
        email="tom@example.com",
        password_hash="hash",
        role="TECHNICIAN",
    )
    db_session.add(technician)
    await db_session.flush()

    incident = IncidentModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.OWNER,
        title="Fridge not cooling",
        description="Kitchen fridge stopped cooling overnight.",
        assigned_technician_id=technician.id,
    )
    db_session.add(incident)
    await db_session.commit()

    await db_session.delete(technician)
    await db_session.commit()

    await db_session.refresh(incident)
    assert incident.assigned_technician_id is None


@pytest.mark.asyncio
async def test_incident_reservation_restrict_on_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    check_in = date(2026, 8, 1)
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=ReservationChannel.DIRECT,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=3),
        nights=3,
    )
    db_session.add(reservation)
    await db_session.flush()

    db_session.add(
        IncidentModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            source=IncidentSource.PMS,
            title="Guest reported noise",
            description="Guest complained about noise from a neighboring unit.",
            reservation_id=reservation.id,
        )
    )
    await db_session.commit()

    await db_session.delete(reservation)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_incident_reported_by_user_set_null_on_user_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    reporter = UserModel(
        tenant_id=tenant.id,
        name="Manager Mia",
        email="mia@example.com",
        password_hash="hash",
        role="PROPERTY_MANAGER",
    )
    db_session.add(reporter)
    await db_session.flush()

    incident = IncidentModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.CLEANER,
        title="Damaged sofa",
        description="Sofa cushion torn, reported by manager.",
        reported_by_user_id=reporter.id,
    )
    db_session.add(incident)
    await db_session.commit()

    await db_session.delete(reporter)
    await db_session.commit()

    await db_session.refresh(incident)
    assert incident.reported_by_user_id is None


@pytest.mark.asyncio
async def test_incident_severity_is_distinct_postgres_enum_from_timeline_severity(db_session) -> None:
    incident_severity_values = await db_session.execute(
        text(
            "SELECT enumlabel FROM pg_enum WHERE enumtypid = "
            "(SELECT oid FROM pg_type WHERE typname = 'incident_severity') ORDER BY enumsortorder"
        )
    )
    timeline_severity_values = await db_session.execute(
        text(
            "SELECT enumlabel FROM pg_enum WHERE enumtypid = "
            "(SELECT oid FROM pg_type WHERE typname = 'timeline_severity') ORDER BY enumsortorder"
        )
    )

    assert [r[0] for r in incident_severity_values] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert [r[0] for r in timeline_severity_values] == ["INFO", "WARNING", "ERROR", "CRITICAL"]
