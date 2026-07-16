import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import PaymentStatus, ReservationChannel, ReservationStatus


def _base_kwargs(**overrides):
    now = datetime.now(timezone.utc)
    check_in = date(2026, 8, 1)
    kwargs = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        channel=ReservationChannel.DIRECT,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=3),
        nights=3,
        created_at=now,
        updated_at=now,
    )
    kwargs.update(overrides)
    return kwargs


def test_reservation_instantiates_with_defaults() -> None:
    reservation = Reservation(**_base_kwargs())

    assert reservation.status == ReservationStatus.PENDING
    assert reservation.payment_status == PaymentStatus.PENDING
    assert reservation.currency == "EUR"
    assert reservation.adults == 1


def test_reservation_rejects_check_out_not_after_check_in() -> None:
    check_in = date(2026, 8, 1)
    with pytest.raises(ValueError):
        Reservation(**_base_kwargs(check_in_date=check_in, check_out_date=check_in))
