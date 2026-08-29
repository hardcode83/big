"""The ten owner-statements and expenses routes (PRD §23, design D9, D13).

Same shape as `app/pricing/api/recommendations_router.py`. The split between this module
and the export endpoints reflects D9: statements and expenses are two aggregates, and the
PDF/CSV exporters are two more doors. **Both routes are owned by the same router here**:
the lifecycle (`POST /generate`, `PATCH /notes|status`) and the read side
(`GET /{id}/export.csv|pdf`) of a statement live close enough that splitting them across
files would duplicate the prefix and the permission dependency.

**No anonymous door into this module.** Every route carries `READ_OWNER_STATEMENTS` or
`MANAGE_OWNER_STATEMENTS` (D8). The export endpoints — CSV, PDF — both read, so they
sit on `READ`, not `MANAGE`: an owner who only holds `READ` can still download their
own statement (R6.1, R6.3).

`POST /generate` runs **in the request and not as a queued task** (D9, R2.1): the report
it returns (`created`, `skipped`, `failed`, `consolidated_count`, `currency_mismatch`)
is only known when it finishes, and a `202` with a job id would be answering a
different question. The same use case backs the monthly cron at
`app/scheduler/tasks.py:_generate_owner_statements` (D11), with `actor=None`; this
endpoint passes the actor and so writes `OWNER_STATEMENT_GENERATED` to `AuditLog` —
the manual path is the **non-exempt** end of the D5/D12 rule-9 carve-out.
"""

# A tripwire worth knowing before you edit this file: every FastAPI route below passes
# a `description=` keyword (the same one `pricing/api/recommendations_router.py` has), and
# tests like `tests/maintenance/test_free_text_sink_contract.py` walk string literals
# looking for "incidents table name plus a write verb". A decorative cross-reference here
# that mentions the other module's table alongside a word like "updated" would pull this
# file into a census it has nothing to do with. Said in a comment rather than in a
# docstring on purpose: the matcher walks string literals, so a comment is invisible to it.
import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    get_client_ip,
    now_utc,
    require,
)
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.statements.api.dependencies import (
    get_create_expense_use_case,
    get_delete_expense_use_case,
    get_export_owner_statement_csv_use_case,
    get_export_owner_statement_pdf_use_case,
    get_expense_use_case,
    get_generate_owner_statement_use_case,
    get_list_expenses_use_case,
    get_list_owner_statements_use_case,
    get_owner_statement_use_case,
    get_transition_owner_statement_status_use_case,
    get_update_expense_use_case,
    get_update_owner_statement_notes_use_case,
)
from app.statements.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    ExpenseCreateRequest,
    ExpensePageResponse,
    ExpenseResponse,
    ExpenseUpdateRequest,
    GenerationReportResponse,
    GenerateOwnerStatementRequest,
    OwnerStatementNotesUpdateRequest,
    OwnerStatementPageResponse,
    OwnerStatementResponse,
    OwnerStatementTransitionRequest,
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
    StatementsActor,
    TransitionOwnerStatementStatusUseCase,
    UpdateExpenseUseCase,
    UpdateOwnerStatementNotesUseCase,
)
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus
from app.statements.domain.repositories import (
    ExpenseFilters,
    OwnerStatementFilters,
)

router = APIRouter(tags=["statements"], responses=AUTHENTICATED_RESPONSES)

ReadDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.READ_OWNER_STATEMENTS))
]
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_OWNER_STATEMENTS))
]


def _actor(authenticated: AuthenticatedRequest, ip: str) -> StatementsActor:
    return StatementsActor(user_id=authenticated.context.user_id, ip=ip or None)


# ---- /owner-statements ---------------------------------------------------------------


@router.get(
    "/owner-statements",
    response_model=OwnerStatementPageResponse,
    summary="List the tenant's owner statements",
    description=(
        "Paginated with `page`/`per_page` (PRD §23), filtered by `property_id`, by the "
        "`period_start_from`/`period_start_to` range, and by `status` — all combined with "
        "AND (R3.1). Only statements of the caller's tenant are ever returned (R7.2).\n\n"
        "Page size is fixed at 20 server-side (R3.1). `per_page` is accepted but the "
        "server uses its own constant; the response surfaces the value it actually used "
        "so the client can render the pagination correctly."
    ),
)
async def list_owner_statements(
    authenticated: ReadDep,
    use_case: Annotated[
        ListOwnerStatementsUseCase, Depends(get_list_owner_statements_use_case)
    ],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    period_start_from: date | None = None,
    period_start_to: date | None = None,
    status_filter: Annotated[
        OwnerStatementStatus | None, Query(alias="status")
    ] = None,
) -> OwnerStatementPageResponse:
    items, total = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        filters=OwnerStatementFilters(
            property_id=property_id,
            period_start_from=period_start_from,
            period_start_to=period_start_to,
            status=status_filter,
        ),
        page=page,
    )
    # R3.1: page size is fixed at 20 server-side; the envelope surfaces the constant,
    # never the caller-supplied `per_page`. A caller asking for 100 still gets 20 rows.
    return OwnerStatementPageResponse.from_domain(
        items, total=total, page=page, per_page=ListOwnerStatementsUseCase.LIST_PER_PAGE
    )


