from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access.domain.enums import AccessCreatedMode, AccessProvider, AccessRecordStatus
from app.access.infrastructure.models import AccessRecordModel
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
async def test_access_record_roundtrip(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    record = AccessRecordModel(tenant_id=tenant.id, property_id=prop.id)
    db_session.add(record)
    await db_session.commit()

    result = await db_session.execute(select(AccessRecordModel).where(AccessRecordModel.id == record.id))
    fetched = result.scalar_one()
    assert fetched.provider == AccessProvider.MANUAL
    assert fetched.status == AccessRecordStatus.PENDING
    assert fetched.created_mode == AccessCreatedMode.MANUAL
    assert fetched.reservation_id is None
    assert fetched.valid_from is None
    assert fetched.valid_to is None


@pytest.mark.asyncio
async def test_access_record_property_restrict_on_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    db_session.add(AccessRecordModel(tenant_id=tenant.id, property_id=prop.id))
    await db_session.commit()

    await db_session.delete(prop)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_access_record_reservation_restrict_on_delete(db_session) -> None:
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
        AccessRecordModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            reservation_id=reservation.id,
            code_masked="****23",
        )
    )
    await db_session.commit()

    await db_session.delete(reservation)
    with pytest.raises(IntegrityError):
        await db_session.commit()
