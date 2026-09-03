import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar

from app.statements.domain.enums import ExpenseCategory, OwnerStatementStatus
from app.statements.domain.exceptions import (
    OwnerStatementInvalidTransitionError,
    OwnerStatementValidationError,
)

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

    #: The legal state moves of `OwnerStatement` (R4.2, R4.4, design D1).
    #:
    #: Keyed by **operation** rather than by origin→destinations, so two different
    #: operations can share a destination without sharing their origins: `mark_ready`
    #: is `DRAFT → READY` only, `mark_sent` is `READY → SENT` only, and there is no
    #: operation that jumps `DRAFT → SENT`. `SENT` is terminal: it appears as an origin
    #: nowhere, which is what makes it terminal without an extra rule.
    _TRANSITIONS: ClassVar[Mapping[str, tuple[frozenset[OwnerStatementStatus], OwnerStatementStatus]]] = {
        "mark_ready": (
            frozenset({OwnerStatementStatus.DRAFT}),
            OwnerStatementStatus.READY,
        ),
        "mark_sent": (
            frozenset({OwnerStatementStatus.READY}),
            OwnerStatementStatus.SENT,
        ),
    }

    def _check_transition(self, operation: str) -> OwnerStatementStatus:
        """Return the destination status if the operation is legal from the current one."""
        if operation not in self._TRANSITIONS:
            raise OwnerStatementInvalidTransitionError(
                f"Unknown operation {operation!r}"
            )
        valid_origins, destination = self._TRANSITIONS[operation]
        if self.status not in valid_origins:
            raise OwnerStatementInvalidTransitionError(
                f"Cannot {operation} a statement in status {self.status.value}"
            )
        return destination

    def mark_ready(self, *, now: datetime) -> None:
        """Transition `DRAFT → READY`. Raises `OwnerStatementInvalidTransitionError` from any other origin (including `READY` itself — caller retry is not silently absorbed)."""
        destination = self._check_transition("mark_ready")
        self.status = destination
        self.updated_at = now

    def mark_sent(self, *, now: datetime) -> None:
        """Transition `READY → SENT`. Raises `OwnerStatementInvalidTransitionError` from any other origin; `SENT` is terminal (R4.4)."""
        destination = self._check_transition("mark_sent")
        self.status = destination
        self.updated_at = now

    def update_notes(self, notes: str, *, now: datetime) -> None:
        """Replace `notes`. Rejects empty/whitespace-only strings and U+0000 (regla 11)."""
        if not isinstance(notes, str):
            raise OwnerStatementValidationError(
                "notes must be a string",
                field="notes",
            )
        if "\x00" in notes:
            raise OwnerStatementValidationError(
                "notes must not contain U+0000",
                field="notes",
            )
        if not notes.strip():
            raise OwnerStatementValidationError(
                "notes must not be empty or whitespace",
                field="notes",
            )
        self.notes = notes
        self.updated_at = now


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