@router.post(
    "/owner-statements/generate",
    response_model=GenerationReportResponse,
    status_code=201,
    summary="Generate owner statements now",
    description=(
        "The manual door of the monthly cron: the same generator, over the same period, "
        "so a manager who wants to close the month early does not wait for 02:00 UTC on "
        "day 1 (R2.1).\n\n"
        "**Idempotent on the unique key** `(tenant_id, property_id, period_start, "
        "period_end)` (R2.3, D6.1): a second call with the same `property_id` and "
        "`period_end` returns the existing statement and counts it in `skipped`. The "
        "manual path is the **non-exempt** end of the rule-9 carve-out (D5/D12): it "
        "writes `OWNER_STATEMENT_GENERATED` to `AuditLog` with the caller as the actor, "
        "in addition to the `TimelineEvent` the cron path emits.\n\n"
        "**`currency_mismatch`** reports the `(property_id, period_start, period_end)` "
        "triples D3 aborted for non-EUR rows, with the offending `(row_id, currency, "
        "table)` list per triple (D3). No statement is partial — a single non-EUR row "
        "aborts the whole `(tenant, property, period)` (D3, R2).\n\n"
        "A `property_id` that is unknown, another tenant's, or not `ACTIVE` is a `422` "
        "(D9): it is a body field, not a path identifier. `period_end` must be the last "
        "day of a calendar month (R2.5)."
    ),
)
async def generate_owner_statement(
    payload: GenerateOwnerStatementRequest,
    authenticated: ManageDep,
    use_case: Annotated[
        GenerateOwnerStatementUseCase,
        Depends(get_generate_owner_statement_use_case),
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> GenerationReportResponse:
    outcome = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        now=now_utc(),
        property_id=payload.property_id,
        period_end=payload.period_end,
        actor=_actor(authenticated, client_ip),
    )
    return GenerationReportResponse(
        created=outcome.created,
        skipped=outcome.skipped,
        failed=outcome.failed,
        consolidated_count=outcome.consolidated_count,
        currency_mismatch=[
            {
                "property_id": str(prop_id),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "mismatches": [
                    {"row_id": row_id, "currency": currency, "table": table}
                    for row_id, currency, table in mismatches
                ],
            }
            for prop_id, period_start, period_end, mismatches in outcome.currency_mismatch
        ],
    )


@router.get(
    "/owner-statements/{statement_id}",
    response_model=OwnerStatementResponse,
    summary="Get one owner statement",
    description=(
        "Returns the statement's eleven monetary columns and its `status`/`notes`. Only "
        "statements of the caller's tenant are reachable — a `404` with the same body "
        "whether the id is unknown or belongs to another tenant (R3.4, R7.2).\n\n"
        "**The detail payload composes here, not in the API layer**: the PDF exporter "
        "(`ExportOwnerStatementPdfUseCase`) reads the same `GetOwnerStatementUseCase`, "
        "so the two surfaces cannot drift on what 'the detail' is (R3.5)."
    ),
)
async def get_owner_statement(
    statement_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[
        GetOwnerStatementUseCase, Depends(get_owner_statement_use_case)
    ],
) -> OwnerStatementResponse:
    payload = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        statement_id=statement_id,
    )
    return OwnerStatementResponse.from_domain(payload["statement"])


