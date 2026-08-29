import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.statements.domain.entities import Expense, OwnerStatement
from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus
from app.statements.domain.exceptions import (
    OwnerStatementInvalidTransitionError,
    OwnerStatementValidationError,
)

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


# --- state machine tests (R4.1, R4.2, R4.4, D1) ---------------------------------


def _draft(now: datetime | None = None) -> OwnerStatement:
    now = now or datetime.now(timezone.utc)
    return OwnerStatement(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        created_at=now,
        updated_at=now,
    )


def test_owner_statement_marks_ready_from_draft() -> None:
    created = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    later = datetime(2026, 7, 31, 12, tzinfo=timezone.utc)
    statement = _draft(created)

    statement.mark_ready(now=later)

    assert statement.status is OwnerStatementStatus.READY
    # R4.6 — `updated_at` must move to the transition moment, otherwise a rejected
    # mark_ready would leave a timestamp artifact (and the manager would see a row
    # that "looks moved" but is still DRAFT).
    assert statement.updated_at == later


def test_owner_statement_marks_sent_from_ready() -> None:
    now = datetime.now(timezone.utc)
    later = datetime(2026, 7, 31, 12, tzinfo=timezone.utc)
    statement = _draft(now)
    statement.mark_ready(now=later)

    statement.mark_sent(now=later)

    assert statement.status is OwnerStatementStatus.SENT


def test_owner_statement_rejects_skip_from_draft_to_sent() -> None:
    statement = _draft()

    with pytest.raises(OwnerStatementInvalidTransitionError):
        statement.mark_sent(now=datetime.now(timezone.utc))


def test_owner_statement_rejects_transition_from_sent() -> None:
    now = datetime.now(timezone.utc)
    statement = _draft(now)
    statement.mark_ready(now=now)
    statement.mark_sent(now=now)

    with pytest.raises(OwnerStatementInvalidTransitionError):
        statement.mark_ready(now=now)

    with pytest.raises(OwnerStatementInvalidTransitionError):
        statement.mark_sent(now=now)


def test_owner_statement_rejects_double_ready() -> None:
    now = datetime.now(timezone.utc)
    statement = _draft(now)
    statement.mark_ready(now=now)

    with pytest.raises(OwnerStatementInvalidTransitionError):
        statement.mark_ready(now=now)


# --- update_notes tests (R4.5, R4.6, D1) --------------------------------------


def test_owner_statement_update_notes_accepts_a_non_empty_string() -> None:
    created = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    later = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    statement = _draft(created)

    statement.update_notes("Reviewed by manager.", now=later)

    assert statement.notes == "Reviewed by manager."
    # R4.6 — `updated_at` must move on accept; without this assertion, dropping
    # `self.updated_at = now` would slip past every test in the file.
    assert statement.updated_at == later


@pytest.mark.parametrize(
    "bad",
    [None, "", "   ", "\t\n", "before\x00after"],
)
def test_owner_statement_update_notes_rejects_invalid(bad: object) -> None:
    statement = _draft()

    with pytest.raises(OwnerStatementValidationError):
        statement.update_notes(bad, now=datetime.now(timezone.utc))


@pytest.mark.parametrize(
    "bad",
    [123, 1.5, [], {"x": 1}, b"bytes-not-str", object()],
)
def test_owner_statement_update_notes_rejects_non_string(bad: object) -> None:
    """`not isinstance(notes, str)` is the first guard; a regression to `notes is None`
    would let dicts/lists/ints fall through to `"\x00" in notes` and either crash or
    silently accept them, depending on the surface."""
    statement = _draft()

    with pytest.raises(OwnerStatementValidationError):
        statement.update_notes(bad, now=datetime.now(timezone.utc))  # type: ignore[arg-type]


def test_owner_statement_unknown_transition_operation_raises() -> None:
    """Defensive coverage for the `_check_transition("not_in_table")` branch — the two
    public methods hardcode their operation names, but the table-driven lookup is the
    single point of failure if a future operation slips in without registering here."""
    statement = _draft()

    with pytest.raises(OwnerStatementInvalidTransitionError):
        statement._check_transition("not_in_table")
