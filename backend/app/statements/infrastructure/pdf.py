"""PDF rendering for owner statements (R6.3-R6.5, D10)."""

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from fpdf import FPDF

from app.statements.domain.enums import ExpenseCategory


def _money(value: Any) -> str:
    """Format monetary values as required by the Spanish operator document."""
    return f"{Decimal(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _text(value: Any) -> str:
    """Keep core PDF fonts usable while preserving ordinary Spanish text."""
    return str(value if value is not None else "").encode("cp1252", errors="replace").decode(
        "cp1252"
    )


class PdfStatementGenerator:
    """Create a compact, printable statement using fpdf2's core fonts."""

    _CATEGORY_COST_FIELDS = (
        (ExpenseCategory.CLEANING, "Limpieza", "cleaning_costs"),
        (ExpenseCategory.LAUNDRY, "Lavandería", "laundry_costs"),
        (ExpenseCategory.AMENITIES, "Amenities", "amenities_costs"),
        (ExpenseCategory.MAINTENANCE, "Mantenimiento", "maintenance_costs"),
        (ExpenseCategory.SPECIALIST, "Especialistas", "specialist_costs"),
        (ExpenseCategory.PLATFORM_FEE, "Comisión de plataforma", "platform_fee"),
        (ExpenseCategory.OTHER, "Otros", "other_costs"),
    )

    def render(
        self,
        *,
        statement: Any,
        reservations: Sequence[Any],
        expenses_by_category: Mapping[Any, Iterable[Any]],
        tenant: Any,
        property: Any,
    ) -> bytes:
        pdf = FPDF()
        # Keep the text stream searchable by lightweight consumers (and by the
        # byte-level contract tests) without requiring a PDF parsing dependency.
        pdf.set_compression(False)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_title(_text(f"Owner statement {statement.period_start}"))
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, _text(getattr(tenant, "name", "Tenant")), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        pdf.cell(0, 7, _text(f"País: {getattr(tenant, 'country', '')}"), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, _text(getattr(property, "name", "Property")), new_x="LMARGIN", new_y="NEXT")
        address = ", ".join(
            str(value)
            for value in (
                getattr(property, "address_line1", None),
                getattr(property, "address_line2", None),
                getattr(property, "postal_code", None),
                getattr(property, "city", None),
                getattr(property, "province", None),
            )
            if value
        )
        pdf.cell(0, 7, _text(f"Código: {getattr(property, 'internal_code', '')}"), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, _text(f"Dirección: {address}"), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(
            0,
            7,
            _text(
                f"Periodo: {statement.period_start} - {statement.period_end} | "
                f"Estado: {getattr(statement.status, 'value', statement.status)}"
            ),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(4)

        self._heading(pdf, "Reservas")
        self._row(pdf, ("Entrada", "Noches", "Bruto", "Comisión", "Neto"), bold=True)
        for reservation in reservations:
            self._row(
                pdf,
                (
                    reservation.check_in_date,
                    str(reservation.nights),
                    _money(reservation.gross_amount or 0),
                    _money(reservation.ota_commission or 0),
                    _money(reservation.net_amount or 0),
                ),
            )
        self._row(
            pdf,
            (
                "Total ingresos",
                "",
                _money(statement.gross_revenue),
                _money(statement.ota_commissions),
                _money(statement.net_revenue),
            ),
            bold=True,
        )

        self._heading(pdf, "Gastos")
        self._row(pdf, ("Categoría", "Descripción", "Fecha", "Importe"), bold=True)
        for category, label, statement_field in self._CATEGORY_COST_FIELDS:
            rows = list(expenses_by_category.get(category, ()))
            for expense in rows:
                self._row(
                    pdf,
                    (_text(getattr(category, "value", category)), _text(expense.description), str(expense.date), _money(expense.amount)),
                )
            self._row(
                pdf,
                (_text(f"Subtotal {getattr(category, 'value', category)}"), "", "", _money(getattr(statement, statement_field, 0))),
                bold=True,
            )
        consolidated_costs = tuple(
            (label, getattr(statement, statement_field, 0))
            for _, label, statement_field in self._CATEGORY_COST_FIELDS
        )
        self._row(
            pdf,
            (
                "Total gastos",
                "",
                "",
                _money(sum((amount for _, amount in consolidated_costs), Decimal(0))),
            ),
            bold=True,
        )
        self._heading(pdf, "Resultado")
        self._row(pdf, ("Resultado neto del propietario", "", "", _money(statement.net_owner_result)), bold=True)
        if statement.notes:
            self._heading(pdf, "Notas")
            pdf.multi_cell(0, 7, _text(statement.notes), border=1)
        return bytes(pdf.output())

    @staticmethod
    def _heading(pdf: FPDF, text: str) -> None:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)

    @staticmethod
    def _row(pdf: FPDF, values: Sequence[Any], *, bold: bool = False) -> None:
        pdf.set_font("Helvetica", "B" if bold else "", 8)
        widths = (28, 62, 32, 30) if len(values) == 4 else (34, 22, 34, 34, 34)
        for width, value in zip(widths, values):
            pdf.cell(width, 6, _text(value), border=1)
        pdf.ln()
