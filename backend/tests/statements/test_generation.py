"""Tests for the generation primitives (Period, MonetaryAggregator, CurrencyFilter).

The tests use plain Python — no DB. The aggregator's input is rows of two already-built
entities, and `Period` and `CurrencyFilter` are pure functions. DB-coupled coverage of
the generator itself lives in `test_use_cases.py` over the real repositories.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.reservations.domain.entities import Reservation
from app.statements.application.generation import (
    CurrencyFilter,
    MonetaryAggregator,
    Period,
)
from app.statements.domain.entities import Expense
from app.statements.domain.enums import ExpenseCategory


def _reservation(*, amount: Decimal = Decimal("100.00"), commission: Decimal = Decimal("0"),
                 currency: str = "EUR", id: str = "r-1") -> Reservation:
    """The minimum viable `Reservation` for the aggregator tests.

    Skips every field the aggregator does not read, so the test stays focused on the
    eleven columns. `id` is a string here so currency-mismatch rows can be told apart.
    """
    import uuid as _uuid

    now = _dt(2026, 7, 1)
    return Reservation(
        id=_uuid.UUID(int=hash(id) & ((1 << 128) - 1)) if id.isdigit() else _uuid.uuid5(
            _uuid.NAMESPACE_DNS, id
        ),
        tenant_id=_uuid.uuid4(),
        property_id=_uuid.uuid4(),
        channel="DIRECT",  # arbitrary closed value
        check_in_date=date(2026, 7, 5),
        check_out_date=date(2026, 7, 10),
        nights=5,
        created_at=now,
        updated_at=now,
        gross_amount=amount,
        ota_commission=commission,
        net_amount=amount - commission,
        currency=currency,
    )


def _expense(
    *,
    category: ExpenseCategory,
    amount: Decimal,
    currency: str = "EUR",
    statement_id=None,
    approved_by=None,
    id: str = "e-1",
) -> Expense:
    import uuid as _uuid

    eid = _uuid.uuid5(_uuid.NAMESPACE_DNS, id)
    return Expense(
        id=eid,
        tenant_id=_uuid.uuid4(),
        property_id=_uuid.uuid4(),
        category=category,
        description=f"test expense {id}",
        amount=amount,
        date=date(2026, 7, 15),
        created_at=_dt(2026, 7, 15),
        statement_id=statement_id,
        approved_by=approved_by,
        currency=currency,
    )


def _dt(year: int, month: int, day: int):
    from datetime import datetime, timezone

    return datetime(year, month, day, tzinfo=timezone.utc)


# ---- Period -----------------------------------------------------------------


class TestPeriod:
    """The rules R2.5 fixes: one calendar month, last day of month on the end."""

    def test_month_containing_accepts_a_last_day(self) -> None:
        period = Period.month_containing(date(2026, 7, 31))
        assert period.period_start == date(2026, 7, 1)
        assert period.period_end == date(2026, 7, 31)

    def test_month_containing_rejects_a_mid_month_day(self) -> None:
        with pytest.raises(ValueError):
            Period.month_containing(date(2026, 7, 15))

    def test_post_init_rejects_cross_month_range(self) -> None:
        with pytest.raises(ValueError):
            Period(period_start=date(2026, 7, 1), period_end=date(2026, 8, 1))

    def test_post_init_rejects_when_end_is_not_last_day_of_month(self) -> None:
        # 15 June is mid-month; post_init catches it.
        with pytest.raises(ValueError):
            Period(period_start=date(2026, 6, 1), period_end=date(2026, 6, 15))

    def test_previous_month_handles_year_boundary(self) -> None:
        period = Period.previous_month(today=date(2026, 1, 15))
        assert period.period_start == date(2025, 12, 1)
        assert period.period_end == date(2025, 12, 31)


# ---- CurrencyFilter ----------------------------------------------------------


class TestCurrencyFilter:
    """D3 — abort on mixed currency, no partial statement."""

    def test_returns_empty_for_eur_only_input(self) -> None:
        result = CurrencyFilter.check(
            reservations=[_reservation()],
            expenses=[_expense(category=ExpenseCategory.CLEANING, amount=Decimal("20"))],
        )
        assert result == []

    def test_flags_a_non_eur_reservation(self) -> None:
        non_eur = _reservation(currency="USD", id="r-bad")
        result = CurrencyFilter.check(
            reservations=[non_eur],
            expenses=[],
        )
        assert result == [(str(non_eur.id), "USD", "reservations")]

    def test_flags_a_non_eur_expense(self) -> None:
        non_eur = _expense(category=ExpenseCategory.OTHER, amount=Decimal("9.99"), currency="USD", id="e-bad")
        result = CurrencyFilter.check(
            reservations=[],
            expenses=[non_eur],
        )
        assert result == [(str(non_eur.id), "USD", "expenses")]

    def test_collects_every_offending_row(self) -> None:
        bad1 = _reservation(currency="USD", id="r-1")
        bad2 = _expense(category=ExpenseCategory.LAUNDRY, amount=Decimal("10"), currency="GBP", id="e-1")
        result = CurrencyFilter.check(
            reservations=[bad1],
            expenses=[bad2],
        )
        assert (str(bad1.id), "USD", "reservations") in result
        assert (str(bad2.id), "GBP", "expenses") in result


# ---- MonetaryAggregator ------------------------------------------------------


class TestMonetaryAggregator:
    """The eleven columns, summed in EUR (D3, D4, D6.1)."""

    def test_empty_input_yields_zero_everywhere(self) -> None:
        agg = MonetaryAggregator(threshold_eur=Decimal("100.00"))
        breakdown = agg.aggregate(reservations=[], expenses=[])
        assert breakdown.gross_revenue == Decimal("0")
        assert breakdown.net_revenue == Decimal("0")
        assert breakdown.net_owner_result == Decimal("0")
        for field in (
            "cleaning_costs",
            "laundry_costs",
            "amenities_costs",
            "maintenance_costs",
            "specialist_costs",
            "platform_fee",
            "other_costs",
        ):
            assert getattr(breakdown, field) == Decimal("0"), field

    def test_sums_gross_and_commission(self) -> None:
        agg = MonetaryAggregator(threshold_eur=Decimal("100.00"))
        breakdown = agg.aggregate(
            reservations=[
                _reservation(amount=Decimal("200.00"), commission=Decimal("30.00"), id="r-1"),
                _reservation(amount=Decimal("100.00"), commission=Decimal("10.00"), id="r-2"),
            ],
            expenses=[],
        )
        assert breakdown.gross_revenue == Decimal("300.00")
        assert breakdown.ota_commissions == Decimal("40.00")
        assert breakdown.net_revenue == Decimal("260.00")

    def test_groups_expenses_into_the_seven_buckets(self) -> None:
        agg = MonetaryAggregator(threshold_eur=Decimal("10000.00"))  # nothing crosses
        breakdown = agg.aggregate(
            reservations=[],
            expenses=[
                _expense(category=ExpenseCategory.CLEANING, amount=Decimal("50")),
                _expense(category=ExpenseCategory.LAUNDRY, amount=Decimal("30"), id="e-l"),
                _expense(category=ExpenseCategory.AMENITIES, amount=Decimal("20"), id="e-a"),
                _expense(category=ExpenseCategory.MAINTENANCE, amount=Decimal("100"), id="e-m"),
                _expense(category=ExpenseCategory.SPECIALIST, amount=Decimal("200"), id="e-s"),
                _expense(category=ExpenseCategory.PLATFORM_FEE, amount=Decimal("15"), id="e-p"),
                _expense(category=ExpenseCategory.OTHER, amount=Decimal("10"), id="e-o"),
            ],
        )
        assert breakdown.cleaning_costs == Decimal("50")
        assert breakdown.laundry_costs == Decimal("30")
        assert breakdown.amenities_costs == Decimal("20")
        assert breakdown.maintenance_costs == Decimal("100")
        assert breakdown.specialist_costs == Decimal("200")
        assert breakdown.platform_fee == Decimal("15")
        assert breakdown.other_costs == Decimal("10")

    def test_net_owner_result_is_net_revenue_minus_total_costs(self) -> None:
        agg = MonetaryAggregator(threshold_eur=Decimal("10000.00"))
        breakdown = agg.aggregate(
            reservations=[_reservation(amount=Decimal("500"), commission=Decimal("0"))],
            expenses=[_expense(category=ExpenseCategory.CLEANING, amount=Decimal("50"))],
        )
        assert breakdown.net_revenue == Decimal("500")
        assert breakdown.cleaning_costs == Decimal("50")
        assert breakdown.net_owner_result == Decimal("450")

    def test_drops_a_consolidated_expense(self) -> None:
        """D6.1 — a row already attached to a statement does not contribute to a fresh
        aggregator run. The aggregator is the single place that drops them; the
        repository does not filter, because the same `list_for_period` backs the
        manual review path."""
        import uuid as _uuid

        statement_id = _uuid.uuid4()
        agg = MonetaryAggregator(threshold_eur=Decimal("10000.00"))
        breakdown = agg.aggregate(
            reservations=[],
            expenses=[
                _expense(category=ExpenseCategory.CLEANING, amount=Decimal("50")),
                _expense(
                    category=ExpenseCategory.CLEANING,
                    amount=Decimal("999"),
                    statement_id=statement_id,
                    id="e-consolidated",
                ),
            ],
        )
        assert breakdown.cleaning_costs == Decimal("50")

    def test_drops_an_unapproved_over_threshold_expense(self) -> None:
        """R5.7 / D4 — a row over the threshold with `approved_by IS NULL` is the
        owner-approval gate. Until the reconciliation of D4 materialises the answer,
        the expense does not contribute to the period."""
        agg = MonetaryAggregator(threshold_eur=Decimal("100.00"))
        breakdown = agg.aggregate(
            reservations=[],
            expenses=[
                _expense(
                    category=ExpenseCategory.SPECIALIST,
                    amount=Decimal("200"),
                    approved_by=None,
                    id="e-pending",
                ),
                _expense(
                    category=ExpenseCategory.SPECIALIST,
                    amount=Decimal("200"),
                    id="e-approved",
                    approved_by=_uuid_from_string("user-1"),
                ),
            ],
        )
        # Only the approved row contributes.
        assert breakdown.specialist_costs == Decimal("200")

    def test_keeps_an_expense_under_threshold_even_without_approval(self) -> None:
        """A row under the threshold does not need an `OwnerApproval`; the
        reconciliation has nothing to do, and the row counts immediately."""
        agg = MonetaryAggregator(threshold_eur=Decimal("100.00"))
        breakdown = agg.aggregate(
            reservations=[],
            expenses=[
                _expense(
                    category=ExpenseCategory.AMENITIES,
                    amount=Decimal("50"),
                    approved_by=None,
                    id="e-tiny",
                ),
            ],
        )
        assert breakdown.amenities_costs == Decimal("50")


def _uuid_from_string(s: str):
    import uuid as _uuid

    return _uuid.uuid5(_uuid.NAMESPACE_DNS, s)
