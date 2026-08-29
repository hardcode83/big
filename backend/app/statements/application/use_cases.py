"""The application layer of `statements` (R1-R7, design D1, D4, D5, D6, D7, D10, D13).

Twelve use cases — eleven per `tasks.md` §4.1-4.10 and the reconciliation of §4.11 lives
in `application/reconciliation.py`. Two are the same code path called twice
(`GenerateOwnerStatementUseCase` is the only generator, shared by the monthly job and by
`POST /owner-statements/generate` — the precedent is `pricing.GeneratePriceRecommendationsUseCase`,
with the same one-generator-not-two reasoning).

**The generation writes no `AuditLog` from the clock** (D5/D12, the seventh exception of
rule 9 of `steering/security.md`): the scheduler fires the job, there is no person to
name and no `ip` to take from a request, and a two-flat tenant would write ~12 anonymous
rows a year into `audit_logs`. The trail for that path is the `TimelineEvent
OWNER_STATEMENT_GENERATED` each new statement emits. The manual `POST
/owner-statements/generate` carries its actor and writes the row, exactly the split the
fifth exception (`PRICE_RECOMMENDATIONS_GENERATED`) and the second (`PMS_CREDENTIAL_READ`)
already established. `_AuditWriter.record` accepts the carve-out through
`actor_optional=True` so the writer itself is the chokepoint and a future call without
an actor is impossible by construction.

`_AuditWriter` refuses `actor is None` by default, exactly like `pricing`'s and
`maintenance`'s, with one named exception: `OWNER_STATEMENT_GENERATED` from the monthly
job. The exception is enumerated rather than left to the writer's caller, so the wider
factory (`AuditLogFactory`) stays free to keep accepting actor-less rows for the other
modules that legitimately need them.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet, REDACT_ONLY_FIELDS
from app.core.unit_of_work import CallerOwnedUnitOfWork, UnitOfWork
from app.maintenance.domain.entities import OwnerApproval
from app.maintenance.domain.enums import OwnerApprovalRelatedType
from app.maintenance.domain.repositories import OwnerApprovalRepository
from app.properties.domain.enums import PropertyStatus
from app.properties.domain.repositories import PropertyRepository
from app.reservations.domain.repositories import ReservationRepository
from app.statements.domain.entities import Expense, OwnerStatement
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus
from app.statements.domain.exceptions import (
    ExpenseAlreadyConsolidatedError,
    ExpenseNotFoundError,
    MixedCurrencyPeriodError,
    NamedExpenseInClosedPeriodError,
    OwnerStatementInvalidTransitionError,
    OwnerStatementNotFoundError,
    OwnerStatementValidationError,
)
from app.statements.domain.repositories import (
    ExpenseFilters,
    ExpenseRepository,
    OwnerStatementFilters,
    OwnerStatementRepository,
)
from app.tenants.domain.repositories import TenantConfigRepository, TenantRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

from .generation import CurrencyFilter, MonetaryAggregator, Period

logger = logging.getLogger(__name__)


#: The actions of this module that an absent actor may write. Enumerated, like
#: `maintenance`'s `_ACTOR_OPTIONAL_ACTIONS` and `pricing`'s implicit rule — one place to
#: read the carve-out from rule 9 of `steering/security.md`.
_ACTOR_OPTIONAL_ACTIONS = frozenset({audit_actions.OWNER_STATEMENT_GENERATED})

#: Reuse the per-entity redact-only mapping rather than re-list `description` here, so
#: the two cannot drift. `REDACT_ONLY_FIELDS["EXPENSE"]` is what `_expense_change_set`
#: reads off, and `ChangeSet` enforces the name-level refusal itself.
_REDACT_EXPENSE_FIELDS = REDACT_ONLY_FIELDS[audit_actions.ENTITY_EXPENSE]

#: `notes` is the rule-11 sink on `OWNER_STATEMENT` (exception 3). Same shape as
#: the price-recommendation example the design cites: `ChangeSet.redacted()` is the
#: only reachable form, so the manager's text never reaches `audit_logs.changes`.
_REDACT_STATEMENT_FIELDS = REDACT_ONLY_FIELDS[audit_actions.ENTITY_OWNER_STATEMENT]


#: What the timeline says happened. Constants, like every other module's: the title is
#: stored on an append-only table, and `app/timeline/domain/rendering.py:211-218`
#: already carries the ES/EN pair each type is displayed with, so no i18n arrives with
#: this change.
_TIMELINE_TITLES: dict[TimelineEventType, str] = {
    TimelineEventType.OWNER_STATEMENT_GENERATED: "Owner statement generated",
}


#: The cap `expenses.description` shares with the rest of the bounded prose columns.
#: `incidents.description` uses 5000 (`String(5000)`), but `expenses` declares
#: `String(500)` on the column, and the shorter bound is what the schema actually holds.
MAX_EXPENSE_DESCRIPTION = 500
#: `expenses.amount` is `NUMERIC(10, 2)` — same ceiling the schema enforces.
MAX_EXPENSE_AMOUNT = Decimal("100000000")


@dataclass(frozen=True)
class StatementsActor:
    """Who is acting — and that is the one field `audit_logs` records (rule 9)."""

    user_id: uuid.UUID
    ip: str | None = None

    def __post_init__(self) -> None:
        if self.user_id is None:
            raise OwnerStatementValidationError(
                "a statements actor must name the user acting (rule 9 of steering/security.md)",
                field="user_id",
            )


class _AuditWriter:
    """Builds and appends an audit entry, so no use case constructs one by hand.

    Same shape as `pricing`'s and `maintenance`'s. The one difference is **what an
    actor-less write looks like**: the fifth exception (`PRICE_RECOMMENDATIONS_GENERATED`)
    and the second (`PMS_CREDENTIAL_READ`) keep their carve-outs in their own modules;
    pricing's writer refuses all five of its actions without an actor, and the job's
    exempt path simply does not call it. Here, the monthly job IS a caller — it has to
    write the `TimelineEvent` it owns — so the carve-out is granted through
    `actor_optional=True`. The flag is named, not a boolean: an accidental `True` reads
    differently than a missing argument.
    """

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        actor: StatementsActor | None,
        changes: ChangeSet,
        now: datetime,
        actor_optional: bool = False,
    ) -> None:
        if actor is None and not actor_optional:
            raise OwnerStatementValidationError(
                f"{action} must name the user who performed it; only "
                f"{sorted(_ACTOR_OPTIONAL_ACTIONS)} may be written without an actor.",
                field="actor",
            )
        if actor is None and action not in _ACTOR_OPTIONAL_ACTIONS:
            raise OwnerStatementValidationError(
                f"actor_optional=True is only honoured for "
                f"{sorted(_ACTOR_OPTIONAL_ACTIONS)}; {action} must name a user.",
                field="actor",
            )
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor.user_id if actor is not None else None,
                actor_ip=actor.ip if actor is not None else None,
                changes=changes,
                now=now,
            ),
        )


# ---- diff helpers -----------------------------------------------------------------


def _statement_change_set(notes: str | None) -> ChangeSet:
    """The audited diff of an `OWNER_STATEMENT_NOTES_UPDATED` (R4.5).

    `notes` is the rule-11 sink (exception 3); its value never reaches
    `audit_logs.changes`. `REDACT_ONLY_FIELDS["OWNER_STATEMENT"] = {"notes"}` makes the
    refusal structural: `ChangeSet.diff("notes", ...)` raises `AuditContractError`,
    leaving `redacted("notes")` as the only reachable form.
    """
    if "notes" not in _REDACT_STATEMENT_FIELDS:
        # Defensive: a regression that moved `notes` off the redact-only list would
        # otherwise silently start storing the manager's prose in an append-only sink.
        raise OwnerStatementValidationError(
            "OWNER_STATEMENT.notes is no longer in REDACT_ONLY_FIELDS; refusing to "
            "diff it (rule 11 of steering/security.md).",
            field="notes",
        )
    return ChangeSet(audit_actions.ENTITY_OWNER_STATEMENT).redacted("notes")


def _statement_status_change_set(
    *, before: OwnerStatementStatus, after: OwnerStatementStatus
) -> ChangeSet:
    """The audited diff of an `OWNER_STATEMENT_STATUS_CHANGED`."""
    return ChangeSet(audit_actions.ENTITY_OWNER_STATEMENT).diff("status", before, after)


def _expense_change_set(
    *,
    expense: Expense,
    before: Expense,
) -> ChangeSet:
    """The audited diff of an `EXPENSE_UPDATED`, with `description` redacted.

    Every field in `AUDITABLE_FIELDS["EXPENSE"]` is iterated off the entity, never off
    the caller's mapping — same defence `_rule_change_set` in `pricing` gives. A field
    whose name is in `REDACT_ONLY_FIELDS["EXPENSE"]` (currently just `description`) goes
    through `redacted()` rather than `diff()`; that is the **only** reachable form,
    because `ChangeSet.diff` raises `AuditContractError` for redact-only fields.

    `description` is iterated explicitly: a description-only change would otherwise
    fall through the no-op guard in `UpdateExpenseUseCase.execute` (no scalar field
    moved, but a redact-only field did) and write an empty `ChangeSet` that the
    factory would serialise as `changes=null` — i.e. lose the very fact that the
    manager's prose changed. Iterating `description` here is what makes rule 11's
    `{"changed": true}` shape reach the trail.
    """
    changes = ChangeSet(audit_actions.ENTITY_EXPENSE)
    for field in (
        "category",
        "amount",
        "currency",
        "date",
        "description",
        "statement_id",
        "incident_id",
        "approved_by",
        "receipt_storage_key",
    ):
        if getattr(expense, field) != getattr(before, field):
            if field in _REDACT_EXPENSE_FIELDS:
                changes = changes.redacted(field)
            else:
                changes = changes.diff(
                    field,
                    getattr(before, field),
                    getattr(expense, field),
                )
    return changes


def _expense_creation_change_set(expense: Expense) -> ChangeSet:
    """The audited diff of an `EXPENSE_CREATED`.

    The eight allowlisted fields go through `diff()` with `old=None`. `description` is
    deliberately **absent**: `AUDITABLE_FIELDS["EXPENSE"]` does not name it, and
    `description` is on `REDACT_ONLY_FIELDS["EXPENSE"]` (rule 11 exception 3). It is
    never audited on creation either — the row exists, no value of the manager's
    prose has reached the column yet, but the structural guarantee holds regardless.
    """
    changes = ChangeSet(audit_actions.ENTITY_EXPENSE)
    for field in (
        "category",
        "amount",
        "currency",
        "date",
        "statement_id",
        "incident_id",
        "approved_by",
        "receipt_storage_key",
    ):
        changes = changes.diff(field, None, getattr(expense, field))
    return changes


# ---- the eleven use cases (plus the generator shared by clock + manual) ------------


class CreateExpenseUseCase:
    """`POST /api/v1/expenses` (R5.1, R5.2, R5.6, R5.7; design D4).

    The expense, its `OwnerApproval(OTHER)` when over the tenant threshold, and the
    audit row are one transaction — so there is no state in which an expense exists
    that nobody can attribute, and the approval is born already linked to the row
    it gates.

    **Threshold bypass via `OwnerApproval(OTHER)`** (D4): when `amount > threshold`,
    the same transaction creates the `Expense` with `approved_by=None` AND an
    `OwnerApproval(related_type=OTHER, related_id=expense.id, amount, reason)`. The
    reconciliation of D4 materialises the owner's answer later. The
    `pending_owner_approval_id` field on the response is what tells the client that
    this expense is gated.

    **Tenant resolution** is from the session's `tenant_id` (R7.2), the property from
    `properties.get(tenant_id, property_id)` — a 422 if the property is unknown, an
    inactive one, or another tenant's. The `property_id` column of `expenses` is a
    plain FK to `properties.id` with no tenant qualification, so the database would
    accept a row pointing at another tenant's flat. Resolving here closes that.
    """

    def __init__(
        self,
        *,
        expenses: ExpenseRepository,
        properties: PropertyRepository,
        approvals: OwnerApprovalRepository,
        configs: TenantConfigRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._expenses = expenses
        self._properties = properties
        self._approvals = approvals
        self._configs = configs
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor: StatementsActor,
        now: datetime,
        property_id: uuid.UUID,
        category: ExpenseCategory,
        description: str,
        amount: Decimal,
        date_: date,
        currency: str = "EUR",
        receipt_storage_key: str | None = None,
        incident_id: uuid.UUID | None = None,
    ) -> tuple[Expense, uuid.UUID | None]:
        if amount > MAX_EXPENSE_AMOUNT:
            raise OwnerStatementValidationError(
                f"exceeds the {MAX_EXPENSE_AMOUNT} ceiling of NUMERIC(10,2)",
                field="amount",
            )
        if date_ > now.date():
            raise OwnerStatementValidationError(
                "date cannot be in the future (R5.2 — the period has not run yet)",
                field="date",
            )
        if not isinstance(description, str) or not description.strip():
            raise OwnerStatementValidationError("description must not be empty", field="description")
        if "\x00" in description:
            raise OwnerStatementValidationError("must not contain U+0000 (rule 11 of steering/security.md)", field="description")
        if len(description) > MAX_EXPENSE_DESCRIPTION:
            raise OwnerStatementValidationError(
                f"exceeds the {MAX_EXPENSE_DESCRIPTION} character bound",
                field="description",
            )

        property = await self._properties.get(tenant_id, property_id)
        if property is None:
            raise OwnerStatementValidationError("does not name a property of this tenant", field="property_id")
        if property.status is not PropertyStatus.ACTIVE:
            # Mirrors `pricing`'s `_candidates` refusal: a property that is not ACTIVE
            # does not earn statements, and a `422` naming the cause is more actionable
            # than a `skipped` counter.
            raise OwnerStatementValidationError(
                "names a property that is not ACTIVE; only the active portfolio is billable",
                field="property_id",
            )

        # D6.3 — `date` cannot fall inside a period that already has a `OwnerStatement`.
        closed = await self._expenses.find_closed_period(
            tenant_id=tenant_id,
            property_id=property_id,
            date_=date_,
        )
        if closed is not None:
            raise NamedExpenseInClosedPeriodError(
                f"An OwnerStatement already exists for property {property_id} covering "
                f"{closed.period_start.isoformat()}–{closed.period_end.isoformat()}; "
                "V1 does not allow new expenses in a closed period."
            )

        expense = Expense(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=property_id,
            category=category,
            description=description,
            amount=amount,
            currency=currency,
            date=date_,
            created_at=now,
            receipt_storage_key=receipt_storage_key,
            incident_id=incident_id,
        )
        await self._expenses.add(expense)

        pending_approval_id: uuid.UUID | None = None
        config = await self._configs.get_or_create(tenant_id, now)
        if amount > config.owner_approval_threshold_eur:
            # R5.7 / D4 — the expense crosses the tenant threshold; create the approval
            # in the same transaction. `OTHER` is the canonical `related_type` (the
            # enum declares `INCIDENT / MAINTENANCE_COST / OTHER`, not `EXPENSE`).
            approval = OwnerApproval(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=property_id,
                related_type=OwnerApprovalRelatedType.OTHER,
                related_id=expense.id,
                amount=amount,
                reason=f"Expense #{expense.id} above the tenant threshold.",
                requested_at=now,
            )
            await self._approvals.add(tenant_id, approval)
            pending_approval_id = approval.id

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.EXPENSE_CREATED,
            entity_type=audit_actions.ENTITY_EXPENSE,
            entity_id=expense.id,
            actor=actor,
            changes=_expense_creation_change_set(expense),
            now=now,
        )

        await self._uow.commit()
        return expense, pending_approval_id


class UpdateExpenseUseCase:
    """`PATCH /api/v1/expenses/{id}` (R5.3, R5.6, R5.7; design D6.2, D6.3).

    The immutability of D6.2 lives in the SQL adapter (the load-then-compare + row-lock
    of `SqlAlchemyExpenseRepository.save`); the use case's job is to **not** raise
    itself when the field would be refused, so the SQL guard does the talking. The
    exception that surfaces is `ExpenseAlreadyConsolidatedError` with the offending
    `field` — what the API maps to a 409.
    """

    def __init__(
        self,
        *,
        expenses: ExpenseRepository,
        approvals: OwnerApprovalRepository,
        configs: TenantConfigRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._expenses = expenses
        self._approvals = approvals
        self._configs = configs
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor: StatementsActor,
        now: datetime,
        expense_id: uuid.UUID,
        category: ExpenseCategory | None = None,
        description: str | None = None,
        amount: Decimal | None = None,
        currency: str | None = None,
        date_: date | None = None,
        receipt_storage_key: str | None = None,
    ) -> tuple[Expense, uuid.UUID | None]:
        before = await self._expenses.get(tenant_id, expense_id)
        if before is None:
            raise ExpenseNotFoundError()

        # R5.7 — read the tenant threshold before mutating, so the same-row
        # approval below has the value at hand.
        config = await self._configs.get_or_create(tenant_id, now)

        # Build the future entity from the current one, applying only the changes the
        # caller supplied. The repository's `save` is what enforces D6.2 immutability;
        # we mirror the entity's allowed-mutation set here so the SQL guard is the
        # single source of truth for the field rule.
        future = Expense(
            id=before.id,
            tenant_id=before.tenant_id,
            property_id=before.property_id,
            category=category if category is not None else before.category,
            description=description if description is not None else before.description,
            amount=amount if amount is not None else before.amount,
            currency=currency if currency is not None else before.currency,
            date=date_ if date_ is not None else before.date,
            created_at=before.created_at,
            receipt_storage_key=(
                receipt_storage_key
                if receipt_storage_key is not None
                else before.receipt_storage_key
            ),
            statement_id=before.statement_id,
            incident_id=before.incident_id,
            approved_by=before.approved_by,
        )

        # Validate description up front (R5.6 / rule 11), independent of the SQL guard.
        if "\x00" in future.description:
            raise OwnerStatementValidationError("must not contain U+0000 (rule 11 of steering/security.md)", field="description")
        if not future.description.strip():
            raise OwnerStatementValidationError("must not be empty", field="description")
        if len(future.description) > MAX_EXPENSE_DESCRIPTION:
            raise OwnerStatementValidationError(
                f"exceeds the {MAX_EXPENSE_DESCRIPTION} character bound",
                field="description",
            )
        if future.amount > MAX_EXPENSE_AMOUNT:
            raise OwnerStatementValidationError(
                f"exceeds the {MAX_EXPENSE_AMOUNT} ceiling of NUMERIC(10,2)",
                field="amount",
            )

        # R5.7 — a PATCH that pushes `amount` over the tenant threshold must create
        # an `OwnerApproval(OTHER)` to gate the row, exactly like `CreateExpenseUseCase`
        # does for a fresh row. The reconciliation job of D4 then materialises the
        # owner's answer. Without this, an `UPDATE expenses SET amount = :new` could
        # silently move a row out of the gate.
        if (
            amount is not None
            and amount != before.amount
            and amount > config.owner_approval_threshold_eur
            and before.approved_by is None
            and before.statement_id is None
        ):
            approval = OwnerApproval(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=before.property_id,
                related_type=OwnerApprovalRelatedType.OTHER,
                related_id=before.id,
                amount=amount,
                reason=f"Expense #{before.id} above the tenant threshold.",
                requested_at=now,
            )
            await self._approvals.add(tenant_id, approval)

        # D6.3 — `date` cannot move into a period that already has a statement.
        if date_ is not None and date_ != before.date:
            closed = await self._expenses.find_closed_period(
                tenant_id=tenant_id,
                property_id=before.property_id,
                date_=future.date,
            )
            if closed is not None:
                raise NamedExpenseInClosedPeriodError(
                    f"An OwnerStatement already exists for property {before.property_id} "
                    f"covering {closed.period_start.isoformat()}–{closed.period_end.isoformat()}; "
                    "V1 does not allow moving an expense into a closed period."
                )

        # The adapter enforces D6.2 immutability: it will raise
        # `ExpenseAlreadyConsolidatedError(field)` if the future touches a frozen field
        # on a consolidated row. Let it.
        await self._expenses.save(future)

        # Audit only the fields that actually changed (D7's principle: an effective no-op
        # does not earn an audit row). The check walks every field of the audit allowlist,
        # including `description` so a redact-only update still counts.
        if (
            future.category == before.category
            and future.amount == before.amount
            and future.currency == before.currency
            and future.date == before.date
            and future.description == before.description
            and future.statement_id == before.statement_id
            and future.incident_id == before.incident_id
            and future.approved_by == before.approved_by
            and future.receipt_storage_key == before.receipt_storage_key
        ):
            pending_id = await self._expenses.find_pending_owner_approval_for(
                tenant_id, future.id
            )
            return future, pending_id

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.EXPENSE_UPDATED,
            entity_type=audit_actions.ENTITY_EXPENSE,
            entity_id=future.id,
            actor=actor,
            changes=_expense_change_set(expense=future, before=before),
            now=now,
        )
        await self._uow.commit()
        pending_id = await self._expenses.find_pending_owner_approval_for(
            tenant_id, future.id
        )
        return future, pending_id


class DeleteExpenseUseCase:
    """`DELETE /api/v1/expenses/{id}` (R5.4, design D6.2)."""

    def __init__(
        self,
        *,
        expenses: ExpenseRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._expenses = expenses
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor: StatementsActor,
        now: datetime,
        expense_id: uuid.UUID,
    ) -> None:
        expense = await self._expenses.get(tenant_id, expense_id)
        if expense is None:
            raise ExpenseNotFoundError()
        if expense.statement_id is not None:
            # R5.4 / D6.2 — the expense is part of a published statement; deleting
            # silently would falsify the owner's view of the period.
            raise ExpenseAlreadyConsolidatedError(
                "Cannot delete an expense that is part of an OwnerStatement",
                field="statement_id",
            )
        await self._expenses.delete(tenant_id, expense)
        # The adapter also raises `ExpenseAlreadyConsolidatedError` when `statement_id`
        # is set — the second line of defence for any caller that bypassed the
        # pre-check above.
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.EXPENSE_DELETED,
            entity_type=audit_actions.ENTITY_EXPENSE,
            entity_id=expense.id,
            actor=actor,
            # The diff is empty: the row is gone, the column names are what an audit
            # reviewer needs to find it.
            changes=ChangeSet(audit_actions.ENTITY_EXPENSE),
            now=now,
        )
        await self._uow.commit()


class GetExpenseUseCase:
    """`GET /api/v1/expenses/{id}` (R5, D13).

    Returns the `Expense` together with the optional `pending_owner_approval_id`.
    The field is set when an `OwnerApproval(OTHER, status=PENDING)` references this
    expense; it is `None` otherwise (no approval, the answer was APPROVED/REJECTED,
    or the threshold was never crossed). The API layer turns this into the
    `pending_owner_approval_id` field on the response (task 6.1).
    """

    def __init__(self, expenses: ExpenseRepository) -> None:
        self._expenses = expenses

    async def execute(
        self, *, tenant_id: uuid.UUID, expense_id: uuid.UUID
    ) -> tuple[Expense, uuid.UUID | None]:
        expense = await self._expenses.get(tenant_id, expense_id)
        if expense is None:
            raise ExpenseNotFoundError()
        pending_id = await self._expenses.find_pending_owner_approval_for(
            tenant_id, expense.id
        )
        return expense, pending_id


class ListExpensesUseCase:
    """`GET /api/v1/expenses` (R5, D13).

    Filters: `property_id`, `period_start_from`, `period_start_to` (mapped to `Expense.date`
    — the closest the schema has to a period column), `category`. Page size fixed at 20
    by R5.1; the same envelope as `pricing-web` and the rest: `{items, total, page,
    per_page}`.

    `per_page` is forced server-side to the constant 20: a caller-supplied value is
    ignored. R3.1 says the same for the statement listing; the two are kept in lock
    step so a single `MAX_PER_PAGE` constant can govern both later if needed.
    """

    LIST_PER_PAGE = 20

    def __init__(self, expenses: ExpenseRepository) -> None:
        self._expenses = expenses

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: ExpenseFilters,
        page: int,
        per_page: int | None = None,
    ) -> tuple[Sequence[tuple[Expense, uuid.UUID | None]], int]:
        # R5.1: server-side fixed page size. A `per_page` of any other value is
        # ignored — the listing is meant for an operator who wants every row, and a
        # caller asking for 200 would not be denied by accident. Documented in the
        # response via `per_page` so the client can see what it got.
        items, total = await self._expenses.list_paginated(
            tenant_id,
            filters,
            page=page,
            per_page=self.LIST_PER_PAGE,
        )
        # D13 — fetch the optional pending-approval id per row, scoped by tenant.
        # The lookup is one indexed query per row; the typical listing is empty
        # after the reconciliation of D4 has done its first sweep.
        decorated: list[tuple[Expense, uuid.UUID | None]] = []
        for expense in items:
            pending_id = await self._expenses.find_pending_owner_approval_for(
                tenant_id, expense.id
            )
            decorated.append((expense, pending_id))
        return decorated, total


class GetOwnerStatementUseCase:
    """`GET /api/v1/owner-statements/{id}` (R3.3, R3.4).

    Returns the statement, the expenses it absorbed, and the reservations whose
    stay overlapped the period — the same payload the PDF exporter of §4.10 builds.
    Composing here means the API layer (task 6.1) and the PDF exporter share one
    read path; without it, the two would drift on what "the detail" actually
    contains.
    """

    def __init__(
        self,
        *,
        statements: OwnerStatementRepository,
        expenses: ExpenseRepository,
        reservations: ReservationRepository,
    ) -> None:
        self._statements = statements
        self._expenses = expenses
        self._reservations = reservations

    async def execute(
        self, *, tenant_id: uuid.UUID, statement_id: uuid.UUID
    ) -> dict:
        statement = await self._statements.get(tenant_id, statement_id)
        if statement is None:
            raise OwnerStatementNotFoundError()
        all_in_period = await self._expenses.list_for_period(
            tenant_id=tenant_id,
            property_id=statement.property_id,
            period_start=statement.period_start,
            period_end=statement.period_end,
        )
        expenses = [
            row for row in all_in_period if row.statement_id == statement.id
        ]
        reservations = await self._reservations.list_for_properties(
            tenant_id=tenant_id,
            property_ids=[statement.property_id],
            date_from=statement.period_start,
            date_to=statement.period_end,
        )
        reservations_in_period = [
            reservation
            for reservation in reservations
            if reservation.currency == "EUR"
        ]
        return {
            "statement": statement,
            "expenses": expenses,
            "reservations": reservations_in_period,
        }


class ListOwnerStatementsUseCase:
    """`GET /api/v1/owner-statements` (R3.1, R3.2).

    Page size is fixed at 20 server-side (R3.1); the same `{items, total, page,
    per_page}` envelope as `pricing-web`. `property_id`, `period_start_from`,
    `period_start_to` and `status` combine with AND, exactly the form R3.1 fixes.

    `per_page` is forced server-side to the constant 20: a caller-supplied value is
    ignored. The schema's contract is the size the server returns, not the size
    the client asked for; the response surfaces the constant in `per_page` so the
    client can see what it got.
    """

    LIST_PER_PAGE = 20

    def __init__(self, statements: OwnerStatementRepository) -> None:
        self._statements = statements

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: OwnerStatementFilters,
        page: int,
        per_page: int | None = None,
    ) -> tuple[Sequence[OwnerStatement], int]:
        items, total = await self._statements.list_paginated(
            tenant_id,
            filters,
            page=page,
            per_page=self.LIST_PER_PAGE,
        )
        return items, total


#: What one tick of the generator produced. Same role as
#: `pricing.GenerationOutcome`: the API surfaces a subset of it (`created`, `skipped`,
#: `failed` per R2.6) and the rest lives in the report. The five counters are
#: independent so the API can render them as-is.
@dataclass
class GenerationOutcome:
    created: int = 0
    skipped: int = 0
    failed: int = 0
    consolidated_count: int = 0
    #: One tuple per `(property_id, period_start, period_end)` whose generation was
    #: aborted because of mixed-currency rows, plus the offending `(row_id, currency,
    #: table)` list. The API exposes the list as `currency_mismatch` so the manager
    #: can fix what the report names.
    currency_mismatch: list[
        tuple[uuid.UUID, date, date, list[tuple[str, str, str]]]
    ] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.currency_mismatch is None:
            self.currency_mismatch = []


class GenerateOwnerStatementUseCase:
    """The one generator, shared by the monthly job and by `POST /generate` (D6.1).

    One transaction per `(tenant, property, period)` (D6.1, R1.4). A failure in one
    does not discard the others. The transaction is the use case's own — the scheduler
    task hands it a real `UnitOfWork`, not `CallerOwnedUnitOfWork`, for the same reason
    `pricing`'s generator refuses the caller-owned boundary.

    **The path through `actor=None` writes no `AuditLog`** (D5/D12). The path through
    `actor=StatementsActor` writes `OWNER_STATEMENT_GENERATED` once per property
    consolidated (R7.5), in addition to the `TimelineEvent`. The flag is a parameter so
    the same use case serves both callers, and the writer is the chokepoint for the
    absence of an actor.
    """

    def __init__(
        self,
        *,
        statements: OwnerStatementRepository,
        expenses: ExpenseRepository,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        timeline: TimelineEventRepository,
        configs: TenantConfigRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        if isinstance(uow, CallerOwnedUnitOfWork):
            raise TypeError(
                "GenerateOwnerStatementUseCase needs a unit of work it can abandon: "
                "a use case whose correctness depends on abandoning its own failed unit "
                "cannot be composed under a caller-owned boundary (same defence "
                "GeneratePriceRecommendationsUseCase raises)."
            )
        self._statements = statements
        self._expenses = expenses
        self._properties = properties
        self._reservations = reservations
        self._timeline = timeline
        self._configs = configs
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        now: datetime,
        property_id: uuid.UUID | None = None,
        actor: StatementsActor | None = None,
        period_end: date | None = None,
    ) -> GenerationOutcome:
        """Generate statements for the tenant's active portfolio.

        `period_end` defaults to **the last day of the month before `now`'s month** when
        omitted — the manual endpoint accepts it as a parameter, the job always passes
        it explicitly to keep the two paths deterministic.
        """
        outcome = GenerationOutcome()
        if period_end is None:
            period = Period.previous_month(today=now.date())
        else:
            try:
                period = Period.month_containing(period_end)
            except ValueError as exc:
                # R2.5 / D6.1: a statement is one calendar month. A mid-month `period_end`
                # is a `422` naming the field — translate the domain-level ValueError to
                # the validator the API layer already maps.
                raise OwnerStatementValidationError(
                    str(exc),
                    field="period_end",
                ) from exc

        config = await self._configs.get_or_create(tenant_id, now)
        candidates = await self._candidates(tenant_id, property_id)

        for property in candidates:
            try:
                created = await self._generate_one(
                    tenant_id=tenant_id,
                    property_id=property.id,
                    period=period,
                    now=now,
                    actor=actor,
                    threshold_eur=config.owner_approval_threshold_eur,
                )
                if created is None:
                    outcome.skipped += 1
                else:
                    outcome.created += 1
                    outcome.consolidated_count += created.consolidated_count
            except MixedCurrencyPeriodError as exc:
                # Currency mismatch is a domain outcome that leaves the session
                # usable: the rollback below is defensive (resets any side-effects
                # of the failed property's iteration) rather than mandatory. The
                # mismatches list is part of the report.
                outcome.failed += 1
                outcome.currency_mismatch.append(
                    (property.id, period.period_start, period.period_end, exc.mismatches)
                )
                try:
                    await self._uow.rollback()
                except Exception:
                    logger.exception(
                        "statements.rollback_after_currency_mismatch_failed",
                        extra={"property_id": str(property.id)},
                    )
            except Exception:
                logger.exception(
                    "statements.generation_failed",
                    extra={
                        "tenant_id": str(tenant_id),
                        "property_id": str(property.id),
                        "period_start": period.period_start.isoformat(),
                        "period_end": period.period_end.isoformat(),
                    },
                )
                outcome.failed += 1
                # R1.4: a failed property must not discard the rest of the sweep.
                # Without the rollback, the session carries the partial state of the
                # failed property and the next iteration's INSERTs hit a broken
                # transaction. Same defence `GeneratePriceRecommendationsUseCase`
                # raises — see its `__init__` and the `abandon()` call below.
                try:
                    await self._uow.rollback()
                except Exception:
                    logger.exception(
                        "statements.rollback_after_generation_failed",
                        extra={"property_id": str(property.id)},
                    )
        return outcome

    async def _candidates(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID | None
    ) -> Sequence:
        if property_id is None:
            properties = await self._properties.list_by_status(
                tenant_id, PropertyStatus.ACTIVE
            )
            return properties
        property = await self._properties.get(tenant_id, property_id)
        if property is None:
            raise OwnerStatementValidationError("does not name a property of this tenant", field="property_id")
        if property.status is not PropertyStatus.ACTIVE:
            raise OwnerStatementValidationError(
                "names a property that is not ACTIVE; only the active portfolio is billable",
                field="property_id",
            )
        return [property]

    async def _generate_one(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        period: Period,
        now: datetime,
        actor: StatementsActor | None,
        threshold_eur: Decimal,
    ) -> "_GeneratedStatement | None":
        """One property's monthly statement, in one transaction (D6.1, D6.4)."""
        existing = await self._statements.find_by_unique_key(
            tenant_id=tenant_id,
            property_id=property_id,
            period_start=period.period_start,
            period_end=period.period_end,
        )
        if existing is not None:
            # R1.3 / R2.3 — preserve whatever the row carries. The job does not overwrite
            # manual entries.
            return None

        expenses = await self._expenses.list_for_period(
            tenant_id=tenant_id,
            property_id=property_id,
            period_start=period.period_start,
            period_end=period.period_end,
        )
        reservations = await self._reservations.list_for_properties(
            tenant_id=tenant_id,
            property_ids=[property_id],
            date_from=period.period_start,
            date_to=period.period_end,
        )

        # D3 — abort the whole period on mixed currency. No partial statement.
        mismatches = CurrencyFilter.check(
            reservations=reservations, expenses=expenses
        )
        if mismatches:
            raise MixedCurrencyPeriodError(
                f"Property {property_id} period {period.period_start.isoformat()}–"
                f"{period.period_end.isoformat()} contains non-EUR rows; V1 aborts the "
                "period rather than emit a partial statement.",
                mismatches=mismatches,
            )

        aggregator = MonetaryAggregator(threshold_eur=threshold_eur)
        breakdown = aggregator.aggregate(reservations=reservations, expenses=expenses)

        statement = OwnerStatement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=property_id,
            period_start=period.period_start,
            period_end=period.period_end,
            created_at=now,
            updated_at=now,
            gross_revenue=breakdown.gross_revenue,
            ota_commissions=breakdown.ota_commissions,
            net_revenue=breakdown.net_revenue,
            cleaning_costs=breakdown.cleaning_costs,
            laundry_costs=breakdown.laundry_costs,
            amenities_costs=breakdown.amenities_costs,
            maintenance_costs=breakdown.maintenance_costs,
            specialist_costs=breakdown.specialist_costs,
            platform_fee=breakdown.platform_fee,
            other_costs=breakdown.other_costs,
            net_owner_result=breakdown.net_owner_result,
            notes=None,
        )
        await self._statements.add(statement)

        # D6.1 — bulk-associate the expenses that fed this statement. `WHERE
        # statement_id IS NULL` is the idempotency guard; a second call would touch 0.
        expense_ids: list[uuid.UUID] = []
        for rows in breakdown.expenses_by_category.values():
            expense_ids.extend(row.id for row in rows)
        consolidated = await self._expenses.bulk_associate_to_statement(
            tenant_id=tenant_id,
            expense_ids=expense_ids,
            statement_id=statement.id,
        )

        # TimelineEvent — both paths emit it (D5/D12).
        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                TimelineEventData(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    property_id=property_id,
                    actor_type=(
                        TimelineActorType.USER
                        if actor is not None
                        else TimelineActorType.SCHEDULER
                    ),
                    actor_user_id=actor.user_id if actor is not None else None,
                    event_type=TimelineEventType.OWNER_STATEMENT_GENERATED,
                    title=_TIMELINE_TITLES[TimelineEventType.OWNER_STATEMENT_GENERATED],
                    created_at=now,
                    metadata={
                        "statement_id": str(statement.id),
                        "property_id": str(property_id),
                        "period_start": period.period_start.isoformat(),
                        "period_end": period.period_end.isoformat(),
                        "source": (
                            "manual" if actor is not None else "monthly_job"
                        ),
                    },
                )
            ),
        )

        # AuditLog — only on the manual path (D5/D12, the seventh exception).
        if actor is not None:
            await self._audit.record(
                tenant_id=tenant_id,
                action=audit_actions.OWNER_STATEMENT_GENERATED,
                entity_type=audit_actions.ENTITY_OWNER_STATEMENT,
                entity_id=statement.id,
                actor=actor,
                changes=ChangeSet(audit_actions.ENTITY_OWNER_STATEMENT),
                now=now,
            )

        await self._uow.commit()
        return _GeneratedStatement(
            statement=statement,
            consolidated_count=consolidated,
        )


