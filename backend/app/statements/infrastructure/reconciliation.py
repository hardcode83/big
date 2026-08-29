"""SQLAlchemy adapter for the `ReconciliationStore` port (D4).

The use case (`ReconcileOwnerApprovalsForExpensesUseCase`) does not import
`sqlalchemy`; this module is the **only** place in `statements/` that issues the
D4 SQL. The architecture rule (`steering/backend-architecture.md`) asks for that
separation explicitly.

The two queries — materialise and inconsistencies — both filter by `tenant_id`
(regla 1). The first carries the JOIN's `e.tenant_id = oa.tenant_id`; the second
projects `e.tenant_id` so the period lookup can filter by it. UUID collisions
are astronomical, so the practical leakage into the log line would be zero
without the guard — but the rule applies regardless.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.maintenance.domain.enums import OwnerApprovalRelatedType
from app.maintenance.infrastructure.models import OwnerApprovalModel
from app.statements.application.reconciliation import (
    FailedReconciliation,
    ReconciliationReport,
    ReconciliationStore,
    _InconsistentRow,
    _PendingRow,
)
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel


@dataclass(frozen=True)
class _Period:
    """The period of a statement, projected to its date components."""

    period_start: date
    period_end: date


class SqlAlchemyReconciliationStore(ReconciliationStore):
    """The only implementation of `ReconciliationStore` (D4)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fetch_pending(self) -> Sequence[_PendingRow]:
        rows = await self._session.execute(
            select(
                OwnerApprovalModel.id,
                OwnerApprovalModel.status,
                OwnerApprovalModel.responded_by,
                OwnerApprovalModel.related_id,
                OwnerApprovalModel.tenant_id,
            )
            .join(
                ExpenseModel,
                (ExpenseModel.id == OwnerApprovalModel.related_id)
                & (ExpenseModel.tenant_id == OwnerApprovalModel.tenant_id),
            )
            .where(
                OwnerApprovalModel.related_type == OwnerApprovalRelatedType.OTHER.value,
                OwnerApprovalModel.responded_at.is_not(None),
                # Both sub-conditions of D4's main guard, OR'd together. Each branch
                # carries its own preconditions on `expenses`.
                (
                    (
                        (OwnerApprovalModel.status == "APPROVED")
                        & ExpenseModel.approved_by.is_(None)
                        & ExpenseModel.statement_id.is_(None)
                    )
                    | (
                        (OwnerApprovalModel.status == "REJECTED")
                        & ExpenseModel.statement_id.is_(None)
                    )
                ),
            )
        )
        return [
            _PendingRow(
                approval_id=row.id,
                status=row.status,
                responded_by=row.responded_by,
                expense_id=row.related_id,
                tenant_id=row.tenant_id,
            )
            for row in rows.all()
        ]

    async def materialise_approved(self, row: _PendingRow) -> bool:
        result = await self._session.execute(
            update(ExpenseModel)
            .where(
                ExpenseModel.tenant_id == row.tenant_id,
                ExpenseModel.id == row.expense_id,
                ExpenseModel.approved_by.is_(None),
                ExpenseModel.statement_id.is_(None),
            )
            .values(approved_by=row.responded_by)
        )
        return bool(result.rowcount)

    async def materialise_rejected(self, row: _PendingRow) -> bool:
        result = await self._session.execute(
            delete(ExpenseModel).where(
                ExpenseModel.tenant_id == row.tenant_id,
                ExpenseModel.id == row.expense_id,
                ExpenseModel.statement_id.is_(None),
            )
        )
        return bool(result.rowcount)

    async def fetch_inconsistencies(self) -> Sequence[_InconsistentRow]:
        rows = await self._session.execute(
            select(
                OwnerApprovalModel.id,
                OwnerApprovalModel.tenant_id,
                ExpenseModel.id,
                ExpenseModel.property_id,
                ExpenseModel.tenant_id,
                ExpenseModel.statement_id,
            )
            .join(
                ExpenseModel,
                (ExpenseModel.id == OwnerApprovalModel.related_id)
                & (ExpenseModel.tenant_id == OwnerApprovalModel.tenant_id),
            )
            .where(
                OwnerApprovalModel.related_type == OwnerApprovalRelatedType.OTHER.value,
                OwnerApprovalModel.status == "REJECTED",
                ExpenseModel.statement_id.is_not(None),
            )
        )
        return [
            _InconsistentRow(
                approval_id=row[0],
                tenant_id=row[1],
                expense_id=row[2],
                property_id=row[3],
                statement_id=row[5],
            )
            for row in rows.all()
        ]

    async def fetch_period_for(
        self, *, tenant_id, statement_id
    ) -> _Period | None:
        """Read `owner_statements.period_{start,end}` scoped by tenant.

        Public — added to the port because the period is a piece of the report
        `ReconciliationReport.failed_reconciliation` carries; without it the
        use case would have to issue its own SQL and the layering rule is back to
        being broken.
        """
        rows = await self._session.execute(
            select(
                OwnerStatementModel.period_start,
                OwnerStatementModel.period_end,
            ).where(
                OwnerStatementModel.tenant_id == tenant_id,
                OwnerStatementModel.id == statement_id,
            )
        )
        row = rows.first()
        if row is None:
            return None
        return _Period(period_start=row[0], period_end=row[1])
