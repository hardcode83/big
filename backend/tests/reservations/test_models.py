from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.guests.infrastructure.models import GuestModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel


def _reservation(**overrides):
    check_in = date(2026, 8, 1)
    defaults = dict(
        channel=ReservationChannel.DIRECT,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=3),
        nights=3,
    )
    defaults.update(overrides)
    return ReservationModel(**defaults)


@pytest.mark.asyncio
async def test_reservation_roundtrip(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    guest = GuestModel(tenant_id=tenant.id, full_name="Jane Doe")
    db_session.add_all([prop, guest])
    await db_session.flush()

    reservation = _reservation(tenant_id=tenant.id, property_id=prop.id, guest_id=guest.id)
    db_session.add(reservation)
    await db_session.commit()

    result = await db_session.execute(
        select(ReservationModel).where(ReservationModel.id == reservation.id)
    )
    fetched = result.scalar_one()
    assert fetched.status == ReservationStatus.PENDING
    assert fetched.currency == "EUR"
    assert fetched.guest_id == guest.id


@pytest.mark.asyncio
async def test_external_pms_id_unique_per_tenant_but_multiple_nulls_allowed(db_session) -> None:
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    db_session.add(prop)
    await db_session.flush()

    # Two reservations with NULL external_pms_id for the same tenant: allowed
    # (Postgres UNIQUE treats NULL as distinct from any other NULL).
    db_session.add_all(
        [
            _reservation(tenant_id=tenant.id, property_id=prop.id),
            _reservation(tenant_id=tenant.id, property_id=prop.id),
        ]
    )
    await db_session.commit()

    # Two reservations with the SAME non-null external_pms_id for the same
    # tenant: rejected.
    db_session.add(_reservation(tenant_id=tenant.id, property_id=prop.id, external_pms_id="EXT-1"))
    await db_session.commit()

    db_session.add(_reservation(tenant_id=tenant.id, property_id=prop.id, external_pms_id="EXT-1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
