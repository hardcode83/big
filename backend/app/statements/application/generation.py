"""The generation primitives shared by `GenerateOwnerStatementUseCase` and the tests.

The module is deliberately thin: three value objects with no I/O. `Period` is the rule of
"what a closed monthly statement is" (D6.1); `CurrencyFilter` is the rule of "abort before
producing a partial statement" (D3); `MonetaryAggregator` is the rule of "how the eleven
columns are summed" (D6.1).

The reservation reader is injected rather than imported because `application/` does not
know which repository implementation is wired (the dependency rule): the use case hands a
callable that, given a `(tenant_id, property_id, date_from, date_to)`, returns the
overlapping reservations. Tests pass a fake; production passes a closure over
`ReservationRepository.list_for_properties`.
"""

from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.reservations.domain.entities import Reservation
from app.statements.domain.entities import Expense
from app.statements.domain.enums import ExpenseCategory


@dataclass(frozen=True)
class Period:
    """A closed monthly window the statement is the snapshot of (R1, R2.5).

    Constructed via `Period.month_containing(period_end)` so the invariant `period_end`
    is the last day of `period_start`'s month is structural, not by-review. Any other
    construction route would let a caller pass a range that crosses two months — exactly
    what R2.5 forbids with a `422`.

    `duration_days` is one informational field used by tests; nothing in the production
    code path depends on it, because a monthly statement is always `30`/`31`/`28`/`29` days.
    """

    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        if self.period_start > self.period_end:
            raise ValueError("period_start cannot be after period_end")
        expected_end = _last_day_of_month(self.period_start)
        if self.period_end != expected_end:
            raise ValueError(
                "period_end must be the last day of period_start's month "
                "(R2.5: a statement is one calendar month)"
            )
        if (self.period_end.year, self.period_end.month) != (
            self.period_start.year,
            self.period_start.month,
        ):
            raise ValueError("a period must stay within a single calendar month")

    @property
    def duration_days(self) -> int:
        return (self.period_end - self.period_start).days + 1

    @classmethod
    def month_containing(cls, period_end: date) -> "Period":
        """Build the closed month that ends on `period_end` (R2.5).

        Accepting the period's last day (rather than its first) is the manual-API form
        (R2.1: the operator types the period they want the statement to cover); the
        monthly job (R1) builds the equivalent by passing the last day of the previous
        month, which it computes from `now`.
        """
        last = _last_day_of_month(period_end)
        if period_end != last:
            raise ValueError(
                f"period_end must be the last day of its month; {period_end.isoformat()} "
                f"is not the last day of {period_end.year}-{period_end.month:02d}"
            )
        first = date(period_end.year, period_end.month, 1)
        return cls(period_start=first, period_end=last)

    @classmethod
    def previous_month(cls, *, today: date) -> "Period":
        """The closed month preceding `today` (R1.1). Used by the monthly job."""
        if today.month == 1:
            first_of_prev = date(today.year - 1, 12, 1)
        else:
            first_of_prev = date(today.year, today.month - 1, 1)
        return cls.month_containing(_last_day_of_month(first_of_prev))


def _last_day_of_month(any_day: date) -> date:
    last = monthrange(any_day.year, any_day.month)[1]
    return date(any_day.year, any_day.month, last)


@dataclass(frozen=True)
class StatementBreakdown:
    """The eleven monetary columns of `OwnerStatement`, ready to be assigned (D6.1).

    Mirrors the dataclass fields named after the PRD's eleven `NUMERIC(10,2)` columns
    (§7.22). `net_owner_result` is derived here so the use case cannot forget the formula —
    `net_revenue - sum(cost_columns)` — and so the entity can stay a dataclass without
    the business rule of how `net_owner_result` is computed.

    `reservations` and `expenses_by_category` are kept on the breakdown for the PDF
    renderer (R6.4), which consumes them without re-querying. The use case builds the
    breakdown from a `MonetaryAggregator` and hands both pieces to the renderer.
    """

    gross_revenue: Decimal
    ota_commissions: Decimal
    net_revenue: Decimal
    cleaning_costs: Decimal
    laundry_costs: Decimal
    amenities_costs: Decimal
    maintenance_costs: Decimal
    specialist_costs: Decimal
    platform_fee: Decimal
    other_costs: Decimal
    net_owner_result: Decimal
    #: Source reservations, kept for the per-line breakdown on the PDF (R6.4).
    reservations: tuple[Reservation, ...]
    #: Source expenses grouped by category, kept for the per-category table on the PDF.
    expenses_by_category: dict[ExpenseCategory, tuple[Expense, ...]]


#: Maps the seven `ExpenseCategory` values to the field name on `StatementBreakdown` and
#: `OwnerStatement` (PRD §7.22, design D6.1). One table so the eleven columns have one
#: home and the aggregator cannot drift from the entity.
_CATEGORY_TO_FIELD: Mapping[ExpenseCategory, str] = {
    ExpenseCategory.CLEANING: "cleaning_costs",
    ExpenseCategory.LAUNDRY: "laundry_costs",
    ExpenseCategory.AMENITIES: "amenities_costs",
    ExpenseCategory.MAINTENANCE: "maintenance_costs",
    ExpenseCategory.SPECIALIST: "specialist_costs",
    ExpenseCategory.PLATFORM_FEE: "platform_fee",
    ExpenseCategory.OTHER: "other_costs",
}


