"""SQLAlchemy adapter for the statements read port (`dashboard-api` R2).

First reader of `expenses`. There is no writer here and the port declares none — see
`app/statements/domain/repositories.py`.

The statement filters `tenant_id` explicitly. The session listener of `app/core/db.py` also
covers this table (it carries `TenantScopedMixin`), but it is the net and never the
mechanism.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.statements.domain.repositories import PropertyFinancialSummary
from app.statements.infrastructure.models import ExpenseModel


class SqlAlchemyExpenseReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> PropertyFinancialSummary:
        rows = await self._session.execute(
            select(ExpenseModel.currency, func.sum(ExpenseModel.amount))
            .where(
                ExpenseModel.tenant_id == tenant_id,
                ExpenseModel.property_id == property_id,
                # "Pending" is "not yet consolidated into a statement", which is what the
                # nullable FK already means (§7.23) — not a rule invented here.
                ExpenseModel.statement_id.is_(None),
            )
            .group_by(ExpenseModel.currency)
        )
        # `SUM` over a `NUMERIC(10,2)` comes back as `Decimal`; the cast is belt and braces
        # for a driver that ever hands back a float, which would silently lose cents.
        return PropertyFinancialSummary(
            pending_expenses={
                currency: Decimal(total) for currency, total in rows.all() if total is not None
            }
        )
