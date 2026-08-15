import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    OwnerApprovalRelatedType,
)
from app.maintenance.domain.exceptions import MaintenanceValidationError
from app.maintenance.domain.value_objects import (
    IncidentClassification,
    IncidentSummary,
    OwnerApprovalSummary,
)


def make_classification(confidence: Decimal) -> IncidentClassification:
    return IncidentClassification(
        category=IncidentCategory.HVAC,
        severity=IncidentSeverity.HIGH,
        summary="Air conditioning fault reported",
        confidence=confidence,
    )


@pytest.mark.parametrize("confidence", ["0", "0.5", "1"])
def test_confidence_within_the_unit_interval_is_accepted(confidence: str) -> None:
    assert make_classification(Decimal(confidence)).confidence == Decimal(confidence)


@pytest.mark.parametrize("confidence", ["-0.01", "1.01", "2", "-1"])
def test_confidence_outside_the_unit_interval_is_refused(confidence: str) -> None:
    """R1.1: it is compared against `TenantConfig.ai_confidence_threshold`, a 0..1 fraction.

    A percentage (`85`) or a negative would never be below any threshold, so the incident
    would be classified with full confidence by an adapter that meant the opposite.
    """
    with pytest.raises(MaintenanceValidationError):
        make_classification(Decimal(confidence))


def test_classification_is_frozen() -> None:
    classification = make_classification(Decimal("0.9"))

    with pytest.raises(Exception):
        classification.summary = "rewritten"  # type: ignore[misc]


def test_dashboard_projections_still_exclude_the_free_text_columns() -> None:
    """`dashboard-api`'s guarantee is structural, and this change must not widen it."""
    incident_fields = set(IncidentSummary.__dataclass_fields__)
    approval_fields = set(OwnerApprovalSummary.__dataclass_fields__)

    assert incident_fields.isdisjoint(
        {"title", "description", "ai_summary", "ai_classification"}
    )
    assert approval_fields.isdisjoint({"reason", "response_notes"})

    summary = IncidentSummary(
        id=uuid.uuid4(),
        category=IncidentCategory.HVAC,
        severity=IncidentSeverity.HIGH,
        opened_at=datetime.now(timezone.utc),
    )
    approval = OwnerApprovalSummary(
        id=uuid.uuid4(),
        related_type=OwnerApprovalRelatedType.INCIDENT,
        amount=Decimal("250.00"),
        requested_at=datetime.now(timezone.utc),
    )

    assert summary.category is IncidentCategory.HVAC
    assert approval.amount == Decimal("250.00")