@dataclass(frozen=True)
class _GeneratedStatement:
    statement: OwnerStatement
    consolidated_count: int


class UpdateOwnerStatementNotesUseCase:
    """`PATCH /api/v1/owner-statements/{id}` with `notes` (R4.1, R4.5, R4.6)."""

    def __init__(
        self,
        *,
        statements: OwnerStatementRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._statements = statements
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor: StatementsActor,
        now: datetime,
        statement_id: uuid.UUID,
        notes: str,
    ) -> OwnerStatement:
        statement = await self._statements.get(tenant_id, statement_id)
        if statement is None:
            raise OwnerStatementNotFoundError()
        previous_updated_at = statement.updated_at
        # The entity's `update_notes` raises `OwnerStatementValidationError` on bad
        # input — `notes` is empty, whitespace, has `U+0000`, or is not a string. We
        # revert `updated_at` from the snapshot so a rejection leaves no timestamp
        # artifact (R4.6).
        try:
            statement.update_notes(notes, now=now)
        except OwnerStatementValidationError:
            statement.updated_at = previous_updated_at
            raise
        await self._statements.save(statement)
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.OWNER_STATEMENT_NOTES_UPDATED,
            entity_type=audit_actions.ENTITY_OWNER_STATEMENT,
            entity_id=statement.id,
            actor=actor,
            changes=_statement_change_set(notes),
            now=now,
        )
        await self._uow.commit()
        return statement


