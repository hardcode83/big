"""`MockPMSAdapter` — the contract, including the failures it must produce (R3.1, R3.4)."""

from datetime import UTC, datetime

import pytest

from app.integrations.infrastructure.mock_pms import (
    SEED_PROPERTY_CODE,
    UNKNOWN_PROPERTY_CODE,
    MockPMSAdapter,
)

SINCE = datetime(2026, 7, 31, tzinfo=UTC)


@pytest.mark.asyncio
async def test_it_returns_the_seed_reservations_of_the_prd() -> None:
    rows = await MockPMSAdapter(include_broken_rows=False).list_reservations(SINCE)

    assert [row.external_id for row in rows] == ["MOCK-PMS-0001", "MOCK-PMS-0002"]
    assert {row.channel for row in rows} == {"AIRBNB", "BOOKING"}
    assert all(row.property_external_id == SEED_PROPERTY_CODE for row in rows)


@pytest.mark.asyncio
async def test_the_first_reservation_is_active_around_the_reference_instant() -> None:
    """PRD §27 seeds one stay in progress; the mock derives it from `since`, not a clock."""
    rows = await MockPMSAdapter(include_broken_rows=False).list_reservations(SINCE)

    active = rows[0]
    assert active.check_in_date < SINCE.date() < active.check_out_date


@pytest.mark.asyncio
async def test_it_deliberately_includes_rows_that_cannot_be_imported() -> None:
    """A mock that never fails would let R3.4 pass untested."""
    rows = await MockPMSAdapter().list_reservations(SINCE)

    unknown_property = [
        row for row in rows if row.property_external_id == UNKNOWN_PROPERTY_CODE
    ]
    impossible_stay = [row for row in rows if row.check_in_date == row.check_out_date]
    assert len(unknown_property) == 1
    assert len(impossible_stay) == 1


@pytest.mark.asyncio
async def test_it_filters_by_property_when_asked() -> None:
    rows = await MockPMSAdapter().list_reservations(SINCE, property_external_id=SEED_PROPERTY_CODE)

    assert rows
    assert all(row.property_external_id == SEED_PROPERTY_CODE for row in rows)


@pytest.mark.asyncio
async def test_get_reservation_finds_a_known_id_and_none_otherwise() -> None:
    adapter = MockPMSAdapter()

    assert (await adapter.get_reservation("MOCK-PMS-0001")).external_id == "MOCK-PMS-0001"
    assert await adapter.get_reservation("NOPE") is None


@pytest.mark.asyncio
async def test_amounts_are_decimals_not_floats() -> None:
    """Money through the adapter boundary must not lose precision on the way in."""
    from decimal import Decimal

    rows = await MockPMSAdapter(include_broken_rows=False).list_reservations(SINCE)

    assert rows[0].gross_amount == Decimal("350.00")
    assert isinstance(rows[0].gross_amount, Decimal)
