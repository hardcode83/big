import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.properties.domain.entities import Property
from app.statements.domain.entities import Expense, OwnerStatement
from app.statements.domain.enums import ExpenseCategory
from app.statements.infrastructure.pdf import PdfStatementGenerator
from app.tenants.domain.entities import Tenant


def test_pdf_has_signature_and_statement_content() -> None:
    now = datetime.now(UTC)
    tenant = Tenant(uuid.uuid4(), "Tenant Madrid", "owner@example.com", now, now)
    property = Property(
        uuid.uuid4(), tenant.id, "Casa Centro", "CC-1", now, now,
        address_line1="Calle Mayor 1", postal_code="28001", city="Madrid",
    )
    statement = OwnerStatement(
        uuid.uuid4(), tenant.id, property.id, date(2026, 7, 1), date(2026, 7, 31), now, now,
        gross_revenue=Decimal("1000.10"), ota_commissions=Decimal("100.01"),
        net_revenue=Decimal("900.09"),
        other_costs=Decimal(25), net_owner_result=Decimal("875.09"), notes="Revisar factura",
    )
    expense = Expense(
        uuid.uuid4(), tenant.id, property.id, ExpenseCategory.OTHER, "Café", Decimal(25),
        date(2026, 7, 10), now, statement_id=statement.id,
    )
    body = PdfStatementGenerator().render(
        statement=statement,
        reservations=(),
        expenses_by_category={ExpenseCategory.OTHER: [expense]},
        tenant=tenant,
        property=property,
    )
    assert body[:4] == b"%PDF"
    assert body.count(b"/Type /Page\n") == 1
    assert b"Tenant Madrid" in body
    assert b"ES" in body and b"CC-1" in body and b"Calle Mayor 1" in body
    assert b"DRAFT" in body and b"Revisar factura" in body
    assert b"OwnerStatementStatus.DRAFT" not in body
    assert b"2026-07-01" in body and b"2026-07-31" in body
    assert b"OTHER" in body and b"Subtotal OTHER" in body
    assert b"Total gastos" in body and b"Resultado neto del propietario" in body
    assert b"1.000,10" in body and b"100,01" in body
    for category in ExpenseCategory:
        assert f"Subtotal {category.value}".encode() in body


def test_pdf_covers_reservation_rows_and_all_statement_amounts() -> None:
    now = datetime.now(UTC)
    tenant = Tenant(uuid.uuid4(), "Tenant", "owner@example.com", now, now)
    property = Property(uuid.uuid4(), tenant.id, "Piso", "P-1", now, now)
    statement = OwnerStatement(
        uuid.uuid4(), tenant.id, property.id, date(2026, 6, 1), date(2026, 6, 30), now, now,
        gross_revenue=Decimal("123.45"), ota_commissions=Decimal("12.34"),
        net_revenue=Decimal("111.11"), cleaning_costs=Decimal("1.01"),
        laundry_costs=Decimal("2.02"), amenities_costs=Decimal("3.03"),
        maintenance_costs=Decimal("4.04"), specialist_costs=Decimal("5.05"),
        platform_fee=Decimal("6.06"), other_costs=Decimal("7.07"),
        net_owner_result=Decimal("82.83"),
    )
    reservation = type(
        "ReservationRow",
        (),
        {
            "check_in_date": date(2026, 6, 10),
            "nights": 2,
            "gross_amount": Decimal("123.45"),
            "ota_commission": Decimal("12.34"),
            "net_amount": Decimal("111.11"),
        },
    )()
    body = PdfStatementGenerator().render(
        statement=statement,
        reservations=(reservation,),
        expenses_by_category={ExpenseCategory.OTHER: []},
        tenant=tenant,
        property=property,
    )
    for value in ("123,45", "12,34", "111,11", "1,01", "2,02", "3,03", "4,04", "5,05", "6,06", "7,07", "82,83"):
        assert value.encode() in body
    assert b"2026-06-10" in body and b"Total ingresos" in body