class TransitionOwnerStatementStatusUseCase:
    """`PATCH /api/v1/owner-statements/{id}` with `status` (R4.2, R4.3, R4.4).

    The state machine lives on `OwnerStatement._TRANSITIONS`; this use case is the
    only writer of `status` after creation, and it delegates the legality check to the
    entity. A move from `SENT` raises `OwnerStatementInvalidTransitionError` and the
    audit row is never written (R4.4).
    """

    def __init__(
        self,
        *,
        statements: OwnerStatementRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._statements = statements
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor: StatementsActor,
        now: datetime,
        statement_id: uuid.UUID,
        target_status: OwnerStatementStatus,
    ) -> OwnerStatement:
        statement = await self._statements.get(tenant_id, statement_id)
        if statement is None:
            raise OwnerStatementNotFoundError()
        previous = statement.status
        try:
            if target_status is OwnerStatementStatus.READY:
                statement.mark_ready(now=now)
            elif target_status is OwnerStatementStatus.SENT:
                statement.mark_sent(now=now)
            else:
                raise OwnerStatementValidationError(
                    f"target status {target_status} is not a legal move target",
                    field="status",
                )
        except OwnerStatementInvalidTransitionError:
            # Re-raise — the entity has refused the move before any field touched.
            raise
        await self._statements.save(statement)
        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.OWNER_STATEMENT_STATUS_CHANGED,
            entity_type=audit_actions.ENTITY_OWNER_STATEMENT,
            entity_id=statement.id,
            actor=actor,
            changes=_statement_status_change_set(before=previous, after=statement.status),
            now=now,
        )
        await self._uow.commit()
        return statement


