"""Wiring for the ten owner-statements and expenses endpoints (design D9, D13).

Same shape as `app/pricing/api/dependencies.py`. The repositories take the session from
`get_db_session` — the same session `get_authenticated_request` has already marked with
the tenant, so the listener of `app/core/db.py` scopes ORM reads as well. That is the
net; the explicit `tenant_id` every repository method takes is the mechanism (rule 1 of
`steering/security.md`).

**`SqlAlchemyUnitOfWork` and never `CallerOwnedUnitOfWork`**, and for the generator that
is load-bearing rather than conventional: D6.1 makes it abandon the failed property's
transaction so the sweep can carry on, and `GenerateOwnerStatementUseCase.__init__`
refuses a boundary whose `rollback()` is a no-op.

`_expense_write_kwargs` and `_statement_write_kwargs` exist for the reason pricing's
`_rule_write_kwargs` does: a use case that forgot its audit repository would silently
stop honouring rule 9 of `steering/security.md`, and the two rule writers plus the
decision writer all need the same five collaborators. The expenses writers also need
`approvals` and `configs` — D4 routes the threshold bypass through the existing
`OwnerApprovalRepository` (the maintenance module's port, not a new one), and D6.3 reads
the tenant's threshold configuration to enforce the closed-period rule.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.maintenance.infrastructure.repositories import SqlAlchemyOwnerApprovalRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.statements.application.reconciliation import (
    ReconcileOwnerApprovalsForExpensesUseCase,
)
from app.statements.application.use_cases import (
    CreateExpenseUseCase,
    DeleteExpenseUseCase,
    ExportOwnerStatementCsvUseCase,
    ExportOwnerStatementPdfUseCase,
    GenerateOwnerStatementUseCase,
    GetExpenseUseCase,
    GetOwnerStatementUseCase,
    ListExpensesUseCase,
    ListOwnerStatementsUseCase,
    TransitionOwnerStatementStatusUseCase,
    UpdateExpenseUseCase,
    UpdateOwnerStatementNotesUseCase,
)
from app.statements.infrastructure.repositories import (
    SqlAlchemyExpenseRepository,
    SqlAlchemyOwnerStatementRepository,
)
from app.tenants.infrastructure.repositories import (
    SqlAlchemyTenantConfigRepository,
    SqlAlchemyTenantRepository,
)
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _expense_create_kwargs(session: AsyncSession) -> dict:
    """The six collaborators `CreateExpenseUseCase` needs.

    `properties` is not optional decoration (R5.1, R7.2): D7 of pricing, repeated for
    expenses, makes the two of them resolve a `property_id` a human typed *inside* the
    acting tenant before it can reach the row, and a builder that omitted it would not
    construct.

    `approvals` is D4's `OwnerApprovalRepository` port — owned by `maintenance`, but the
    statements module is its caller because the threshold bypass lives here. The dependency
    crosses the module boundary through the port, not through the implementation: this
    file imports the SQLAlchemy adapter for wiring, and `use_cases.py` imports the port.
    """
    return {
        "expenses": SqlAlchemyExpenseRepository(session),
        "properties": SqlAlchemyPropertyRepository(session),
        "approvals": SqlAlchemyOwnerApprovalRepository(session),
        "configs": SqlAlchemyTenantConfigRepository(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": SqlAlchemyUnitOfWork(session),
    }


def _expense_update_kwargs(session: AsyncSession) -> dict:
    """The five collaborators `UpdateExpenseUseCase` needs.

    `UpdateExpenseUseCase` does not take `properties` — the row's `property_id` is fixed
    by creation and cannot move (R5.3), so the update path has nothing to resolve. The
    other five are the same as the create kwargs.
    """
    return {
        "expenses": SqlAlchemyExpenseRepository(session),
        "approvals": SqlAlchemyOwnerApprovalRepository(session),
        "configs": SqlAlchemyTenantConfigRepository(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": SqlAlchemyUnitOfWork(session),
    }


def _statement_write_kwargs(session: AsyncSession) -> dict:
    """The six collaborators every statement writer needs.

    `configs` is read for `owner_approval_threshold_eur` (D6.1, the per-period threshold
    the aggregator uses). The other five are the same shape as the pricing generator:
    repos + timeline + audit + uow.
    """
    return {
        "statements": SqlAlchemyOwnerStatementRepository(session),
        "expenses": SqlAlchemyExpenseRepository(session),
        "properties": SqlAlchemyPropertyRepository(session),
        "reservations": SqlAlchemyReservationRepository(session),
        "timeline": SqlAlchemyTimelineEventRepository(session),
        "configs": SqlAlchemyTenantConfigRepository(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": SqlAlchemyUnitOfWork(session),
    }


# ---- statements -----------------------------------------------------------------------


def get_list_owner_statements_use_case(
    session: SessionDep,
) -> ListOwnerStatementsUseCase:
    return ListOwnerStatementsUseCase(SqlAlchemyOwnerStatementRepository(session))


def get_owner_statement_use_case(
    session: SessionDep,
) -> GetOwnerStatementUseCase:
    return GetOwnerStatementUseCase(
        statements=SqlAlchemyOwnerStatementRepository(session),
        expenses=SqlAlchemyExpenseRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
    )


def get_generate_owner_statement_use_case(
    session: SessionDep,
) -> GenerateOwnerStatementUseCase:
    return GenerateOwnerStatementUseCase(**_statement_write_kwargs(session))


def get_update_owner_statement_notes_use_case(
    session: SessionDep,
) -> UpdateOwnerStatementNotesUseCase:
    return UpdateOwnerStatementNotesUseCase(
        statements=SqlAlchemyOwnerStatementRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_transition_owner_statement_status_use_case(
    session: SessionDep,
) -> TransitionOwnerStatementStatusUseCase:
    return TransitionOwnerStatementStatusUseCase(
        statements=SqlAlchemyOwnerStatementRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_export_owner_statement_csv_use_case(
    session: SessionDep,
) -> ExportOwnerStatementCsvUseCase:
    # The CSV exporter lives in `infrastructure/`; the dependency builder is the only
    # place `api/` is allowed to import it (`sdd/steering/backend-architecture.md`). The
    # use case takes the exporter through its constructor so the router never sees the
    # infrastructure layer. `app.statements.infrastructure.csv_export` does not yet
    # exist (`CsvStatementExporter` lands in task 7.3); the import is guarded so a
    # missing exporter surfaces at request time, not at startup.
    from app.statements.infrastructure.csv_export import CsvStatementExporter

    return ExportOwnerStatementCsvUseCase(
        expenses=SqlAlchemyExpenseRepository(session),
        statements=SqlAlchemyOwnerStatementRepository(session),
        csv_exporter=CsvStatementExporter,
    )


def get_export_owner_statement_pdf_use_case(
    session: SessionDep,
) -> ExportOwnerStatementPdfUseCase:
    # Same pattern as the CSV builder: the PDF generator is imported here (the only
    # `api/` place that may touch `infrastructure/`) and passed to the use case.
    # `PdfStatementGenerator` lands in task 7.2; import is guarded for the same reason.
    from app.statements.infrastructure.pdf import PdfStatementGenerator

    return ExportOwnerStatementPdfUseCase(
        statements=SqlAlchemyOwnerStatementRepository(session),
        expenses=SqlAlchemyExpenseRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        tenants=SqlAlchemyTenantRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        pdf_generator=PdfStatementGenerator,
    )


# ---- expenses -------------------------------------------------------------------------


def get_create_expense_use_case(session: SessionDep) -> CreateExpenseUseCase:
    return CreateExpenseUseCase(**_expense_create_kwargs(session))


def get_update_expense_use_case(session: SessionDep) -> UpdateExpenseUseCase:
    return UpdateExpenseUseCase(**_expense_update_kwargs(session))


def get_delete_expense_use_case(session: SessionDep) -> DeleteExpenseUseCase:
    return DeleteExpenseUseCase(
        expenses=SqlAlchemyExpenseRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_expense_use_case(session: SessionDep) -> GetExpenseUseCase:
    return GetExpenseUseCase(SqlAlchemyExpenseRepository(session))


def get_list_expenses_use_case(session: SessionDep) -> ListExpensesUseCase:
    return ListExpensesUseCase(SqlAlchemyExpenseRepository(session))


def get_reconcile_owner_approvals_for_expenses_use_case(
    session: SessionDep,
) -> ReconcileOwnerApprovalsForExpensesUseCase:
    """The scheduler's reconciliation entry point (D4).

    Exposed as a dependency so the router can also surface it as a manual flush — the
    scheduled job is the primary caller, but a developer hitting the endpoint is what
    makes D4's idempotency a property one can test from the API.
    """
    from app.statements.infrastructure.reconciliation import (
        SqlAlchemyReconciliationStore,
    )

    async def _commit() -> None:
        await session.commit()

    return ReconcileOwnerApprovalsForExpensesUseCase(
        store=SqlAlchemyReconciliationStore(session),
        commit=_commit,
    )