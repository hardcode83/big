"""How the detail's money block is decided (`dashboard-api` R2.1, PRD §9.2).

**A rule, not orchestration, which is why it lives here.** The architect panel of section 6
was right that this sat in `application/use_cases.py`: `steering/backend-architecture.md`
puts "Reglas de negocio propias (si hay una regla, pertenece a `domain/`)" among the things
`application/` must not contain, and choosing what a currency figure *means* when the data
does not agree is exactly such a rule. Its neighbours here are `next_action.py` and
`labels.py`, which are rules of the same kind.

**The problem it exists to solve.** `ExpenseReader.summary_for_property` reports a total
**per currency** and refuses to collapse them — its own docstring records why: amounts in
different currencies are not comparable, and any single figure it returned would either pick
one silently or add up unlike things. But `frontend/features/dashboard/data/dto.ts:146-150`
wants one `pendingExpenses` and one `currency`. Somebody has to choose, and this is the
somebody.

**ASSUMPTION.** Neither the PRD nor the frontend contract says what to do with a property
that has pending expenses in two currencies. The choice made here is to say **nothing**
rather than something wrong: a single currency reports its total, and anything else reports
`null`. Inventing an exchange rate would be worse than an empty figure, and summing across
currencies would be a number that is simply false. A property billing in two currencies is
not a case the MVP has; if it becomes one, this is the one place that decides.

Pure Python, and deliberately built from primitives rather than from a `Reservation`: the
rule is about a currency and two amounts, and taking the entity would couple this module to
another domain for no gain.
"""

from collections.abc import Mapping
from decimal import Decimal

from app.dashboard.domain.read_models import FinancialBlock

#: The currency reported when nothing else determines one. `expenses.currency` defaults to
#: `EUR` in the schema and the product operates in Spain (PRD §27).
DEFAULT_CURRENCY = "EUR"


def financial_block(
    *,
    reservation_currency: str | None,
    reservation_total: Decimal | None,
    pending_expenses: Mapping[str, Decimal],
) -> FinancialBlock:
    """The money block for one property.

    * **No pending expenses** — the common case today, since `expenses` has no writer until
      `revenue`: the reservation's own currency and total, and `pending_expenses: None`.
      `None` and not `Decimal("0")`, because "nothing recorded" and "nothing owed" are
      different facts and only the first one is known.
    * **One pending currency** — that currency and that total. The reservation's total rides
      along only if it is denominated the same way; otherwise it is `None`, because two
      figures under one currency label would misread as comparable.
    * **Several pending currencies** — the reservation's currency, and `None` for the
      pending total. See the `ASSUMPTION` above.
    """
    currency = reservation_currency or DEFAULT_CURRENCY

    if len(pending_expenses) == 1:
        [(pending_currency, total)] = pending_expenses.items()
        return FinancialBlock(
            currency=pending_currency,
            reservation_total=reservation_total if pending_currency == currency else None,
            pending_expenses=total,
        )

    return FinancialBlock(
        currency=currency,
        reservation_total=reservation_total,
        pending_expenses=None,
    )
