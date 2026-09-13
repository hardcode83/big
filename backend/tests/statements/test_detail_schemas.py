"""Minimal API projections for owner-statement financial detail."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import get_args, get_origin

from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel
from app.reservations.domain.enums import ReservationStatus
from fastapi.routing import APIRoute
from app.statements.api.schemas import (
    OwnerStatementExpenseBreakdownResponse,
    OwnerStatementDetailResponse,
    OwnerStatementPageResponse,
    OwnerStatementReservationBreakdownResponse,
    OwnerStatementResponse,
)
from app.statements.api.dependencies import get_owner_statement_use_case
from app.statements.api.router import router
from app.statements.domain.entities import Expense
from app.statements.domain.enums import ExpenseCategory


NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


def test_reservation_breakdown_only_serializes_financial_stay_fields() -> None:
    reservation = Reservation(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        channel=ReservationChannel.BOOKING,
        check_in_date=date(2026, 7, 10),
        check_out_date=date(2026, 7, 13),
        nights=3,
        created_at=NOW,
        updated_at=NOW,
        guest_id=uuid.uuid4(),
        external_pms_id="private-pms-id",
        status=ReservationStatus.CONFIRMED,
        gross_amount=Decimal("300.00"),
        ota_commission=Decimal("45.00"),
        net_amount=Decimal("255.00"),
        internal_notes="private note",
        guest_full_name="Private Guest",
    )

    body = OwnerStatementReservationBreakdownResponse.from_domain(reservation).model_dump()

    assert set(body) == {
        "id",
        "check_in_date",
        "nights",
        "gross_amount",
        "ota_commission",
        "net_amount",
        "currency",
    }
    assert body["id"] == reservation.id
    assert body["gross_amount"] == Decimal("300.00")


def test_expense_breakdown_only_serializes_financial_fields() -> None:
    expense = Expense(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        category=ExpenseCategory.CLEANING,
        description="Linen service",
        amount=Decimal("25.00"),
        date=date(2026, 7, 11),
        created_at=NOW,
        statement_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        receipt_storage_key="private/receipt.pdf",
        approved_by=uuid.uuid4(),
    )

    body = OwnerStatementExpenseBreakdownResponse.from_domain(expense).model_dump()

    assert set(body) == {
        "id",
        "category",
        "description",
        "amount",
        "currency",
        "date",
    }
    assert body["id"] == expense.id
    assert body["amount"] == Decimal("25.00")


def test_detail_does_not_enrich_shared_list_schema() -> None:
    items = OwnerStatementPageResponse.model_fields["items"].annotation

    assert get_origin(items) is list
    assert get_args(items) == (OwnerStatementResponse,)
    assert OwnerStatementDetailResponse.model_fields["expenses"].is_required()
    assert OwnerStatementDetailResponse.model_fields["reservations"].is_required()


def test_only_detail_route_uses_detail_composition() -> None:
    routes = {
        (route.path, method): route
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }

    detail = routes[("/owner-statements/{statement_id}", "GET")]
    listing = routes[("/owner-statements", "GET")]
    mutation = routes[("/owner-statements/{statement_id}", "PATCH")]

    assert detail.response_model is OwnerStatementDetailResponse
    assert listing.response_model is OwnerStatementPageResponse
    assert mutation.response_model is OwnerStatementResponse
    assert any(
        dependency.call is get_owner_statement_use_case
        for dependency in detail.dependant.dependencies
    )
    assert all(
        dependency.call is not get_owner_statement_use_case
        for route in (listing, mutation)
        for dependency in route.dependant.dependencies
    )
