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
