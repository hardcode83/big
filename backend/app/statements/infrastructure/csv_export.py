"""CSV serialisation for owner-statement expenses (R6.1-R6.2, D10)."""

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Protocol


class _ExpenseRow(Protocol):
    date: object
    category: object
    description: str
    amount: object
    currency: str
    receipt_storage_key: str | None


class CsvStatementExporter:
    """Render expense rows as UTF-8 CSV without a BOM."""

    HEADER = ("date", "category", "description", "amount", "currency", "receipt_storage_key")

    @staticmethod
    def _cell(value: object) -> str:
        """Prevent spreadsheet formula execution while preserving ordinary UTF-8 text."""
        text = str(value)
        return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text

    def render(
        self,
        *,
        header: Sequence[str],
        rows: Iterable[_ExpenseRow],
    ) -> bytes:
        if tuple(header) != self.HEADER:
            raise ValueError("CSV header must match the owner-statement export contract")
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(header)
        for expense in rows:
            category = getattr(expense.category, "value", expense.category)
            writer.writerow(
                (
                    expense.date.isoformat(),
                    category,
                    self._cell(expense.description),
                    str(expense.amount),
                    self._cell(expense.currency),
                    self._cell(expense.receipt_storage_key or ""),
                )
            )
        return output.getvalue().encode("utf-8")
