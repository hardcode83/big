"""Ports owned by the statements domain (`dashboard-api` R2, design D2).

**The first port this module has ever had, and read-only on purpose** — the same shape and
the same reasoning as `app/maintenance/domain/repositories.py`, which arrived in the same
change. `statements` has been entities plus schema since `domain-foundation-financial`, with
no use case to justify a port; `dashboard-api` gives it a reader (PRD §9.2 wants a financial
block on the property detail) and no writer. Consolidating expenses into a statement,
computing `net_owner_result` and sending it to an owner all arrive with `revenue`, which
owns those invariants. **No `add`, no `save`.** The signature is where that boundary lives.

Returns nothing but facts. What the detail page shows — one figure and one currency — is a
presentation decision, and this port refuses to make it: see `PropertyFinancialSummary`.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class PropertyFinancialSummary:
    """What a property owes that no statement has absorbed yet (PRD §9.2, R2.3).

    **`pending_expenses` is keyed by currency, and that is not over-engineering.**
    `expenses.currency` is a per-row `String(3)`, so a property genuinely can hold rows in
    more than one, and any single `Decimal` this port could return would have to either
    pick one silently or add up amounts that are not comparable. Reporting the totals as
    they are keeps this layer factual; the `dashboard` use case decides how to present them
    and marks its own `ASSUMPTION` for the multi-currency case, where the decision belongs.

    An empty mapping means "nothing pending", which is what every property answers today —
    `expenses` has no writer until `revenue` (design D9). That is the correct answer and
    not a stub: the contract does not change when `revenue` lands, only the data.
    """

    pending_expenses: Mapping[str, Decimal]


class ExpenseReader(Protocol):
    """Read-only. Named `Reader` rather than `Repository` so the absence of writers is
    visible at the call site and not only in this file."""

    async def summary_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> PropertyFinancialSummary:
        """The property's unconsolidated expenses, totalled per currency.

        "Unconsolidated" is `statement_id IS NULL`, which the schema already defines as its
        meaning: `domain-foundation-financial` made the column "nullable until the expense
        is consolidated into a statement (§7.23)". So this is not a rule invented here — it
        reads one the schema already carries.

        Never `None`: a property with no expenses gets a summary with an empty mapping, so
        the caller has one shape to handle rather than two.
        """
        ...