class CurrencyFilter:
    """Decide whether the period may produce a statement, before any money is summed (D3).

    The strategy is **abort on mixed currencies** — V1's only option without a
    `tenant_configs.statement_currency` migration. The aggregator then sums only EUR rows;
    a single non-EUR row of either table refuses the whole `(tenant, property, period)`.

    The check is structural rather than by-row aggregation: `CurrencyFilter.check` runs
    first, on raw rows, before the aggregator ever runs. That ordering matters because
    `MonetaryAggregator.aggregate` assumes all input rows are EUR — calling it on a mixed
    set would silently sum across currencies and produce a `net_owner_result` that does
    not mean what the owner thinks it means. The aggregator therefore **trusts** its
    caller to have run the filter, and the use case calls them in the right order.
    """

    @staticmethod
    def check(
        *,
        reservations: Sequence[Reservation],
        expenses: Sequence[Expense],
    ) -> list[tuple[str, str, str]]:
        """Return the list of offending `(row_id, currency, table)` pairs, or empty.

        The list is empty when the period is safe to aggregate. The use case reports it
        as `currency_mismatch` so the manager can fix it (D3 / R2.6).
        """
        mismatches: list[tuple[str, str, str]] = []
        for reservation in reservations:
            if reservation.currency != "EUR":
                mismatches.append((str(reservation.id), reservation.currency, "reservations"))
        for expense in expenses:
            if expense.currency != "EUR":
                mismatches.append((str(expense.id), expense.currency, "expenses"))
        return mismatches


class MonetaryAggregator:
    """Sum the eleven columns of a closed monthly period (D6.1).

    Reads pre-filtered rows (the use case has already aborted on non-EUR). All amounts
    are `Decimal`, so the column types the schema declares (`NUMERIC(10,2)`) match what
    we add. Zero `Decimal` for the empty buckets — never `None`, never `0` from `int`.

    Two filters applied to the `Expense` set before summation (D6.1, D4):

    * `statement_id IS NULL` — a row already consolidated into another statement does
      not contribute here. The repository's `list_for_period` does **not** filter on this
      column, because the same method backs the manual review path, which does want to
      see all rows. The aggregator is the single place that drops the already-consolidated
      ones for the **calculation** view.
    * `approved_by IS NOT NULL OR amount <= threshold_eur` — the threshold bypass of
      R5.7 / D4. A row whose `OwnerApproval(OTHER)` is `PENDING` is not yet approved and
      must not contribute until the reconciliation of D4 materialises the answer.

    `threshold_eur` is the tenant's `TenantConfig.owner_approval_threshold_eur`, passed
    in by the use case (the aggregator is not the home of that field).
    """

    def __init__(self, *, threshold_eur: Decimal) -> None:
        self._threshold_eur = threshold_eur

    def aggregate(
        self,
        *,
        reservations: Sequence[Reservation],
        expenses: Sequence[Expense],
    ) -> StatementBreakdown:
        """Sum a period, returning the eleven columns + the source rows for the PDF.

        Empty input → all columns zero, both `reservations` and `expenses_by_category`
        empty. A period with only expenses and no reservations still has
        `net_revenue = 0` (no income to net) and the eleven cost columns populated.
        """
        gross_revenue = Decimal("0")
        ota_commissions = Decimal("0")
        for reservation in reservations:
            gross_revenue += reservation.gross_amount or Decimal("0")
            ota_commissions += reservation.ota_commission or Decimal("0")
        net_revenue = gross_revenue - ota_commissions

        buckets: dict[str, Decimal] = {name: Decimal("0") for name in _CATEGORY_TO_FIELD.values()}
        kept_expenses: list[Expense] = []
        expenses_by_category: dict[ExpenseCategory, list[Expense]] = {
            category: [] for category in ExpenseCategory
        }
        for expense in expenses:
            if expense.statement_id is not None:
                # Already consolidated into another statement — not this period's bill.
                continue
            if (
                expense.amount > self._threshold_eur
                and expense.approved_by is None
            ):
                # R5.7 / D4: pending owner approval. The reconciliation will either
                # set `approved_by` (then it counts) or DELETE the row (then it never
                # counts). Until then, the period that produced the statement must not
                # see it.
                continue
            field_name = _CATEGORY_TO_FIELD[expense.category]
            buckets[field_name] += expense.amount
            kept_expenses.append(expense)
            expenses_by_category[expense.category].append(expense)

        net_owner_result = net_revenue - sum(buckets.values())

        return StatementBreakdown(
            gross_revenue=gross_revenue,
            ota_commissions=ota_commissions,
            net_revenue=net_revenue,
            cleaning_costs=buckets["cleaning_costs"],
            laundry_costs=buckets["laundry_costs"],
            amenities_costs=buckets["amenities_costs"],
            maintenance_costs=buckets["maintenance_costs"],
            specialist_costs=buckets["specialist_costs"],
            platform_fee=buckets["platform_fee"],
            other_costs=buckets["other_costs"],
            net_owner_result=net_owner_result,
            reservations=tuple(reservations),
            expenses_by_category={
                category: tuple(rows) for category, rows in expenses_by_category.items()
            },
        )