@router.patch(
    "/owner-statements/{statement_id}",
    response_model=OwnerStatementResponse,
    summary="Update an owner statement's notes or status",
    description=(
        "Two fields, never both at once — the router routes on which key is present in "
        "the body. `notes` is the rule-11 sink: its value never reaches "
        "`audit_logs.changes` (only `{\"changed\": true}` does), per `steering/security.md` "
        "rule 11 (R4.5). An empty or whitespace-only `notes`, or one carrying `U+0000`, "
        "is a `422` naming `notes` (R5.6).\n\n"
        "`status` accepts one of `READY` or `SENT` (R4.2, R4.4). The state machine "
        "lives on the entity; an illegal move is a `409` with the status untouched, "
        "and `SENT` is terminal — no move, legal or otherwise, accepts it as the origin "
        "(R4.4, D1).\n\n"
        "**No other column of the statement is writable from the API** (R4.1): the "
        "amounts and dates are produced by generation, and the eleven monetary columns are "
        "frozen at generation time (D6.1, D6.4). Sending them is a `422` from Pydantic's "
        "`extra=\"forbid\"`."
    ),
)
async def patch_owner_statement(
    statement_id: uuid.UUID,
    payload: OwnerStatementNotesUpdateRequest | OwnerStatementTransitionRequest,
    authenticated: ManageDep,
    notes_use_case: Annotated[
        UpdateOwnerStatementNotesUseCase,
        Depends(get_update_owner_statement_notes_use_case),
    ],
    transition_use_case: Annotated[
        TransitionOwnerStatementStatusUseCase,
        Depends(get_transition_owner_statement_status_use_case),
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> OwnerStatementResponse:
    # `payload` is a tagged union by content: `notes` is the notes-only body, `status`
    # is the transition body. The router does the routing because Pydantic's unions
    # would otherwise need a discriminator and the two endpoints share the same shape
    # of having *one* field.
    tenant_id = authenticated.context.tenant_id
    actor = _actor(authenticated, client_ip)
    if isinstance(payload, OwnerStatementTransitionRequest):
        statement = await transition_use_case.execute(
            tenant_id=tenant_id,
            actor=actor,
            now=now_utc(),
            statement_id=statement_id,
            target_status=payload.status,
        )
    else:
        statement = await notes_use_case.execute(
            tenant_id=tenant_id,
            actor=actor,
            now=now_utc(),
            statement_id=statement_id,
            notes=payload.notes,
        )
    return OwnerStatementResponse.from_domain(statement)


@router.get(
    "/owner-statements/{statement_id}/export.csv",
    summary="Download the statement's expenses as CSV",
    response_class=StreamingResponse,
    description=(
        "**No `AuditLog` is written for the download** (R6.7) — a read is a read. The "
        "audit trail of the statement is its transitions (R4) and the mutations of its "
        "expenses (R5).\n\n"
        "Header line is the canonical six columns (`date,category,description,amount,"
        "currency,receipt_storage_key`), one row per `Expense` of the statement. UTF-8 "
        "without BOM (R6.2), codepoints not escaped (R6.2)."
    ),
)
async def export_owner_statement_csv(
    statement_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[
        ExportOwnerStatementCsvUseCase,
        Depends(get_export_owner_statement_csv_use_case),
    ],
) -> StreamingResponse:
    statement, body = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        statement_id=statement_id,
    )
    # The bytes leave the use case already serialised; the router is a thin shell that
    # names the file and hands the body to a `StreamingResponse` (R6.1, R6.2, R6.3).
    period = statement.period_end.isoformat()
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="owner-statement-{period}.csv"'
        },
    )


@router.get(
    "/owner-statements/{statement_id}/export.pdf",
    summary="Download the statement as a PDF",
    response_class=StreamingResponse,
    description=(
        "Streamed directly in the response (R6.3): the PDF is **generated in the moment** "
        "and never persisted in `StorageAdapter` (R6.3, the gate of `/sdd:new` decision).\n\n"
        "Layout follows R6.4: tenant header, property block, period block, reservation "
        "lines (`gross_amount`/`ota_commission`/`net_amount`), expenses by category with "
        "subtotals, totals row, and a `notes` box. All amounts with two decimals, "
        "separator `,` (R6.5)."
    ),
)
async def export_owner_statement_pdf(
    statement_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[
        ExportOwnerStatementPdfUseCase,
        Depends(get_export_owner_statement_pdf_use_case),
    ],
) -> StreamingResponse:
    statement, body = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        statement_id=statement_id,
    )
    # Same shape as the CSV endpoint: the bytes leave the use case serialised, the
    # router names the file and streams the body (R6.3, R6.7 — no `AuditLog`).
    period = statement.period_end.isoformat()
    return StreamingResponse(
        iter([body]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="owner-statement-{period}.pdf"'
        },
    )


# ---- /expenses ------------------------------------------------------------------------


@router.get(
    "/expenses",
    response_model=ExpensePageResponse,
    summary="List the tenant's expenses",
    description=(
        "Paginated with `page`/`per_page` (PRD §23), filtered by `property_id`, by the "
        "`period_start_from`/`period_start_to` range on `expense.date`, and by `category` "
        "— all combined with AND (R5). Only expenses of the caller's tenant are ever "
        "returned (R7.2).\n\n"
        "Each item carries its optional `pending_owner_approval_id` (D13): the id of "
        "the `OwnerApproval(OTHER, PENDING)` raised for `amount > threshold`, or `None` "
        "if the threshold was never crossed or the reconciliation of D4 already "
        "materialised the answer."
    ),
)
async def list_expenses(
    authenticated: ReadDep,
    use_case: Annotated[
        ListExpensesUseCase, Depends(get_list_expenses_use_case)
    ],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    period_start_from: date | None = None,
    period_start_to: date | None = None,
    category_filter: Annotated[
        ExpenseCategory | None, Query(alias="category")
    ] = None,
) -> ExpensePageResponse:
    rows, total = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        filters=ExpenseFilters(
            property_id=property_id,
            period_start_from=period_start_from,
            period_start_to=period_start_to,
            category=category_filter,
        ),
        page=page,
    )
    # R5 listing parity: page size is fixed at 20 server-side; the envelope surfaces
    # the constant, never the caller-supplied `per_page`.
    return ExpensePageResponse.from_domain(
        rows, total=total, page=page, per_page=ListExpensesUseCase.LIST_PER_PAGE
    )


