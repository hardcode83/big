"""Request/response DTOs for the ten owner-statements and expenses routes (design D9, D13).

Four rules this module enforces, the same four `pricing/api/schemas.py` enumerates:

* **No request schema carries `tenant_id`.** The effective tenant comes only from the
  verified token (R7.2).
* **Response fields are enumerated, never dumped from the entity.** `OwnerStatement` and
  `Expense` carry `tenant_id`; a `from_attributes` dump would publish it.
* **`page` and `per_page` have ceilings.** Same reason as pricing: a 20-digit page number
  overflows the SQL `OFFSET` and produces an unhandled driver error rather than a 422 in
  the PRD §23 envelope.
* **Schemas validate types and shapes, not business rules.** Field bounds (the description
  ≤ 500 chars of `expenses.description`, the `NUMERIC(10,2)` ceiling of `expenses.amount`,
  the closed-period check of D6.3) live in `application/use_cases.py` — the use case names
  the failing field, and a validator that only ran here would leave every later reader
  unprotected.

**`pending_owner_approval_id`** is the D13 field. It sits on `ExpenseResponse`, not on
`OwnerStatementResponse`: a consolidated statement cannot have a pending approval by
construction (D6.1 freezes the expenses that fed it), so the field would be `None` for
every statement. The asymmetry is deliberate, and the row that explains it is the panel
of §3 fix-rounds.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.statements.domain.entities import Expense, OwnerStatement
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus

MAX_PER_PAGE = 100
#: `page` ceiling: a 20-digit page number overflows int8 in PostgreSQL and produces an
#: unhandled driver error instead of the 422 the PRD §23 envelope promises. Same bound as
#: `pricing/api/schemas.py`.
MAX_PAGE = 100_000

#: `expenses.description` is `String(500)` (`backend/app/statements/infrastructure/models.py`).
#: The use case applies the bound; this constant exists only so the body ceiling matches the
#: schema ceiling — a 4 KB description is refused at parse time, not after the entity is built.
MAX_EXPENSE_DESCRIPTION = 500
#: `expenses.amount` is `NUMERIC(10,2)`, so the ceiling is 99 999 999.99.
MAX_EXPENSE_AMOUNT = Decimal(100000000)

#: `allow_inf_nan=False` on every `Decimal` field: Pydantic otherwise accepts the JSON
#: strings `"NaN"` and `"Infinity"` into a `Decimal`, and the entity refuses both. A price
#: that is not a number has no business reaching the application layer.
_Amount = Annotated[Decimal, Field(allow_inf_nan=False)]


# ---- OwnerStatement -----------------------------------------------------------------


class OwnerStatementResponse(BaseModel):
    """What an authorised caller may see about one statement.

    Every writable column of the statement plus its identity and timestamps. **No
    `tenant_id`** — it is the token's, and echoing it tells a caller nothing she did not
    already prove. **No `pending_owner_approval_id`** — D13's deliberate asymmetry: a
    statement is built from consolidated expenses, and a consolidated expense's approval is
    necessarily `APPROVED`, never `PENDING`.
    """

    id: uuid.UUID
    property_id: uuid.UUID
    period_start: date
    period_end: date
    status: OwnerStatementStatus
    notes: str | None
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
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, statement: OwnerStatement) -> OwnerStatementResponse:
        return cls(
            id=statement.id,
            property_id=statement.property_id,
            period_start=statement.period_start,
            period_end=statement.period_end,
            status=statement.status,
            notes=statement.notes,
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
            created_at=statement.created_at,
            updated_at=statement.updated_at,
        )


class OwnerStatementPageResponse(BaseModel):
    """R3.2 — the listing envelope: `items`, `total`, `page`, `per_page`.

    `total_pages` is **not** published — the client computes it from `total` and `per_page`
    (the same convention `pricing-web` R3.4 set and `/sdd:auto` consumes).
    """

    items: list[OwnerStatementResponse]
    total: int
    page: int
    per_page: int

    @classmethod
    def from_domain(
        cls,
        statements: Sequence[OwnerStatement],
        *,
        total: int,
        page: int,
        per_page: int,
    ) -> OwnerStatementPageResponse:
        return cls(
            items=[OwnerStatementResponse.from_domain(statement) for statement in statements],
            total=total,
            page=page,
            per_page=per_page,
        )


class GenerateOwnerStatementRequest(BaseModel):
    """`POST /api/v1/owner-statements/generate` (R2.1, R2.2).

    `property_id` omitted sweeps the tenant's whole `ACTIVE` portfolio; named, it scopes to
    that one property. A `property_id` that is unknown, another tenant's, or not `ACTIVE` is
    a `422` — it is a body field, not a path identifier (D9's fourth refinement).

    `period_end` is the period's last day (R2.5: a statement covers one calendar month);
    `Period.month_containing` in `application/generation.py` rebuilds the closed range
    from it, so a caller typing a mid-month day is `422`'d with the field named.
    """

    model_config = ConfigDict(extra="forbid")

    property_id: uuid.UUID | None = None
    period_end: date | None = None


class OwnerStatementGenerationReportResponse(BaseModel):
    """R2.6 / D9 — the three counters the manual generation reports.

    `currency_mismatch` is the list of `(property_id, period_start, period_end, mismatches)`
    entries the use case collects when D3 aborts one or more `(tenant, property, period)`
    slices for non-EUR rows. The shape matches what the use case builds; the router hands
    it through unchanged.
    """

    created: int
    skipped: int
    failed: int
    consolidated_count: int
    currency_mismatch: list[dict[str, Any]]


class OwnerStatementTransitionRequest(BaseModel):
    """`PATCH /api/v1/owner-statements/{id}` with `status` (R4.2, R4.3, R4.4).

    The state machine lives on the entity (`OwnerStatement._TRANSITIONS`); this schema
    only constrains the value to the enum. An illegal move is a `409` raised by the
    entity, not a `422` from a shape check (R4.4).
    """

    model_config = ConfigDict(extra="forbid")

    status: OwnerStatementStatus


class OwnerStatementNotesUpdateRequest(BaseModel):
    """`PATCH /api/v1/owner-statements/{id}` with `notes` (R4.1, R4.5, R4.6).

    Only `notes`, no other field of the statement is writable from the API (R4.1):
    the amounts and dates are produced by generation. The body accepts empty strings
    too — the use case refuses them with a `422`, and the router passes the field through.
    """

    model_config = ConfigDict(extra="forbid")

    notes: str


# ---- Expense ------------------------------------------------------------------------ -----------------------------------------------------------------


class ExpenseResponse(BaseModel):
    """One expense row plus the optional `pending_owner_approval_id` (D13).

    `pending_owner_approval_id` is set when an `OwnerApproval(OTHER, PENDING)` exists for
    this expense — the reconciliation job of D4 will materialise the owner's answer on
    the next sweep, and the field lets the UI say "waiting for the owner" without a
    second call. `None` otherwise: no approval, the answer was `APPROVED`/`REJECTED`, or
    the threshold was never crossed.
    """

    id: uuid.UUID
    property_id: uuid.UUID
    category: ExpenseCategory
    description: str
    amount: Decimal
    currency: str
    date: date
    receipt_storage_key: str | None
    incident_id: uuid.UUID | None
    statement_id: uuid.UUID | None
    approved_by: uuid.UUID | None
    pending_owner_approval_id: uuid.UUID | None
    created_at: datetime

    @classmethod
    def from_domain(
        cls, expense: Expense, *, pending_owner_approval_id: uuid.UUID | None = None
    ) -> ExpenseResponse:
        return cls(
            id=expense.id,
            property_id=expense.property_id,
            category=expense.category,
            description=expense.description,
            amount=expense.amount,
            currency=expense.currency,
            date=expense.date,
            receipt_storage_key=expense.receipt_storage_key,
            incident_id=expense.incident_id,
            statement_id=expense.statement_id,
            approved_by=expense.approved_by,
            pending_owner_approval_id=pending_owner_approval_id,
            created_at=expense.created_at,
        )


class ExpensePageResponse(BaseModel):
    """The listing envelope for `GET /api/v1/expenses` (R5.1).

    Same shape as `OwnerStatementPageResponse` — `items`, `total`, `page`, `per_page` —
    so the FE can render both with one paginator.
    """

    items: list[ExpenseResponse]
    total: int
    page: int
    per_page: int

    @classmethod
    def from_domain(
        cls,
        rows: Sequence[tuple[Expense, uuid.UUID | None]],
        *,
        total: int,
        page: int,
        per_page: int,
    ) -> ExpensePageResponse:
        return cls(
            items=[
                ExpenseResponse.from_domain(expense, pending_owner_approval_id=pending_id)
                for expense, pending_id in rows
            ],
            total=total,
            page=page,
            per_page=per_page,
        )


class ExpenseCreateRequest(BaseModel):
    """`POST /api/v1/expenses` (R5.1, R5.2, R5.6, R5.7).

    `currency` defaults to `"EUR"` (R5.2: when omitted, defaultea a EUR); the use case
    runs the `Date not in future` check (R5.2), the threshold check (R5.7), the
    description check (R5.6), and the closed-period check (D6.3). This schema only
    constrains types and shapes.
    """

    model_config = ConfigDict(extra="forbid")

    property_id: uuid.UUID
    category: ExpenseCategory
    description: Annotated[str, Field(max_length=MAX_EXPENSE_DESCRIPTION)]
    amount: _Amount
    date: date
    currency: str = "EUR"
    receipt_storage_key: str | None = None
    incident_id: uuid.UUID | None = None


class ExpenseUpdateRequest(BaseModel):
    """`PATCH /api/v1/expenses/{id}` (R5.3, R5.6, D6.2, D6.3).

    Every field optional, and the router forwards `model_dump(exclude_unset=True)` so
    absent and `null` mean different things — a PATCH that does not name `description`
    is a no-op on it, while a PATCH that explicitly sets it to a new string writes the
    new value (R5.3).

    `statement_id`, `property_id`, `approved_by`, `incident_id`, and `created_at` are
    deliberately **not** writable here (R5.3, D6.2): `statement_id` is set by the
    generation; `approved_by` is set by the reconciliation job; `property_id` would
    silently move an expense across portfolios; `incident_id` is set when an incident
    raises one. Sending them is a `422` from Pydantic's `extra="forbid"`.
    """

    model_config = ConfigDict(extra="forbid")

    category: ExpenseCategory | None = None
    description: Annotated[str | None, Field(max_length=MAX_EXPENSE_DESCRIPTION)] = None
    amount: _Amount | None = None
    currency: str | None = None
    # `Optional[date]` rather than `date | None`: the field name `date` shadows the
    # imported `datetime.date` symbol in Pydantic's annotation resolver (the class
    # namespace is searched for `date`, and the field descriptor resolves to `None`
    # before the import resolves to the class). `Optional[...]` does the name lookup
    # through the typing module, dodging the shadow.
    date: Optional[date] = None
    receipt_storage_key: str | None = None