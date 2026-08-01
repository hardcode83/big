import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.auth.infrastructure.models import UserModel
from app.properties.infrastructure.models import PropertyModel
from app.statements.domain.enums import ExpenseCategory
from app.statements.infrastructure.models import ExpenseModel, OwnerStatementModel
from app.tenants.infrastructure.models import TenantModel

_MONEY_COLUMNS = (
    "gross_revenue",
    "ota_commissions",
    "net_revenue",
    "cleaning_costs",
    "laundry_costs",
    "amenities_costs",
    "maintenance_costs",
    "specialist_costs",
    "platform_fee",
    "other_costs",
    "net_owner_result",
)


async def _tenant_property(db_session):
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code="redes11")
    db_session.add(prop)
    await db_session.flush()
    return tenant, prop


def _statement(tenant_id, property_id) -> OwnerStatementModel:
    return OwnerStatementModel(
        tenant_id=tenant_id,
        property_id=property_id,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )


@pytest.mark.asyncio
async def test_owner_statement_is_unique_per_tenant_property_and_period(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    for _ in range(2):
        db_session.add(_statement(tenant.id, prop.id))

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_owner_statement_amount_defaults_come_from_the_ddl(db_session) -> None:
    """Raw `text()` on purpose (QA finding, section 1).

    `Table.insert().values(...)` still applies each column's Python-side `default=`,
    so it would pass with every `server_default` stripped from the model. Only a
    statement SQLAlchemy knows nothing about reaches Postgres's own DEFAULT — which
    is what a data migration or a psql session would hit (R3.2).
    """
    tenant, prop = await _tenant_property(db_session)

    await db_session.execute(
        text(
            "INSERT INTO owner_statements "
            "(id, tenant_id, property_id, period_start, period_end) "
            "VALUES (:id, :tenant_id, :property_id, DATE '2026-06-01', DATE '2026-06-30')"
        ),
        {"id": uuid.uuid4(), "tenant_id": tenant.id, "property_id": prop.id},
    )
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(OwnerStatementModel).where(OwnerStatementModel.period_start == date(2026, 6, 1))
        )
    ).scalar_one()
    assert fetched.status.value == "DRAFT"
    for name in _MONEY_COLUMNS:
        assert getattr(fetched, name) == Decimal("0"), name


@pytest.mark.asyncio
async def test_expense_currency_default_comes_from_the_ddl(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    await db_session.execute(
        text(
            "INSERT INTO expenses (id, tenant_id, property_id, category, description, amount, date) "
            "VALUES (:id, :tenant_id, :property_id, 'CLEANING', 'raw insert', 45.00, "
            "DATE '2026-07-12')"
        ),
        {"id": uuid.uuid4(), "tenant_id": tenant.id, "property_id": prop.id},
    )
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(ExpenseModel).where(ExpenseModel.description == "raw insert")
        )
    ).scalar_one()
    assert fetched.currency == "EUR"
    assert fetched.statement_id is None
    assert fetched.incident_id is None
    assert fetched.created_at is not None


@pytest.mark.asyncio
async def test_expense_statement_restrict_on_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    statement = _statement(tenant.id, prop.id)
    db_session.add(statement)
    await db_session.flush()

    db_session.add(
        ExpenseModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            statement_id=statement.id,
            category=ExpenseCategory.LAUNDRY,
            description="Linen service.",
            amount=Decimal("22.50"),
            date=date(2026, 7, 12),
        )
    )
    await db_session.commit()

    await db_session.delete(statement)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_expense_approver_set_null_on_user_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    owner = UserModel(
        tenant_id=tenant.id,
        name="Owner Olga",
        email="olga@example.com",
        password_hash="hash",
        role="TENANT_OWNER",
    )
    db_session.add(owner)
    await db_session.flush()

    expense = ExpenseModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        category=ExpenseCategory.MAINTENANCE,
        description="Boiler part.",
        amount=Decimal("120.00"),
        date=date(2026, 7, 20),
        approved_by=owner.id,
    )
    db_session.add(expense)
    await db_session.commit()

    await db_session.delete(owner)
    await db_session.commit()
    await db_session.refresh(expense)

    assert expense.approved_by is None
    assert expense.amount == Decimal("120.00")


@pytest.mark.asyncio
async def test_expenses_has_no_updated_at_column() -> None:
    """§7.23 declares created_at only."""
    columns = set(ExpenseModel.__table__.columns.keys())

    assert "created_at" in columns
    assert "updated_at" not in columns


@pytest.mark.asyncio
async def test_owner_statement_property_restrict_on_delete(db_session) -> None:
    """`owner_statements.property_id` is this model's OWN mandatory FK (R3.7, D8).

    Its UNIQUE constraint and its child's RESTRICT were covered; this column was not,
    so a change to CASCADE would have deleted statements with their property silently.
    """
    tenant, prop = await _tenant_property(db_session)
    db_session.add(_statement(tenant.id, prop.id))
    await db_session.commit()

    await db_session.delete(prop)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_expense_property_restrict_on_delete(db_session) -> None:
    """`expenses.property_id` — the same gap, one table over."""
    tenant, prop = await _tenant_property(db_session)
    db_session.add(
        ExpenseModel(
            tenant_id=tenant.id,
            property_id=prop.id,
            category=ExpenseCategory.AMENITIES,
            description="Welcome pack.",
            amount=Decimal("15.00"),
            date=date(2026, 7, 12),
        )
    )
    await db_session.commit()

    await db_session.delete(prop)
    with pytest.raises(IntegrityError):
        await db_session.commit()
