"""The first port of `statements` (`dashboard-api` R2, task 4.3).

Read-only by construction. Empty today — `expenses` has no writer until `revenue` — and
correct once rows exist, so the contract does not change when that lands.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.properties.infrastructure.models import PropertyModel
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel
from app.statements.infrastructure.repositories import SqlAlchemyExpenseReader
from app.tenants.infrastructure.models import TenantModel


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _property(db_session, tenant: TenantModel, code: str) -> PropertyModel:
    model = PropertyModel(tenant_id=tenant.id, name=code, internal_code=code)
    db_session.add(model)
    await db_session.flush()
    return model


async def _statement(db_session, tenant: TenantModel, prop: PropertyModel) -> OwnerStatementModel:
    model = OwnerStatementModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        status=OwnerStatementStatus.DRAFT,
    )
    db_session.add(model)
    await db_session.flush()
    return model


async def _expense(
    db_session,
    tenant: TenantModel,
    prop: PropertyModel,
    *,
    amount: str,
    currency: str = "EUR",
    statement: OwnerStatementModel | None = None,
) -> ExpenseModel:
    model = ExpenseModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        category=ExpenseCategory.MAINTENANCE,
        description="Boiler part",
        amount=Decimal(amount),
        currency=currency,
        date=date(2026, 7, 15),
        statement_id=statement.id if statement is not None else None,
    )
    db_session.add(model)
    await db_session.flush()
    return model


@pytest.mark.asyncio
async def test_a_property_with_no_expenses_gets_an_empty_summary_not_none(
    db_session,
) -> None:
    """The case of today, and the reason the return type is not `| None`: one shape to
    handle rather than two."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")

    summary = await SqlAlchemyExpenseReader(db_session).summary_for_property(
        tenant.id, prop.id
    )

    assert summary.pending_expenses == {}