@router.post(
    "/expenses",
    response_model=ExpenseResponse,
    status_code=201,
    summary="Create an expense",
    description=(
        "Returns the row plus `pending_owner_approval_id` when `amount > "
        "TenantConfig.owner_approval_threshold_eur` (R5.7, D4): a new "
        "`OwnerApproval(OTHER)` is created in the same transaction, and the response "
        "field tells the UI that the row is gated on the owner's answer. The "
        "reconciliation of D4 will materialise the answer on its next sweep, and the "
        "field will then clear.\n\n"
        "A `date` that falls inside a period already covered by an `OwnerStatement` is "
        "a `422` (`NamedExpenseInClosedPeriodError`) — V1 does not regenerate, so a "
        "closed period cannot absorb new rows (D6.3)."
    ),
)
async def create_expense(
    payload: ExpenseCreateRequest,
    authenticated: ManageDep,
    use_case: Annotated[
        CreateExpenseUseCase, Depends(get_create_expense_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> ExpenseResponse:
    expense, pending_id = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
        property_id=payload.property_id,
        category=payload.category,
        description=payload.description,
        amount=payload.amount,
        date_=payload.date,
        currency=payload.currency,
        receipt_storage_key=payload.receipt_storage_key,
        incident_id=payload.incident_id,
    )
    return ExpenseResponse.from_domain(expense, pending_owner_approval_id=pending_id)


@router.get(
    "/expenses/{expense_id}",
    response_model=ExpenseResponse,
    summary="Get one expense",
    description=(
        "Returns the row plus its optional `pending_owner_approval_id` (D13). The id "
        "is the same value the listing returns for the row; an unknown id or one that "
        "belongs to another tenant is a `404` with the same body for both (R5.5)."
    ),
)
async def get_expense(
    expense_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetExpenseUseCase, Depends(get_expense_use_case)],
) -> ExpenseResponse:
    expense, pending_id = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        expense_id=expense_id,
    )
    return ExpenseResponse.from_domain(expense, pending_owner_approval_id=pending_id)


@router.patch(
    "/expenses/{expense_id}",
    response_model=ExpenseResponse,
    summary="Update an expense",
    description=(
        "Every field optional; the use case receives `model_dump(exclude_unset=True)` "
        "and applies only what the caller supplied (R5.3). Absent and `null` mean "
        "different things — sending no `description` is a no-op on it, sending "
        "`description: \"new\"` writes the new value.\n\n"
        "**Consolidated fields are immutable** (D6.2, R5.3): once `statement_id IS NOT "
        "NULL`, `amount`, `currency`, `category`, `date`, `property_id`, `statement_id`, "
        "and `approved_by` are read-only. The repository raises `ExpenseAlreadyConsolidatedError` "
        "for the offending field, mapped to `409 CONFLICT` here. `description` and "
        "`receipt_storage_key` remain editable.\n\n"
        "`statement_id`, `property_id`, `approved_by`, `incident_id`, and `created_at` "
        "are **not** in the body schema: sending them is a `422` from Pydantic's "
        "`extra=\"forbid\"`."
    ),
)
async def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseUpdateRequest,
    authenticated: ManageDep,
    use_case: Annotated[UpdateExpenseUseCase, Depends(get_update_expense_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> ExpenseResponse:
    updates = payload.model_dump(exclude_unset=True)
    expense, pending_id = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
        expense_id=expense_id,
        **updates,
    )
    return ExpenseResponse.from_domain(expense, pending_owner_approval_id=pending_id)


@router.delete(
    "/expenses/{expense_id}",
    status_code=204,
    summary="Delete an expense",
    description=(
        "Refuses with `409 ExpenseAlreadyConsolidatedError` when `statement_id IS NOT "
        "NULL` (R5.4, D6.2): a consolidated expense is part of the visible statement, "
        "and deleting it would falsify the owner's view of the period. The repository's "
        "`DELETE WHERE statement_id IS NULL` is the structural guard (QA-panel of §3); "
        "the use case's pre-check is the second line of defence."
    ),
)
async def delete_expense(
    expense_id: uuid.UUID,
    authenticated: ManageDep,
    use_case: Annotated[
        DeleteExpenseUseCase, Depends(get_delete_expense_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> None:
    await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor=_actor(authenticated, client_ip),
        now=now_utc(),
        expense_id=expense_id,
    )
    return None