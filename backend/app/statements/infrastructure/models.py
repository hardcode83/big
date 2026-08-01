import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus


def _money_zero() -> Mapped[Decimal]:
    """One of the eleven DECIMAL(10,2) NOT NULL DEFAULT 0 columns of §7.22."""
    return mapped_column(Numeric(10, 2), default=Decimal("0"), server_default="0")


class OwnerStatementModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "owner_statements"
    __table_args__ = (
        # Shortened from the usual uq_<table>_<every column>: the literal form would
        # be 66 characters and Postgres truncates identifiers at 63.
        UniqueConstraint(
            "tenant_id",
            "property_id",
            "period_start",
            "period_end",
            name="uq_owner_statements_tenant_property_period",
        ),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    gross_revenue: Mapped[Decimal] = _money_zero()
    ota_commissions: Mapped[Decimal] = _money_zero()
    net_revenue: Mapped[Decimal] = _money_zero()
    cleaning_costs: Mapped[Decimal] = _money_zero()
    laundry_costs: Mapped[Decimal] = _money_zero()
    amenities_costs: Mapped[Decimal] = _money_zero()
    maintenance_costs: Mapped[Decimal] = _money_zero()
    specialist_costs: Mapped[Decimal] = _money_zero()
    platform_fee: Mapped[Decimal] = _money_zero()
    other_costs: Mapped[Decimal] = _money_zero()
    net_owner_result: Mapped[Decimal] = _money_zero()
    status: Mapped[OwnerStatementStatus] = mapped_column(
        Enum(OwnerStatementStatus, name="owner_statement_status", native_enum=True),
        default=OwnerStatementStatus.DRAFT,
        server_default=OwnerStatementStatus.DRAFT.value,
    )
    notes: Mapped[str | None] = mapped_column(default=None)


class ExpenseModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "expenses"

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    # Nullable until the expense is consolidated into a statement (§7.23).
    statement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("owner_statements.id", ondelete="RESTRICT"), default=None
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), default=None
    )
    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(ExpenseCategory, name="expense_category", native_enum=True)
    )
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    date: Mapped[date] = mapped_column(Date)
    receipt_storage_key: Mapped[str | None] = mapped_column(String(500), default=None)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # No TimestampMixin: §7.23 declares created_at only.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