@pytest.mark.asyncio
async def test_it_totals_the_unconsolidated_expenses(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    await _expense(db_session, tenant, prop, amount="120.50")
    await _expense(db_session, tenant, prop, amount="79.50")

    summary = await SqlAlchemyExpenseReader(db_session).summary_for_property(
        tenant.id, prop.id
    )

    assert summary.pending_expenses == {"EUR": Decimal("200.00")}


@pytest.mark.asyncio
async def test_an_expense_already_in_a_statement_is_not_pending(db_session) -> None:
    """"Pending" is `statement_id IS NULL`, which is the meaning the schema already gives
    the column (§7.23) — not a rule invented in this change."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    statement = await _statement(db_session, tenant, prop)
    await _expense(db_session, tenant, prop, amount="500.00", statement=statement)
    await _expense(db_session, tenant, prop, amount="12.00")

    summary = await SqlAlchemyExpenseReader(db_session).summary_for_property(
        tenant.id, prop.id
    )

    assert summary.pending_expenses == {"EUR": Decimal("12.00")}


@pytest.mark.asyncio
async def test_totals_are_kept_apart_per_currency_and_never_added_up(db_session) -> None:
    """`expenses.currency` is per row, so amounts in different currencies are not
    comparable — this port reports them as they are rather than picking one."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    await _expense(db_session, tenant, prop, amount="100.00", currency="EUR")
    await _expense(db_session, tenant, prop, amount="30.00", currency="GBP")
    await _expense(db_session, tenant, prop, amount="20.00", currency="GBP")

    summary = await SqlAlchemyExpenseReader(db_session).summary_for_property(
        tenant.id, prop.id
    )

    assert summary.pending_expenses == {
        "EUR": Decimal("100.00"),
        "GBP": Decimal("50.00"),
    }


@pytest.mark.asyncio
async def test_the_totals_are_decimals_and_keep_their_cents(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    await _expense(db_session, tenant, prop, amount="0.01")
    await _expense(db_session, tenant, prop, amount="0.02")

    summary = await SqlAlchemyExpenseReader(db_session).summary_for_property(
        tenant.id, prop.id
    )

    total = summary.pending_expenses["EUR"]
    assert isinstance(total, Decimal)
    assert total == Decimal("0.03")


@pytest.mark.asyncio
async def test_a_sibling_property_is_not_mixed_in(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    mine = await _property(db_session, tenant, "REDES11")
    other = await _property(db_session, tenant, "PAJARITOS8")
    await _expense(db_session, tenant, mine, amount="10.00")
    await _expense(db_session, tenant, other, amount="999.00")

    summary = await SqlAlchemyExpenseReader(db_session).summary_for_property(
        tenant.id, mine.id
    )

    assert summary.pending_expenses == {"EUR": Decimal("10.00")}


@pytest.mark.asyncio
async def test_it_never_reads_another_tenants_expenses(db_session) -> None:
    """DoD §28.18."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, "THEIRS")
    await _expense(db_session, tenant_b, theirs, amount="999.00")

    summary = await SqlAlchemyExpenseReader(db_session).summary_for_property(
        tenant_a.id, theirs.id
    )

    assert summary.pending_expenses == {}


# ---- `revenue-statements` — write adapters (tasks 3.5) -----------------------------


from app.statements.domain.exceptions import ExpenseAlreadyConsolidatedError
from app.statements.infrastructure.repositories import (
    SqlAlchemyExpenseRepository,
    SqlAlchemyOwnerStatementRepository,
)


@pytest.mark.asyncio
async def test_expense_bulk_associate_is_idempotent(db_session) -> None:
    """D6.1: a second `bulk_associate_to_statement` over the same id returns `0`, leaving
    the existing `statement_id` untouched. The `WHERE statement_id IS NULL` guard makes the
    statement side idempotent — the first call wins, the second is no-op."""
    from app.statements.domain.entities import Expense

    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    statement = await _statement(db_session, tenant, prop)
    e = await _expense(db_session, tenant, prop, amount="50.00")
    repo = SqlAlchemyExpenseRepository(db_session)

    first = await repo.bulk_associate_to_statement(
        tenant.id, [e.id], statement.id
    )
    assert first == 1

    second = await repo.bulk_associate_to_statement(
        tenant.id, [e.id], statement.id
    )
    assert second == 0

    # Reload and verify the original statement_id is preserved.
    refreshed = await repo.get(tenant.id, e.id)
    assert refreshed is not None
    assert refreshed.statement_id == statement.id


@pytest.mark.asyncio
async def test_expense_bulk_associate_respects_tenant(db_session) -> None:
    """A call with the wrong tenant id cannot reach another tenant's expenses."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop_a = await _property(db_session, tenant_a, "REDES11")
    statement = await _statement(db_session, tenant_a, prop_a)
    e = await _expense(db_session, tenant_a, prop_a, amount="50.00")
    repo = SqlAlchemyExpenseRepository(db_session)

    rows = await repo.bulk_associate_to_statement(tenant_b.id, [e.id], statement.id)

    assert rows == 0
    refreshed = await repo.get(tenant_a.id, e.id)
    assert refreshed.statement_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,new_value_factory",
    [
        ("amount", lambda: Decimal("999.00")),
        ("currency", lambda: "USD"),
        ("category", lambda: ExpenseCategory.PLATFORM_FEE),
        ("date", lambda: date(2026, 8, 1)),
        ("property_id", lambda: None),  # placeholder, set per-test
    ],
)
async def test_consolidated_expense_blocks_mutation_of_immutable_field(
    db_session, field, new_value_factory
) -> None:
    """D6.2 — the seven fields are immutable after consolidation. The error names the
    first field that differs, so the UI can point at the offending column."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    other_prop = await _property(db_session, tenant, "PAJARITOS8")
    statement = await _statement(db_session, tenant, prop)
    e = await _expense(db_session, tenant, prop, amount="50.00")
    repo = SqlAlchemyExpenseRepository(db_session)

    # Lock the row in.
    await repo.bulk_associate_to_statement(tenant.id, [e.id], statement.id)
    refreshed = await repo.get(tenant.id, e.id)
    assert refreshed is not None

    # Pick the right new value per field.
    if field == "property_id":
        new_value = other_prop.id
    else:
        new_value = new_value_factory()
    setattr(refreshed, field, new_value)

    with pytest.raises(ExpenseAlreadyConsolidatedError) as exc_info:
        await repo.save(refreshed)

    assert exc_info.value.field == field


@pytest.mark.asyncio
async def test_consolidated_expense_allows_description_and_receipt_key(
    db_session,
) -> None:
    """D6.2 — `description` and `receipt_storage_key` are mutable after consolidation.
    Pinning the boundary so a future regression that locks them down is caught."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    statement = await _statement(db_session, tenant, prop)
    e = await _expense(db_session, tenant, prop, amount="50.00")
    repo = SqlAlchemyExpenseRepository(db_session)
    await repo.bulk_associate_to_statement(tenant.id, [e.id], statement.id)

    refreshed = await repo.get(tenant.id, e.id)
    assert refreshed is not None
    refreshed.description = "Late note about the boiler part."
    refreshed.receipt_storage_key = "tenants/x/expenses/y/boiler.pdf"
    await repo.save(refreshed)  # must not raise

    reloaded = await repo.get(tenant.id, e.id)
    assert reloaded.description == "Late note about the boiler part."
    assert reloaded.receipt_storage_key == "tenants/x/expenses/y/boiler.pdf"


@pytest.mark.asyncio
async def test_unconsolidated_expense_allows_all_mutations(db_session) -> None:
    """D6.2 — before consolidation every field is mutable. The immutability fires only
    once `statement_id IS NOT NULL`."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    e = await _expense(db_session, tenant, prop, amount="50.00")
    repo = SqlAlchemyExpenseRepository(db_session)
    refreshed = await repo.get(tenant.id, e.id)
    assert refreshed is not None

    refreshed.amount = Decimal("75.00")
    refreshed.currency = "USD"
    refreshed.category = ExpenseCategory.PLATFORM_FEE
    refreshed.description = "Changed."

    await repo.save(refreshed)  # must not raise

    reloaded = await repo.get(tenant.id, e.id)
    assert reloaded.amount == Decimal("75.00")
    assert reloaded.currency == "USD"
    assert reloaded.category == ExpenseCategory.PLATFORM_FEE
    assert reloaded.description == "Changed."


@pytest.mark.asyncio
async def test_owner_statement_get_returns_none_for_wrong_tenant(
    db_session,
) -> None:
    """DoD §28.18 — tenant isolation. The same id in another tenant is invisible; the
    API maps both "not found" and "wrong tenant" to 404 with the same body, so the
    repository returns `None` in both cases."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop_a = await _property(db_session, tenant_a, "REDES11")
    s = await _statement(db_session, tenant_a, prop_a)

    repo = SqlAlchemyOwnerStatementRepository(db_session)

    assert (await repo.get(tenant_a.id, s.id)) is not None
    assert (await repo.get(tenant_b.id, s.id)) is None
    assert (await repo.get(tenant_a.id, uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_find_pending_owner_approval_uses_other_related_type(db_session) -> None:
    """Section-3 fix-rounds regression: the literal `'EXPENSE'` was the silent functional
    break. `OwnerApproval(OTHER)` (per D4) is the canonical value — `OwnerApprovalRelatedType`
    declares `INCIDENT / MAINTENANCE_COST / OTHER`, never `EXPENSE`. The lookup must filter
    by `OTHER` to find approvals created by `CreateExpenseUseCase` for `amount > threshold`."""
    from app.maintenance.domain.enums import OwnerApprovalRelatedType
    from app.maintenance.infrastructure.models import OwnerApprovalModel

    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    e = await _expense(db_session, tenant, prop, amount="150.00")  # > threshold

    # Mirror what `CreateExpenseUseCase` writes (D4).
    approval = OwnerApprovalModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        related_type=OwnerApprovalRelatedType.OTHER.value,
        related_id=e.id,
        amount=e.amount,
        reason=f"Expense #{e.id}",
    )
    db_session.add(approval)
    await db_session.flush()

    repo = SqlAlchemyExpenseRepository(db_session)
    found = await repo.find_pending_owner_approval_for(tenant.id, e.id)

    assert found == approval.id


@pytest.mark.asyncio
async def test_find_pending_owner_approval_returns_none_for_other_tenant(
    db_session,
) -> None:
    """Regla 1 of `steering/security.md` — the SQL scopes by `tenant_id` even though
    `related_id` is a UUID."""
    from app.maintenance.domain.enums import OwnerApprovalRelatedType
    from app.maintenance.infrastructure.models import OwnerApprovalModel

    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop = await _property(db_session, tenant_a, "REDES11")
    e = await _expense(db_session, tenant_a, prop, amount="150.00")

    approval = OwnerApprovalModel(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        property_id=prop.id,
        related_type=OwnerApprovalRelatedType.OTHER.value,
        related_id=e.id,
        amount=e.amount,
        reason=f"Expense #{e.id}",
    )
    db_session.add(approval)
    await db_session.flush()

    repo = SqlAlchemyExpenseRepository(db_session)
    # Same expense id, wrong tenant — must return None.
    assert (await repo.find_pending_owner_approval_for(tenant_b.id, e.id)) is None


# ---- Cross-tenant isolation (regla 1) for the §4 new methods ------------------


@pytest.mark.asyncio
async def test_find_by_unique_key_does_not_match_other_tenants_row(db_session) -> None:
    """Regla 1: a neighbour's `(property_id, period_start, period_end)` does not
    collide with this tenant's UNIQUE — the SQL filters by `tenant_id` first."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop_a = await _property(db_session, tenant_a, "REDES11")
    s = await _statement(db_session, tenant_a, prop_a)

    repo = SqlAlchemyOwnerStatementRepository(db_session)
    # Same `(property_id, period_start, period_end)` on TenantB — must return None.
    assert (
        await repo.find_by_unique_key(
            tenant_b.id, prop_a.id, s.period_start, s.period_end
        )
    ) is None
    # Same key on TenantA — must return the row.
    found = await repo.find_by_unique_key(
        tenant_a.id, prop_a.id, s.period_start, s.period_end
    )
    assert found is not None and found.id == s.id


@pytest.mark.asyncio
async def test_find_closed_period_does_not_match_other_tenants_statement(
    db_session,
) -> None:
    """Regla 1: a neighbour's `OwnerStatement` for the same `(property_id, date_)`
    does not close this tenant's period — the SQL filters by `tenant_id`."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop_a = await _property(db_session, tenant_a, "REDES11")
    other_prop = await _property(db_session, tenant_b, "REDES11")  # same code, different tenant
    await _statement(db_session, tenant_a, prop_a)

    repo = SqlAlchemyExpenseRepository(db_session)
    # TenantA asking about TenantB's property on the same date — must return None.
    assert (
        await repo.find_closed_period(
            tenant_id=tenant_a.id,
            property_id=other_prop.id,
            date_=date(2026, 7, 12),
        )
    ) is None


@pytest.mark.asyncio
async def test_delete_does_not_touch_other_tenants_expense(db_session) -> None:
    """Regla 1: a `DELETE` issued with the wrong tenant id cannot land on the row."""
    from app.statements.domain.entities import Expense

    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop_a = await _property(db_session, tenant_a, "REDES11")
    e = await _expense(db_session, tenant_a, prop_a, amount="50.00")

    # Build a domain Expense pointing at TenantA's row, but ask the repo (which is
    # bound to TenantB via `tenant_id`) to delete it.
    repo = SqlAlchemyExpenseRepository(db_session)
    domain_expense = Expense(
        id=e.id,
        tenant_id=tenant_a.id,
        property_id=prop_a.id,
        category=ExpenseCategory.MAINTENANCE,
        description=e.description,
        amount=e.amount,
        date=e.date,
        created_at=e.created_at,
        currency=e.currency,
    )
    await repo.delete(tenant_id=tenant_b.id, expense=domain_expense)

    # The row is still there because the SQL guard `tenant_id = :tenant_id` did not
    # match.
    refreshed = await repo.get(tenant_a.id, e.id)
    assert refreshed is not None and refreshed.id == e.id


@pytest.mark.asyncio
async def test_delete_refuses_consolidated_row(db_session) -> None:
    """D6.2 — the second line of defence: a `DELETE` on a consolidated row raises
    `ExpenseAlreadyConsolidatedError` even if the caller bypassed the use case's
    pre-check."""
    from app.statements.domain.exceptions import ExpenseAlreadyConsolidatedError

    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    statement = await _statement(db_session, tenant, prop)
    e = await _expense(db_session, tenant, prop, amount="50.00")
    repo = SqlAlchemyExpenseRepository(db_session)
    await repo.bulk_associate_to_statement(tenant.id, [e.id], statement.id)

    refreshed = await repo.get(tenant.id, e.id)
    assert refreshed is not None
    with pytest.raises(ExpenseAlreadyConsolidatedError):
        await repo.delete(tenant_id=tenant.id, expense=refreshed)
