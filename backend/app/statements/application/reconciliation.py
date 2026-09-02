"""The reconciliation use case — turn owner answers into material changes on `expenses`.

`ReconcileOwnerApprovalsForExpensesUseCase` is the worker behind the scheduler entry
`reconcile_owner_approvals_for_expenses` (tasks 5.3 of `tasks.md`, design D4). It is
deliberately **not** part of `maintenance.application` — `RespondToOwnerApprovalUseCase`
records the answer, and this module applies it. The split is the design's own:

* `OwnerApproval(OTHER)` is the canonical way D4 created approvals for `Expense` rows
  that exceeded `TenantConfig.owner_approval_threshold_eur` (R5.7);
* the owner answers through `POST /api/v1/owner-approvals/{id}/respond`, which is the
  existing `maintenance` route — untouched by this change;
* a worker running every five minutes queries the table for `APPROVED` / `REJECTED`
  answers whose expense still needs the materialisation, and applies the answer.

The worker has **no cursor** and **no Redis key** (D4): the query is a `JOIN` on the
state of the rows, so a row that misses one tick is caught by the next. Idempotency
comes from the SQL guard (`approved_by IS NULL` for `APPROVED`, `statement_id IS NULL`
for both), not from any external state — the same row returned twice is a no-op on
the second pass.

The use case is **thin**: it takes a port (`ReconciliationStore`) that owns the
SQL. The port lives on `infrastructure/` because it speaks SQL; the application
layer imports only the report dataclasses. This is the same shape as
`pricing.GeneratePriceRecommendationsUseCase`'s split — the orchestration stays in
`application/`, the persistence in `infrastructure/`. The layering rule
(`steering/backend-architecture.md`: "application/ no importa infrastructure/") is
preserved by construction.

Two queries the store runs:

1. **Work to materialise** — joined with `expenses`; rows whose answer is `APPROVED`
   get `approved_by` set; rows whose answer is `REJECTED` get deleted; both fail
   silently on a row that has already moved on.
2. **Inconsistencies** — `REJECTED` answers whose expense is already consolidated
   (`statement_id IS NOT NULL`); reported as `failed_reconciliation` and logged, **never
   touched**: the anomaly is real data, not a transient state, and the design's
   instruction is "no lo borres ni lo interpretes como aprobado".
"""

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FailedReconciliation:
    """One inconsistent row: a `REJECTED` approval pointing at a consolidated expense.

    Five identifiers — the four a reviewer would look up plus the period the consolidated
    statement recorded. The period is read off `owner_statements` rather than the expense
    (the expense has no period column of its own) and serialised as ISO strings so the
    JSON report and the log line share one shape.
    """

    approval_id: uuid.UUID
    expense_id: uuid.UUID
    property_id: uuid.UUID
    period_start: str
    period_end: str


@dataclass
class ReconciliationReport:
    """What one tick of `reconcile_owner_approvals_for_expenses` did.

    The two counters are independent — `materialised_approved` is the count of
    `APPROVED` answers that became `expenses.approved_by`, `materialised_rejected` is
    the count of `REJECTED` answers that became a `DELETE`. `failed_reconciliation`
    collects the inconsistencies the second query surfaces — never zero by construction,
    only absent when the data is well-formed.
    """

    materialised_approved: int = 0
    materialised_rejected: int = 0
    failed_reconciliation: list[FailedReconciliation] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.materialised_approved
            + self.materialised_rejected
            + len(self.failed_reconciliation)
        )


@dataclass(frozen=True)
class _PendingRow:
    """One row from the pending query, joined with the approval's tenant id.

    The pending SELECT does not project `tenant_id` (the JOIN condition already enforces
    equality, so re-fetching it would be a column we don't need to read), but the
    materialise UPDATEs need it as a guard — the store filters `tenant_id =
    row.tenant_id` so a same-id, wrong-tenant pair cannot land on the write.
    """

    approval_id: uuid.UUID
    status: str
    responded_by: uuid.UUID | None
    expense_id: uuid.UUID
    tenant_id: uuid.UUID


@dataclass(frozen=True)
class _InconsistentRow:
    """One inconsistency: the approval's id, the expense's id, the property, and the
    tenant it belongs to. The period is fetched by the store in a second query and
    attached to the row before the use case hands the report off."""

    approval_id: uuid.UUID
    expense_id: uuid.UUID
    property_id: uuid.UUID
    tenant_id: uuid.UUID
    statement_id: uuid.UUID