class ExportOwnerStatementCsvUseCase:
    """`GET /api/v1/owner-statements/{id}/export.csv` (R6.1, R6.2).

    Returns the bytes of the CSV: header line plus one row per `Expense` of the
    statement, UTF-8 without BOM, no translation. The serialisation lives in
    `infrastructure/csv_export.py` (task 7.3); the use case takes the exporter
    through its constructor so the router does not import the infrastructure layer
    (`sdd/steering/backend-architecture.md`).

    The bytes go straight to a `StreamingResponse`; nothing is persisted (R6.3).
    """

    HEADER = ("date", "category", "description", "amount", "currency", "receipt_storage_key")

    def __init__(
        self,
        expenses: ExpenseRepository,
        statements: OwnerStatementRepository,
        csv_exporter,
    ) -> None:
        self._expenses = expenses
        self._statements = statements
        self._csv_exporter = csv_exporter

    async def execute(
        self, *, tenant_id: uuid.UUID, statement_id: uuid.UUID
    ) -> tuple[OwnerStatement, bytes]:
        statement = await self._statements.get(tenant_id, statement_id)
        if statement is None:
            raise OwnerStatementNotFoundError()
        # Reuse the period query to pull the expenses the statement absorbed. The
        # `ExpenseRepository.list_for_period` does not filter on `statement_id`, so
        # we narrow the answer client-side; the SQL stays the same shape it has for
        # the generator and the API stays one trip.
        all_in_period = await self._expenses.list_for_period(
            tenant_id=tenant_id,
            property_id=statement.property_id,
            period_start=statement.period_start,
            period_end=statement.period_end,
        )
        rows = [row for row in all_in_period if row.statement_id == statement.id]
        body = self._csv_exporter.render(header=self.HEADER, rows=rows)
        return statement, body


