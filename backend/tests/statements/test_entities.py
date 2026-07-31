import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.statements.domain.entities import Expense, OwnerStatement
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus

_MONEY_FIELDS = (
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


def test_owner_statement_instantiates_with_every_amount_at_zero() -> None:
    now = datetime.now(timezone.utc)
    statement = OwnerStatement(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        created_at=now,
        updated_at=now,
    )

    assert statement.status is OwnerStatementStatus.DRAFT
    assert statement.notes is None
    for name in _MONEY_FIELDS:
        assert getattr(statement, name) == Decimal("0"), name


def test_owner_statement_declares_the_eleven_amounts_of_the_prd() -> None:
    assert set(_MONEY_FIELDS) <= set(OwnerStatement.__dataclass_fields__)
    assert len(_MONEY_FIELDS) == 11


def test_expense_instantiates_with_defaults() -> None:
    expense = Expense(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        category=ExpenseCategory.CLEANING,
        description="Turnover clean after checkout.",
        amount=Decimal("45.00"),
        date=date(2026, 7, 12),
        created_at=datetime.now(timezone.utc),
    )

    assert expense.currency == "EUR"
    assert expense.statement_id is None
    assert expense.incident_id is None
    assert expense.receipt_storage_key is None
    assert expense.approved_by is None
