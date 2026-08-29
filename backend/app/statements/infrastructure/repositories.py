"""SQLAlchemy adapter for the statements read port (`dashboard-api` R2).

First reader of `expenses`. There is no writer here and the port declares none — see
`app/statements/domain/repositories.py`.

The statement filters `tenant_id` explicitly. The session listener of `app/core/db.py` also
covers this table (it carries `TenantScopedMixin`), but it is the net and never the
mechanism.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, delete as sqla_delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.statements.domain.entities import Expense, OwnerStatement
from app.statements.domain.exceptions import ExpenseAlreadyConsolidatedError
from app.statements.domain.repositories import (
    ExpenseFilters,
    OwnerStatementFilters,
    PropertyFinancialSummary,
)
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel


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


# ---- `revenue-statements` adapters -----------------------------------------------------


#: Fields a consolidated `Expense` must not mutate (design D6.2). `statement_id` and
#: `approved_by` are listed too: the first is the consolidation marker itself (mutating it
#: would be a regenerate, V1-prohibited); the second is the audit trail of the threshold
#: approval — letting it move post-hoc would break the proof of who approved what.
_EXPENSE_IMMUTABLE_WHEN_CONSOLIDATED: frozenset[str] = frozenset(
    {
        "amount",
        "currency",
        "category",
        "date",
        "property_id",
        "statement_id",
        "approved_by",
    }
)


def _owner_statement_to_domain(model: OwnerStatementModel) -> OwnerStatement:
    return OwnerStatement(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        period_start=model.period_start,
        period_end=model.period_end,
        created_at=model.created_at,
        updated_at=model.updated_at,
        gross_revenue=model.gross_revenue,
        ota_commissions=model.ota_commissions,
        net_revenue=model.net_revenue,
        cleaning_costs=model.cleaning_costs,
        laundry_costs=model.laundry_costs,
        amenities_costs=model.amenities_costs,
        maintenance_costs=model.maintenance_costs,
        specialist_costs=model.specialist_costs,
        platform_fee=model.platform_fee,
        other_costs=model.other_costs,
        net_owner_result=model.net_owner_result,
        status=model.status,
        notes=model.notes,
    )


def _expense_to_domain(model: ExpenseModel) -> Expense:
    return Expense(
        id=model.id,
        tenant_id=model.tenant_id,
        property_id=model.property_id,
        category=model.category,
        description=model.description,
        amount=model.amount,
        date=model.date,
        created_at=model.created_at,
        statement_id=model.statement_id,
        incident_id=model.incident_id,
        currency=model.currency,
        receipt_storage_key=model.receipt_storage_key,
        approved_by=model.approved_by,
    )


class SqlAlchemyOwnerStatementRepository:
    """SQLAlchemy adapter for `OwnerStatementRepository` (design D2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: uuid.UUID, statement_id: uuid.UUID
    ) -> OwnerStatement | None:
        result = await self._session.execute(
            select(OwnerStatementModel).where(
                OwnerStatementModel.tenant_id == tenant_id,
                OwnerStatementModel.id == statement_id,
            )
        )
        model = result.scalar_one_or_none()
        return _owner_statement_to_domain(model) if model else None

    async def list_paginated(
        self,
        tenant_id: uuid.UUID,
        filters: OwnerStatementFilters,
        *,
        page: int,
        per_page: int,
    ) -> tuple[Sequence[OwnerStatement], int]:
        conditions = [OwnerStatementModel.tenant_id == tenant_id]
        if filters.property_id is not None:
            conditions.append(OwnerStatementModel.property_id == filters.property_id)
        if filters.period_start_from is not None:
            conditions.append(OwnerStatementModel.period_start >= filters.period_start_from)
        if filters.period_start_to is not None:
            conditions.append(OwnerStatementModel.period_start <= filters.period_start_to)
        if filters.status is not None:
            conditions.append(OwnerStatementModel.status == filters.status)
        offset = (page - 1) * per_page
        rows = await self._session.execute(
            select(OwnerStatementModel)
            .where(and_(*conditions))
            .order_by(OwnerStatementModel.period_start.desc(), OwnerStatementModel.id)
            .offset(offset)
            .limit(per_page)
        )
        total = await self._session.execute(
            select(func.count())
            .select_from(OwnerStatementModel)
            .where(and_(*conditions))
        )
        items = [_owner_statement_to_domain(m) for m in rows.scalars().all()]
        return items, int(total.scalar_one())

    async def find_by_unique_key(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> OwnerStatement | None:
        """D6.1 — idempotency lookup for the generator.

        `uq_owner_statements_tenant_property_period` guarantees at most one row per
        `(tenant, property, period)`. The query filters by tenant first so a
        neighbour's id can never reach this row.
        """
        result = await self._session.execute(
            select(OwnerStatementModel).where(
                OwnerStatementModel.tenant_id == tenant_id,
                OwnerStatementModel.property_id == property_id,
                OwnerStatementModel.period_start == period_start,
                OwnerStatementModel.period_end == period_end,
            )
        )
        model = result.scalar_one_or_none()
        return _owner_statement_to_domain(model) if model else None

    async def add(self, statement: OwnerStatement) -> None:
        self._session.add(
            OwnerStatementModel(
                id=statement.id,
                tenant_id=statement.tenant_id,
                property_id=statement.property_id,
                period_start=statement.period_start,
                period_end=statement.period_end,
                gross_revenue=statement.gross_revenue,
                ota_commissions=statement.ota_commissions,
                net_revenue=statement.net_revenue,
                cleaning_costs=statement.cleaning_costs,
                laundry_costs=statement.laundry_costs,
                amenities_costs=statement.amenities_costs,
                maintenance_costs=statement.maintenance_costs,
                specialist_costs=statement.specialist_costs,
                platform_fee=statement.platform_fee,
                other_costs=statement.other_costs,
                net_owner_result=statement.net_owner_result,
                status=statement.status,
                notes=statement.notes,
            )
        )

    async def save(self, statement: OwnerStatement) -> None:
        """The only fields the use case ever moves on an existing statement are `status`
        and `notes` (R4.1, R4.5). Writing those as a single UPDATE keeps the SQL narrow.
        """
        await self._session.execute(
            update(OwnerStatementModel)
            .where(
                OwnerStatementModel.tenant_id == statement.tenant_id,
                OwnerStatementModel.id == statement.id,
            )
            .values(
                status=statement.status,
                notes=statement.notes,
                updated_at=statement.updated_at,
            )
        )


class SqlAlchemyExpenseRepository:
    """SQLAlchemy adapter for `ExpenseRepository` (design D2, D6.2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: uuid.UUID, expense_id: uuid.UUID
    ) -> Expense | None:
        result = await self._session.execute(
            select(ExpenseModel).where(
                ExpenseModel.tenant_id == tenant_id,
                ExpenseModel.id == expense_id,
            )
        )
        model = result.scalar_one_or_none()
        return _expense_to_domain(model) if model else None

    async def list_paginated(
        self,
        tenant_id: uuid.UUID,
        filters: ExpenseFilters,
        *,
        page: int,
        per_page: int,
    ) -> tuple[Sequence[Expense], int]:
        conditions = [ExpenseModel.tenant_id == tenant_id]
        if filters.property_id is not None:
            conditions.append(ExpenseModel.property_id == filters.property_id)
        if filters.period_start_from is not None:
            conditions.append(ExpenseModel.date >= filters.period_start_from)
        if filters.period_start_to is not None:
            conditions.append(ExpenseModel.date <= filters.period_start_to)
        if filters.category is not None:
            conditions.append(ExpenseModel.category == filters.category)
        offset = (page - 1) * per_page
        rows = await self._session.execute(
            select(ExpenseModel)
            .where(and_(*conditions))
            .order_by(ExpenseModel.date.desc(), ExpenseModel.id)
            .offset(offset)
            .limit(per_page)
        )
        total = await self._session.execute(
            select(func.count()).select_from(ExpenseModel).where(and_(*conditions))
        )
        items = [_expense_to_domain(m) for m in rows.scalars().all()]
        return items, int(total.scalar_one())

    async def add(self, expense: Expense) -> None:
        self._session.add(
            ExpenseModel(
                id=expense.id,
                tenant_id=expense.tenant_id,
                property_id=expense.property_id,
                category=expense.category,
                description=expense.description,
                amount=expense.amount,
                currency=expense.currency,
                date=expense.date,
                statement_id=expense.statement_id,
                incident_id=expense.incident_id,
                receipt_storage_key=expense.receipt_storage_key,
                approved_by=expense.approved_by,
            )
        )

    async def save(self, expense: Expense) -> None:
        """D6.2 immutability lives here, not in the entity.

        We load the persisted row first; if `statement_id IS NOT NULL`, every field in
        `_EXPENSE_IMMUTABLE_WHEN_CONSOLIDATED` is compared against the in-memory copy and
        raises `ExpenseAlreadyConsolidatedError(field_name)` on the first difference.
        A consolidated row may still move `description` and `receipt_storage_key`, which
        is the boundary the design fixes.

        The load-then-compare approach is cheap (one `SELECT` per save, indexed by PK) and
        self-explanatory; the alternative — a single `UPDATE … WHERE old_values` — would
        race against concurrent `description`-only updates and would not give a field name.

        **Row lock**: `with_for_update()` acquires a `FOR UPDATE` lock so a concurrent
        `bulk_associate_to_statement` (which writes `statement_id`) cannot race past the
        immutability check between the SELECT and the UPDATE below. Without the lock, the
        sequence `T1: load → check → T2: associate → T1: UPDATE` would let `T1` mutate
        fields on a row that became consolidated between the two steps. The lock serializes
        T1 and T2 on the row; whichever wins, the post-condition matches the design.
        """
        result = await self._session.execute(
            select(ExpenseModel)
            .where(
                ExpenseModel.tenant_id == expense.tenant_id,
                ExpenseModel.id == expense.id,
            )
            .with_for_update()
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            return  # caller asked to save an expense that does not exist; nothing to do
        if existing.statement_id is not None:
            for field in _EXPENSE_IMMUTABLE_WHEN_CONSOLIDATED:
                if getattr(existing, field) != getattr(expense, field):
                    raise ExpenseAlreadyConsolidatedError(
                        f"{field} is immutable after consolidation",
                        field=field,
                    )
        await self._session.execute(
            update(ExpenseModel)
            .where(
                ExpenseModel.tenant_id == expense.tenant_id,
                ExpenseModel.id == expense.id,
            )
            .values(
                category=expense.category,
                description=expense.description,
                amount=expense.amount,
                currency=expense.currency,
                date=expense.date,
                property_id=expense.property_id,
                receipt_storage_key=expense.receipt_storage_key,
            )
        )

    async def list_for_period(
        self,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> Sequence[Expense]:
        rows = await self._session.execute(
            select(ExpenseModel)
            .where(
                ExpenseModel.tenant_id == tenant_id,
                ExpenseModel.property_id == property_id,
                ExpenseModel.date >= period_start,
                ExpenseModel.date <= period_end,
            )
            .order_by(ExpenseModel.date.asc(), ExpenseModel.id)
        )
        return [_expense_to_domain(m) for m in rows.scalars().all()]

    async def list_pending_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[Expense]:
        rows = await self._session.execute(
            select(ExpenseModel)
            .where(
                ExpenseModel.tenant_id == tenant_id,
                ExpenseModel.property_id == property_id,
                ExpenseModel.statement_id.is_(None),
            )
            .order_by(ExpenseModel.date.desc(), ExpenseModel.id)
        )
        return [_expense_to_domain(m) for m in rows.scalars().all()]

    async def bulk_associate_to_statement(
        self,
        tenant_id: uuid.UUID,
        expense_ids: Sequence[uuid.UUID],
        statement_id: uuid.UUID,
    ) -> int:
        """D6.1 — single `UPDATE`, idempotent thanks to `statement_id IS NULL`.

        Empty `expense_ids` returns `0` — no UPDATE is issued.
        """
        if not expense_ids:
            return 0
        result = await self._session.execute(
            update(ExpenseModel)
            .where(
                ExpenseModel.tenant_id == tenant_id,
                ExpenseModel.id.in_(list(expense_ids)),
                ExpenseModel.statement_id.is_(None),
            )
            .values(statement_id=statement_id)
        )
        return int(result.rowcount or 0)

    async def find_pending_owner_approval_for(
        self, tenant_id: uuid.UUID, expense_id: uuid.UUID
    ) -> uuid.UUID | None:
        """D13 — joins across modules via `OwnerApprovalModel`.

        The dependency runs from `statements` → `maintenance.infrastructure.models`, not
        from `maintenance.application`. The boundary is the SQL layer; the `OwnerApproval`
        port in `maintenance.domain.repositories` is unused here and intentionally so.

        `related_type = 'OTHER'` (not `'EXPENSE'`) is the canonical value: D4 creates the
        approval with `related_type=OTHER, related_id=expense.id`, and `OwnerApprovalRelatedType`
        only declares `INCIDENT / MAINTENANCE_COST / OTHER`. A literal `'EXPENSE'` would
        return `None` for every expense (silent functional break, fix-rounds of section 3).

        `tenant_id` is mandatory per regla 1; the SQL layer scopes by it.
        """
        from app.maintenance.domain.enums import OwnerApprovalRelatedType
        from app.maintenance.infrastructure.models import OwnerApprovalModel

        result = await self._session.execute(
            select(OwnerApprovalModel.id).where(
                OwnerApprovalModel.tenant_id == tenant_id,
                OwnerApprovalModel.related_type == OwnerApprovalRelatedType.OTHER.value,
                OwnerApprovalModel.related_id == expense_id,
                OwnerApprovalModel.status == "PENDING",
            )
        )
        row = result.first()
        return row[0] if row else None

    async def delete(self, tenant_id: uuid.UUID, expense: Expense) -> None:
        """D6.2 — refuse to delete a consolidated expense.

        **Atomic guard**: the `WHERE` clause carries `statement_id IS NULL`, so even if a
        concurrent transaction (the generator, another operator) consolidates the row
        between this caller's `get` and the `DELETE`, the row is no-op'd at the database
        rather than deleted out from under the statement. The pre-check above is the
        programmer-error second line of defence, but the SQL is what closes the
        cross-transaction race QA flagged.
        """
        if expense.statement_id is not None:
            raise ExpenseAlreadyConsolidatedError(
                "Cannot delete an expense that is part of an OwnerStatement",
                field="statement_id",
            )
        result = await self._session.execute(
            sqla_delete(ExpenseModel).where(
                ExpenseModel.tenant_id == tenant_id,
                ExpenseModel.id == expense.id,
                ExpenseModel.statement_id.is_(None),
            )
        )
        if not result.rowcount:
            # The row either vanished or became consolidated between the caller's
            # read and the DELETE. The use case surfaces `ExpenseNotFoundError` from
            # the next get, so we just no-op silently here — the row is in some
            # other tenant's view of the truth and we are not its author.
            return

    async def find_closed_period(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        date_: date,
    ) -> OwnerStatement | None:
        """D6.3 — the closed period covering `date_`, if any.

        Returns the `OwnerStatement` itself (not just its bounds) so the caller can
        name it in the error body. `None` when no statement covers the date.
        """
        result = await self._session.execute(
            select(OwnerStatementModel).where(
                OwnerStatementModel.tenant_id == tenant_id,
                OwnerStatementModel.property_id == property_id,
                OwnerStatementModel.period_start <= date_,
                OwnerStatementModel.period_end >= date_,
            )
        )
        model = result.scalar_one_or_none()
        return _owner_statement_to_domain(model) if model else None