class ExportOwnerStatementPdfUseCase:
    """`GET /api/v1/owner-statements/{id}/export.pdf` (R6.3, R6.4, R6.5).

    Returns the bytes of the PDF rendered from the assembled detail. The render
    itself lives in `infrastructure/pdf.py` (task 7.2); the use case takes the
    generator through its constructor so the router does not import the
    infrastructure layer (`sdd/steering/backend-architecture.md`).

    Streamed directly in the response (R6.3): the PDF is generated in the moment
    and never persisted in `StorageAdapter`. No `AuditLog` is written (R6.7).
    """

    def __init__(
        self,
        *,
        statements: OwnerStatementRepository,
        expenses: ExpenseRepository,
        properties: PropertyRepository,
        tenants: TenantRepository,
        reservations: ReservationRepository,
        pdf_generator,
    ) -> None:
        self._statements = statements
        self._expenses = expenses
        self._properties = properties
        self._tenants = tenants
        self._reservations = reservations
        self._pdf_generator = pdf_generator

    async def execute(
        self, *, tenant_id: uuid.UUID, statement_id: uuid.UUID
    ) -> tuple[OwnerStatement, bytes]:
        statement = await self._statements.get(tenant_id, statement_id)
        if statement is None:
            raise OwnerStatementNotFoundError()
        property = await self._properties.get(tenant_id, statement.property_id)
        if property is None:
            raise OwnerStatementNotFoundError()
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise OwnerStatementNotFoundError()
        expenses = await self._expenses.list_for_period(
            tenant_id=tenant_id,
            property_id=statement.property_id,
            period_start=statement.period_start,
            period_end=statement.period_end,
        )
        expenses_in_statement = [row for row in expenses if row.statement_id == statement.id]
        reservations = await self._reservations.list_for_properties(
            tenant_id=tenant_id,
            property_ids=[statement.property_id],
            date_from=statement.period_start,
            date_to=statement.period_end,
        )
        reservations_in_period = [
            reservation
            for reservation in reservations
            if reservation.currency == "EUR"
        ]
        body = self._pdf_generator.render(
            statement=statement,
            property=property,
            tenant=tenant,
            reservations=reservations_in_period,
            expenses=expenses_in_statement,
        )
        return statement, body
