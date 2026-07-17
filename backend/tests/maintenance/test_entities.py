import uuid
from datetime import datetime, timezone

from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
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
