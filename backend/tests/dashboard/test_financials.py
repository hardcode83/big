"""The money rule (`dashboard-api` R2.1, architect panel of section 6).

Extracted from `application/` to `domain/` because deciding what a currency figure means
when the data does not agree is a rule, and `steering/backend-architecture.md` puts rules in
`domain/`. Pure Python, so it gets pure unit tests.
"""

from decimal import Decimal

import pytest

from app.dashboard.domain.financials import DEFAULT_CURRENCY, financial_block


def test_no_expenses_reports_the_reservations_own_money() -> None:
    """The case of today: `expenses` has no writer until `revenue`."""
    block = financial_block(
        reservation_currency="EUR",
        reservation_total=Decimal("450.00"),
        pending_expenses={},
    )

    assert block.currency == "EUR"
    assert block.reservation_total == Decimal("450.00")
    assert block.pending_expenses is None


def test_nothing_pending_is_none_and_not_zero() -> None:
    """"Nothing recorded" and "nothing owed" are different facts, and only the first is
    known — a `0.00` would assert the second."""
    block = financial_block(
        reservation_currency="EUR", reservation_total=None, pending_expenses={}
    )

    assert block.pending_expenses is None


def test_one_currency_reports_its_total() -> None:
    block = financial_block(
        reservation_currency="EUR",
        reservation_total=Decimal("450.00"),
        pending_expenses={"EUR": Decimal("75.50")},
    )

    assert block.currency == "EUR"
    assert block.pending_expenses == Decimal("75.50")
    assert block.reservation_total == Decimal("450.00")


def test_a_reservation_in_another_currency_does_not_ride_along() -> None:
    """Two figures under one currency label would misread as comparable."""
    block = financial_block(
        reservation_currency="EUR",
        reservation_total=Decimal("450.00"),
        pending_expenses={"GBP": Decimal("30.00")},
    )

    assert block.currency == "GBP"
    assert block.pending_expenses == Decimal("30.00")
    assert block.reservation_total is None


def test_several_currencies_report_no_total_rather_than_a_false_one() -> None:
    """ASSUMPTION: saying nothing beats summing amounts that are not comparable, and beats
    inventing an exchange rate."""
    block = financial_block(
        reservation_currency="EUR",
        reservation_total=Decimal("450.00"),
        pending_expenses={"EUR": Decimal("10.00"), "GBP": Decimal("20.00")},
    )

    assert block.currency == "EUR"
    assert block.pending_expenses is None
    assert block.reservation_total == Decimal("450.00")


def test_no_reservation_falls_back_to_the_default_currency() -> None:
    block = financial_block(
        reservation_currency=None, reservation_total=None, pending_expenses={}
    )

    assert block.currency == DEFAULT_CURRENCY
    assert block.reservation_total is None
    assert block.pending_expenses is None


def test_pending_expenses_decide_the_currency_even_with_no_reservation() -> None:
    block = financial_block(
        reservation_currency=None,
        reservation_total=None,
        pending_expenses={"GBP": Decimal("5.00")},
    )

    assert block.currency == "GBP"
    assert block.pending_expenses == Decimal("5.00")


@pytest.mark.parametrize("total", [Decimal("0.01"), Decimal("0.00"), Decimal("9999.99")])
def test_the_amounts_stay_decimal_and_keep_their_cents(total: Decimal) -> None:
    block = financial_block(
        reservation_currency="EUR",
        reservation_total=None,
        pending_expenses={"EUR": total},
    )

    assert isinstance(block.pending_expenses, Decimal)
    assert block.pending_expenses == total


def test_the_rule_never_returns_none() -> None:
    """A block is always produced: the detail's `financial` key is present, and a caller
    handling one shape rather than two is what the return type buys."""
    for pending in ({}, {"EUR": Decimal("1")}, {"EUR": Decimal("1"), "USD": Decimal("2")}):
        assert (
            financial_block(
                reservation_currency=None, reservation_total=None, pending_expenses=pending
            )
            is not None
        )
