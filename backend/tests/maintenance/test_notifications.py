import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.maintenance.domain.enums import IncidentSeverity
from app.maintenance.domain.notifications import (
    RELATED_TYPE_INCIDENT,
    _SLA_FIELD_BY_SEVERITY,
    owner_approval_notification,
    sla_minutes_for,
    technician_assignment_notification,
)
from app.notifications.domain.enums import NotificationStatus, NotificationType
from app.tenants.domain.entities import TenantConfig

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)


def make_config() -> TenantConfig:
    return TenantConfig.with_defaults(tenant_id=uuid.uuid4(), now=NOW)


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (IncidentSeverity.CRITICAL, 5),
        (IncidentSeverity.HIGH, 15),
        (IncidentSeverity.MEDIUM, 240),
        (IncidentSeverity.LOW, 480),
    ],
)
def test_sla_minutes_come_from_the_tenant_config(
    severity: IncidentSeverity, expected: int
) -> None:
    """R3.2, PRD §11 defaults — all four severities, so none inherits another's deadline."""
    assert sla_minutes_for(severity, make_config()) == expected


def test_every_severity_has_a_deadline() -> None:
    config = make_config()

    for severity in IncidentSeverity:
        assert sla_minutes_for(severity, config) > 0


def test_the_map_covers_the_enum_exactly() -> None:
    """What actually protects R3.2: the loud failure below is only reachable if this drifts.

    A severity added to `IncidentSeverity` without a `TenantConfig` field would otherwise
    inherit somebody else's deadline, which is the failure nobody would see.
    """
    assert set(_SLA_FIELD_BY_SEVERITY) == set(IncidentSeverity)


def test_a_severity_outside_the_map_fails_loudly() -> None:
    """The branch the assertion above exists to keep unreachable — exercised anyway, so it
    cannot rot into a silent default."""
    with pytest.raises(KeyError):
        sla_minutes_for("SEVERITY_FROM_THE_FUTURE", make_config())  # type: ignore[arg-type]


def test_sla_minutes_follow_a_reconfigured_tenant() -> None:
    config = make_config()
    config.sla_critical_minutes = 3

    assert sla_minutes_for(IncidentSeverity.CRITICAL, config) == 3


def test_technician_assignment_opens_the_sla_deadline() -> None:
    incident_id = uuid.uuid4()
    technician_id = uuid.uuid4()

    log = technician_assignment_notification(
        tenant_id=uuid.uuid4(),
        incident_id=incident_id,
        property_id=uuid.uuid4(),
        technician_id=technician_id,
        recipient_contact="tech@example.com",
        sla_minutes=15,
        now=NOW,
    )

    assert log.notification_type == NotificationType.TECHNICIAN_ASSIGNED.value
    assert log.status is NotificationStatus.PENDING
    assert log.related_type == RELATED_TYPE_INCIDENT
    assert log.related_id == incident_id
    assert log.recipient_user_id == technician_id
    assert log.sla_deadline_at == NOW + timedelta(minutes=15)


def test_owner_approval_notification_has_no_deadline() -> None:
    """D12: nobody defined how long the owner may take, and `escalation_for` has no rule
    for `OWNER_APPROVAL_REQUIRED` — a deadline here escalates to nobody."""
    log = owner_approval_notification(
        tenant_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        approval_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        recipient_contact="owner@example.com",
        now=NOW,
    )

    assert log.notification_type == NotificationType.OWNER_APPROVAL_REQUIRED.value
    assert log.status is NotificationStatus.PENDING
    assert log.sla_deadline_at is None


def test_neither_notification_carries_incident_free_text() -> None:
    """Rule 11 of `steering/security.md`: ids and a type, never the content of another row."""
    incident_id = uuid.uuid4()
    property_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    leaked = "the guest wrote their document number here"

    logs = [
        technician_assignment_notification(
            tenant_id=uuid.uuid4(),
            incident_id=incident_id,
            property_id=property_id,
            technician_id=uuid.uuid4(),
            recipient_contact="tech@example.com",
            sla_minutes=15,
            now=NOW,
        ),
        owner_approval_notification(
            tenant_id=uuid.uuid4(),
            incident_id=incident_id,
            property_id=property_id,
            approval_id=approval_id,
            owner_id=uuid.uuid4(),
            recipient_contact="owner@example.com",
            now=NOW,
        ),
    ]

    for log in logs:
        assert leaked not in log.body
        # Everything variable in the body is an identifier this module was handed.
        for token in log.body.replace(",", " ").replace(".", " ").split():
            if len(token) == 36 and "-" in token:
                assert uuid.UUID(token) in {incident_id, property_id, approval_id}
