import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.maintenance.domain.entities import Incident, OwnerApproval
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)


def test_incident_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    incident = Incident(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        source=IncidentSource.GUEST,
        title="Broken AC",
        description="The AC unit in the living room is not cooling.",
        created_at=now,
        updated_at=now,
    )

    assert incident.category == IncidentCategory.OTHER
    assert incident.severity == IncidentSeverity.MEDIUM
    assert incident.status == IncidentStatus.OPEN
    assert incident.owner_approval_required is False
    assert incident.reservation_id is None


def test_owner_approval_instantiates_with_defaults() -> None:
    approval = OwnerApproval(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        related_type=OwnerApprovalRelatedType.INCIDENT,
        related_id=uuid.uuid4(),
        amount=Decimal("250.00"),
        reason="Boiler replacement quoted by the technician.",
        requested_at=datetime.now(timezone.utc),
    )

    assert approval.status is OwnerApprovalStatus.PENDING
    assert approval.responded_at is None
    assert approval.responded_by is None
    assert approval.response_notes is None


def test_owner_approval_has_no_created_or_updated_at() -> None:
    """Strict fidelity to §7.19 (design OQ1): only requested_at/responded_at."""
    fields = OwnerApproval.__dataclass_fields__

    assert "created_at" not in fields
    assert "updated_at" not in fields
    assert "requested_at" in fields