class ReconciliationStore(Protocol):
    """The persistence port for the reconciliation worker (D4).

    Methods are the only SQL-bearing surface of this module; the use case above does
    not import `sqlalchemy` or any `infrastructure/` model. Wiring hands it
    `SqlAlchemyReconciliationStore` (in `infrastructure/reconciliation.py`), whose
    implementation is the SQL the design D4 names.
    """

    async def fetch_pending(self) -> Sequence[_PendingRow]:
        """The rows whose answer still needs materialising.

        No cursor (D4): the JOIN is on row state, so re-running it picks up whatever
        landed between ticks. `tenant_id` is read from the approval row, which the JOIN
        carries, because the materialise step needs it as a SQL guard.
        """
        ...

    async def materialise_approved(self, row: _PendingRow) -> bool:
        """One row's UPDATE for an `APPROVED` answer.

        `True` when the guard matched (and `approved_by` was set); `False` when the row
        no longer matches the guard — the row moved on between the SELECT and the
        write, and the next tick will skip it because the JOIN won't return it.
        """
        ...

    async def materialise_rejected(self, row: _PendingRow) -> bool:
        """One row's DELETE for a `REJECTED` answer.

        Same idempotency guarantee as `materialise_approved`: the SQL guard
        (`statement_id IS NULL`) is the contract, not external state.
        """
        ...

    async def fetch_inconsistencies(self) -> Sequence[_InconsistentRow]:
        """The `REJECTED` approvals whose expense is already consolidated.

        Every row is scoped by `tenant_id`: the SQL layer carries the approval's and
        expense's tenant ids and the second-step period lookup filters by it too.
        Regla 1 of `steering/security.md` is enforced here, not at the use case.
        """
        ...


class ReconcileOwnerApprovalsForExpensesUseCase:
    """Apply owner answers to the `expenses` rows they were raised against.

    One transactional boundary per tick: the store's writes commit when the use case
    commits. An exception during materialisation propagates and the scheduler retries
    on the next tick — the SQL is idempotent, so a retry costs nothing extra.
    """

    def __init__(self, *, store: ReconciliationStore, commit: Callable[[], Awaitable[None]]) -> None:
        self._store = store
        self._commit = commit

    async def execute(self, *, now: datetime) -> ReconciliationReport:
        """Run the two queries, return a report, leave the database consistent.

        `now` is accepted to keep the signature parallel with the other use cases and
        to leave room for a future "only answered within the last window" filter; today
        no row is filtered by `now`, so it is unused.
        """
        del now  # see docstring
        report = ReconciliationReport()
        pending = await self._store.fetch_pending()
        for row in pending:
            applied = (
                await self._store.materialise_approved(row)
                if row.status == "APPROVED"
                else await self._store.materialise_rejected(row)
            )
            if applied:
                if row.status == "APPROVED":
                    report.materialised_approved += 1
                elif row.status == "REJECTED":
                    report.materialised_rejected += 1
        report.failed_reconciliation = await self._fetch_inconsistencies_with_period()
        for inconsistency in report.failed_reconciliation:
            logger.error(
                "statements.reconciliation_inconsistency",
                extra={
                    "approval_id": str(inconsistency.approval_id),
                    "expense_id": str(inconsistency.expense_id),
                    "property_id": str(inconsistency.property_id),
                    "period_start": inconsistency.period_start,
                    "period_end": inconsistency.period_end,
                },
            )
        await self._commit()
        return report

    async def _fetch_inconsistencies_with_period(self) -> list[FailedReconciliation]:
        """Decorate each `_InconsistentRow` with the period read off `owner_statements`.

        The store already returns the row's tenant id; we ask the store again for the
        period, scoped by tenant, so regla 1 holds end-to-end.
        """
        rows = await self._store.fetch_inconsistencies()
        results: list[FailedReconciliation] = []
        for row in rows:
            period = await self._store.fetch_period_for(
                tenant_id=row.tenant_id, statement_id=row.statement_id
            )
            results.append(
                FailedReconciliation(
                    approval_id=row.approval_id,
                    expense_id=row.expense_id,
                    property_id=row.property_id,
                    period_start=period.period_start.isoformat() if period else "",
                    period_end=period.period_end.isoformat() if period else "",
                )
            )
        return results
