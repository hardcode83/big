import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus

_ZERO = Decimal("0")


@dataclass
class OwnerStatement:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    period_start: date
    period_end: date
    created_at: datetime
    updated_at: datetime
    gross_revenue: Decimal = _ZERO
    ota_commissions: Decimal = _ZERO
    net_revenue: Decimal = _ZERO
    cleaning_costs: Decimal = _ZERO
    laundry_costs: Decimal = _ZERO
    amenities_costs: Decimal = _ZERO
    maintenance_costs: Decimal = _ZERO
    specialist_costs: Decimal = _ZERO
    platform_fee: Decimal = _ZERO
    other_costs: Decimal = _ZERO
    net_owner_result: Decimal = _ZERO
    status: OwnerStatementStatus = OwnerStatementStatus.DRAFT
    notes: str | None = None


@dataclass
class Expense:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    category: ExpenseCategory
    description: str
    amount: Decimal
    date: date
    created_at: datetime
    statement_id: uuid.UUID | None = None
    incident_id: uuid.UUID | None = None
    currency: str = "EUR"
    receipt_storage_key: str | None = None
    approved_by: uuid.UUID | None = None
