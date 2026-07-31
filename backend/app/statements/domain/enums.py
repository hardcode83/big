import enum


class OwnerStatementStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (OwnerStatement.status) without a named block (§7.22)."""

    DRAFT = "DRAFT"
    READY = "READY"
    SENT = "SENT"


class ExpenseCategory(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (Expense.category) without a named block (§7.23)."""

    CLEANING = "CLEANING"
    LAUNDRY = "LAUNDRY"
    AMENITIES = "AMENITIES"
    MAINTENANCE = "MAINTENANCE"
    SPECIALIST = "SPECIALIST"
    PLATFORM_FEE = "PLATFORM_FEE"
    OTHER = "OTHER"
