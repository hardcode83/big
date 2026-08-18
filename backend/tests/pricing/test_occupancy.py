import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.pricing.domain.constants import OCCUPANCY_WINDOW_DAYS
from app.pricing.domain.occupancy import occupancy_pct_for, occupancy_window
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus

EXECUTION_DATE = date(2026, 9, 1)
NOW = datetime(2026, 9, 1, 6, tzinfo=timezone.utc)
PROPERTY_ID = uuid.uuid4()


def stay(
    check_in: date, check_out: date, status: ReservationStatus = ReservationStatus.CONFIRMED
) -> Reservation:
    return Reservation(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=PROPERTY_ID,
        channel=ReservationChannel.DIRECT,
        check_in_date=check_in,
        check_out_date=check_out,
        nights=(check_out - check_in).days,
        created_at=NOW,
        updated_at=NOW,
        status=status,
    )


def test_the_window_is_the_thirty_days_after_the_execution_date() -> None:
    start, end = occupancy_window(EXECUTION_DATE)

    assert start == date(2026, 9, 2)
    assert (end - start).days == OCCUPANCY_WINDOW_DAYS


def test_an_empty_window_is_zero_percent() -> None:
    assert occupancy_pct_for([], execution_date=EXECUTION_DATE) == Decimal("0")


def test_a_full_window_is_one_hundred_percent() -> None:
    start, end = occupancy_window(EXECUTION_DATE)

    assert occupancy_pct_for([stay(start, end)], execution_date=EXECUTION_DATE) == Decimal("100")


def test_the_check_out_day_is_not_an_occupied_night() -> None:
    start, _ = occupancy_window(EXECUTION_DATE)

    result = occupancy_pct_for([stay(start, start + timedelta(days=1))],
                               execution_date=EXECUTION_DATE)

    assert result == Decimal(100) / Decimal(30)


def test_overlapping_reservations_count_a_shared_night_once() -> None:
    start, _ = occupancy_window(EXECUTION_DATE)
    reservations = [
        stay(start, start + timedelta(days=5)),
        stay(start + timedelta(days=3), start + timedelta(days=8)),
    ]

    # Union is [start, start+8) = 8 nights, not 5 + 5.
    assert occupancy_pct_for(reservations, execution_date=EXECUTION_DATE) == (
        Decimal(8) * Decimal(100) / Decimal(30)
    )


def test_a_stay_starting_before_the_window_counts_only_its_intersection() -> None:
    start, _ = occupancy_window(EXECUTION_DATE)
    reservation = stay(start - timedelta(days=10), start + timedelta(days=3))

    assert occupancy_pct_for([reservation], execution_date=EXECUTION_DATE) == (
        Decimal(3) * Decimal(100) / Decimal(30)
    )


def test_a_stay_ending_after_the_window_counts_only_its_intersection() -> None:
    _, end = occupancy_window(EXECUTION_DATE)
    reservation = stay(end - timedelta(days=2), end + timedelta(days=20))

    assert occupancy_pct_for([reservation], execution_date=EXECUTION_DATE) == (
        Decimal(2) * Decimal(100) / Decimal(30)
    )


def test_a_stay_entirely_outside_the_window_counts_nothing() -> None:
    _, end = occupancy_window(EXECUTION_DATE)

    assert occupancy_pct_for(
        [stay(end, end + timedelta(days=3))], execution_date=EXECUTION_DATE
    ) == Decimal("0")


def test_the_execution_date_itself_is_outside_the_window() -> None:
    reservation = stay(EXECUTION_DATE, EXECUTION_DATE + timedelta(days=1))

    assert occupancy_pct_for([reservation], execution_date=EXECUTION_DATE) == Decimal("0")


@pytest.mark.parametrize("status", [ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW])
def test_a_cancelled_or_no_show_night_is_free(status: ReservationStatus) -> None:
    start, end = occupancy_window(EXECUTION_DATE)

    assert occupancy_pct_for([stay(start, end, status)],
                             execution_date=EXECUTION_DATE) == Decimal("0")


@pytest.mark.parametrize(
    "status",
    [
        ReservationStatus.PENDING,
        ReservationStatus.CONFIRMED,
        ReservationStatus.CHECKED_IN_ESTIMATED,
        ReservationStatus.CHECKED_OUT_ESTIMATED,
        ReservationStatus.COMPLETED,
    ],
)
def test_every_other_status_occupies(status: ReservationStatus) -> None:
    start, end = occupancy_window(EXECUTION_DATE)

    assert occupancy_pct_for([stay(start, end, status)],
                             execution_date=EXECUTION_DATE) == Decimal("100")


def test_the_result_is_a_decimal() -> None:
    start, _ = occupancy_window(EXECUTION_DATE)

    result = occupancy_pct_for([stay(start, start + timedelta(days=1))],
                               execution_date=EXECUTION_DATE)

    assert type(result) is Decimal
