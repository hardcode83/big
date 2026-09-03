import csv
import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.statements.domain.entities import Expense
from app.statements.domain.enums import ExpenseCategory
from app.statements.infrastructure.csv_export import CsvStatementExporter


def test_csv_has_exact_header_rows_and_utf8() -> None:
    expense = Expense(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(),
        category=ExpenseCategory.OTHER, description="Café y niño", amount=Decimal("12.30"),
        date=date(2026, 8, 1), created_at=datetime.now(UTC),
        receipt_storage_key="receipts/a.pdf",
    )
    body = CsvStatementExporter().render(
        header=("date", "category", "description", "amount", "currency", "receipt_storage_key"),
        rows=[expense],
    )
    assert not body.startswith(b"\xef\xbb\xbf")
    assert body.decode("utf-8").splitlines() == [
        "date,category,description,amount,currency,receipt_storage_key",
        "2026-08-01,OTHER,Café y niño,12.30,EUR,receipts/a.pdf",
    ]


def test_csv_neutralizes_spreadsheet_formula_cells() -> None:
    expense = Expense(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(),
        category=ExpenseCategory.OTHER, description="=HYPERLINK(\"https://evil\")",
        amount=Decimal("1.00"), date=date(2026, 8, 1),
        created_at=datetime.now(UTC), currency="+EUR", receipt_storage_key="@evil",
    )
    body = CsvStatementExporter().render(
        header=("date", "category", "description", "amount", "currency", "receipt_storage_key"), rows=[expense]
    )
    parsed = list(csv.reader(body.decode("utf-8").splitlines()))
    assert len(parsed[1]) == 6
    assert "'=HYPERLINK" in body.decode("utf-8")
    assert "'+EUR" in body.decode("utf-8")
    assert "'@evil" in body.decode("utf-8")


def test_csv_neutralizes_all_formula_prefixes() -> None:
    exporter = CsvStatementExporter()
    rows = []
    for prefix in ("=", "+", "-", "@"):
        rows.append(
            Expense(
                id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(),
                category=ExpenseCategory.OTHER, description=f"{prefix}formula,\"quoted\"",
                amount=Decimal("1.00"), date=date(2026, 8, 1),
                created_at=datetime.now(UTC),
            )
        )
    body = exporter.render(
        header=("date", "category", "description", "amount", "currency", "receipt_storage_key"),
        rows=rows,
    )
    parsed = list(csv.reader(body.decode("utf-8").splitlines()))
    assert len(parsed) == 5
    assert [row[2][0] for row in parsed[1:]] == ["'", "'", "'", "'"]


def test_csv_preserves_quoted_newline_and_unicode_cells_without_bom() -> None:
    expense = Expense(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), property_id=uuid.uuid4(),
        category=ExpenseCategory.OTHER,
        description='Línea "especial"\nCafé — niño', amount=Decimal("10.00"),
        date=date(2026, 8, 1), created_at=datetime.now(UTC),
        receipt_storage_key="recibos/á.pdf",
    )
    body = CsvStatementExporter().render(
        header=("date", "category", "description", "amount", "currency", "receipt_storage_key"),
        rows=[expense],
    )
    assert not body.startswith(b"\xef\xbb\xbf")
    parsed = list(csv.reader(io.StringIO(body.decode("utf-8"))))
    assert parsed[1] == [
        "2026-08-01", "OTHER", 'Línea "especial"\nCafé — niño', "10.00", "EUR", "recibos/á.pdf"
    ]


def test_csv_rejects_non_contract_header() -> None:
    with pytest.raises(ValueError, match="header"):
        CsvStatementExporter().render(header=("date", "description"), rows=[])
