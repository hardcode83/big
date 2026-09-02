"""Ports owned by the statements domain (`dashboard-api` R2, design D2).

**The first port this module had, and read-only on purpose** — the same shape and the
same reasoning as `app/maintenance/domain/repositories.py`, which arrived in the same
change. `statements` has been entities plus schema since `domain-foundation-financial`, with
no use case to justify a port; `dashboard-api` gives it a reader (PRD §9.2 wants a financial
block on the property detail) and no writer. Consolidating expenses into a statement,
computing `net_owner_result` and sending it to an owner all arrive with `revenue`, which
owns those invariants.

**`revenue` adds writers** (design D2): `OwnerStatementRepository` covers the statement
lifecycle (CRUD + listing + period aggregation); `ExpenseRepository` covers expense CRUD,
the consolidation link, the pending-approval lookup for `ExpenseResponse`, and the
period query the `MonetaryAggregator` consumes. The pre-existing `ExpenseReader` stays
intact — `dashboard-api` is its only caller and we do not break it.

Returns nothing but facts. What the detail page shows — one figure and one currency — is a
presentation decision, and this port refuses to make it: see `PropertyFinancialSummary`.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.statements.domain.entities import Expense, OwnerStatement
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus


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


@dataclass(frozen=True)
class OwnerStatementFilters:
    """Filter set for `OwnerStatementRepository.list_paginated` (R3.1).

    Each field is **optional and combined with AND** when set. A `None` means "do not
    filter on this dimension". The repository applies the tenant scope before any of these.
    """

    property_id: uuid.UUID | None = None
    period_start_from: date | None = None
    period_start_to: date | None = None
    status: OwnerStatementStatus | None = None


@dataclass(frozen=True)
class ExpenseFilters:
    """Filter set for `ExpenseRepository.list_paginated` (R5).

    `statement_id_filter` accepts three values: `None` (do not filter), `True`
    (`statement_id IS NOT NULL`), `False` (`statement_id IS NULL`). Booleans-as-state
    cannot be optional with a tri-state default, so the explicit filter wrapper keeps the
    call site readable.
    """

    property_id: uuid.UUID | None = None
    period_start_from: date | None = None
    period_start_to: date | None = None
    category: ExpenseCategory | None = None


class OwnerStatementRepository(Protocol):
    """Write/read surface for `OwnerStatement` (design D2)."""

    async def get(
        self, tenant_id: uuid.UUID, statement_id: uuid.UUID
    ) -> OwnerStatement | None:
        """Returns `None` for both "not found" and "wrong tenant" — the API maps both to 404
        with the same body, so a reader that distinguishes would let callers enumerate."""
        ...

    async def find_by_unique_key(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> OwnerStatement | None:
        """The idempotency lookup of R1.3 / R2.3 / D6.1.

        `uq_owner_statements_tenant_property_period` guarantees at most one row.
        Returns `None` outside the tenant — same contract as `get`.
        """
        ...

    async def list_paginated(
        self,
        tenant_id: uuid.UUID,
        filters: OwnerStatementFilters,
        *,
        page: int,
        per_page: int,
    ) -> tuple[Sequence[OwnerStatement], int]:
        """Returns `(items, total)`. Page size is fixed at 20 server-side per D9."""
        ...

    async def add(self, statement: OwnerStatement) -> None:
        ...

    async def save(self, statement: OwnerStatement) -> None:
        """Persists the current entity state. Used by status transitions and notes updates
        — neither writes the money columns, which are set only by `GenerateOwnerStatement`."""
        ...


class ExpenseRepository(Protocol):
    """Write/read surface for `Expense` (design D2)."""

    async def get(
        self, tenant_id: uuid.UUID, expense_id: uuid.UUID
    ) -> Expense | None:
        ...

    async def list_paginated(
        self,
        tenant_id: uuid.UUID,
        filters: ExpenseFilters,
        *,
        page: int,
        per_page: int,
    ) -> tuple[Sequence[Expense], int]:
        ...

    async def add(self, expense: Expense) -> None:
        ...

    async def save(self, expense: Expense) -> None:
        """Persists the current entity state. The immutability rule of D6.2 lives in the
        SQLAlchemy adapter, not here — the protocol declares the contract (`save` accepts
        any expense) and the adapter enforces which fields move once `statement_id` is set.

        The reconciliation job of D4 calls `save` to set `approved_by`. That write target is
        auditable when called by a person, and ignored when the audit row is built by the
        job (the `_AuditWriter` of §4.1 rejects without actor). The shape of `save` does not
        change either way.
        """
        ...

    async def delete(self, tenant_id: uuid.UUID, expense: Expense) -> None:
        """Removes a single `Expense` row. The consolidation guard of D6.2 lives in the
        adapter: a `delete` on a row whose `statement_id IS NOT NULL` raises
        `ExpenseAlreadyConsolidatedError` rather than succeeding silently.

        The use case `DeleteExpenseUseCase` already checks the field before calling
        here; the adapter's check is the second line of defence for any future caller
        that forgot.
        """
        ...

    async def find_closed_period(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        date_: date,
    ) -> OwnerStatement | None:
        """D6.3 — the period of `property_id` that already covers `date_`, if any.

        Used by `CreateExpenseUseCase` and `UpdateExpenseUseCase` to refuse a write whose
        `date` would land in a closed period. Returns the **statement** rather than a
        bare `(start, end)` so the caller can name it in the error body.
        """
        ...

    async def list_for_period(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> Sequence[Expense]:
        """D6.1 — read by `MonetaryAggregator`. Filters by `[period_start, period_end]`
        intersection with `[expense.date, expense.date]`."""
        ...

    async def list_pending_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[Expense]:
        """Reads only `statement_id IS NULL`, ordered by `date DESC` for the manager view."""
        ...

    async def bulk_associate_to_statement(
        self,
        tenant_id: uuid.UUID,
        expense_ids: Sequence[uuid.UUID],
        statement_id: uuid.UUID,
    ) -> int:
        """D6.1 — `UPDATE expenses SET statement_id = :new WHERE id = ANY(:ids) AND tenant_id
        = :t AND statement_id IS NULL`. Idempotent: a second call returns `0` (no rows
        match because the first already set `statement_id`). Returns the rowcount."""
        ...

    async def find_pending_owner_approval_for(
        self, tenant_id: uuid.UUID, expense_id: uuid.UUID
    ) -> uuid.UUID | None:
        """D13 — returns the `id` of the `OwnerApproval(OTHER, status=PENDING)` that
        references the given expense, or `None` if none exists. Joins across modules via
        `OwnerApprovalRepository`; the statements module depends on `maintenance`'s port.

        `tenant_id` is **mandatory**: regla 1 of `steering/security.md` requires every
        query to scope by tenant. The cross-tenant lookup is blocked at the SQL layer by
        `oa.tenant_id = :tenant_id`, even though `related_id` is a UUID that by itself
        would not let a leak reach the row. The steering rule wins over D13's earlier
        omission (a deviation noted by the panel in section 3, fix-rounds).
        """
        ...
