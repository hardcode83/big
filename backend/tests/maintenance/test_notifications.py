import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.maintenance.domain.enums import IncidentSeverity
from app.maintenance.domain.notifications import (
    NOTIFICATION_TYPE_INCIDENT_REJECTED,
    RELATED_TYPE_INCIDENT,
    _SLA_FIELD_BY_SEVERITY,
    incident_critical_notification,
    incident_high_notification,
    incident_rejection_notification,
    owner_approval_notification,
    sla_minutes_for,
    technician_assignment_notification,
)
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
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


# --- The refusal's notification (`tech-cycle-completion` R1.4, design D3) ----------------


def test_the_rejection_notification_carries_no_sla_deadline() -> None:
    """R1.4 — "esa notificación NEVER SHALL llevar plazo de SLA".

    A refusal *is* the answer, so nobody is late; and there is no escalation policy for this
    type, so a deadline here would produce a breach that escalates to nobody — the same
    reasoning `owner_approval_notification` records for itself.
    """
    row = incident_rejection_notification(
        tenant_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        manager_id=uuid.uuid4(),
        recipient_contact="manager@example.com",
        now=NOW,
    )

    assert row.sla_deadline_at is None
    assert row.status is NotificationStatus.PENDING
    assert row.related_type == RELATED_TYPE_INCIDENT


def test_the_rejection_type_is_a_plain_string_and_not_a_notification_type() -> None:
    """D3 — deliberately outside `NotificationType`.

    That enum is the sixteen canonical names of PRD §14 and this is not one of them; the
    column has been free text since `domain-foundation-financial`, so there is no migration;
    and `escalation_for` returns `None` for a type it does not know, which is how R1.4's "no
    deadline, no escalation" is obtained by construction rather than by an omission somebody
    could fill in later.
    """
    assert NOTIFICATION_TYPE_INCIDENT_REJECTED == "INCIDENT_REJECTED"
    assert NOTIFICATION_TYPE_INCIDENT_REJECTED not in {
        member.value for member in NotificationType
    }


def test_the_rejection_notification_names_only_identifiers() -> None:
    """Rule 11's contract for `notification_logs.subject`/`body`: a constant plus ids.

    Asserted by driving the builder with a recognisable string in none of its inputs — every
    argument is a UUID or the recipient's own address — and checking the body carries the two
    identifiers and nothing that came from another row.
    """
    incident_id = uuid.uuid4()
    property_id = uuid.uuid4()

    row = incident_rejection_notification(
        tenant_id=uuid.uuid4(),
        incident_id=incident_id,
        property_id=property_id,
        manager_id=uuid.uuid4(),
        recipient_contact="manager@example.com",
        now=NOW,
    )

    assert str(incident_id) in row.body
    assert str(property_id) in row.body
    assert row.subject == "Incident rejected by the technician"


# --- The severity alerts (`notification-writers-gap` R1, design D4/D10) -----------------


@pytest.mark.parametrize(
    ("builder", "expected_type"),
    [
        (incident_critical_notification, NotificationType.INCIDENT_CREATED_CRITICAL),
        (incident_high_notification, NotificationType.INCIDENT_CREATED_HIGH),
    ],
)
def test_a_severity_alert_is_queued_in_app_and_points_at_the_incident(
    builder, expected_type
) -> None:
    """R5.3 — `PENDING` and `IN_APP`: queued work for `dispatch_notifications`, not a delivery.

    The polymorphic pair points at the **incident**, like every other builder in this module,
    so everything notified about one incident is reachable by one query — and so that R1.3's
    `exists_for` check has a stable pair to deduplicate on.
    """
    incident_id = uuid.uuid4()
    property_id = uuid.uuid4()
    manager_id = uuid.uuid4()

    log = builder(
        tenant_id=uuid.uuid4(),
        incident_id=incident_id,
        property_id=property_id,
        manager_id=manager_id,
        recipient_contact="manager@example.com",
        now=NOW,
    )

    assert log.notification_type == expected_type.value
    assert log.status is NotificationStatus.PENDING
    assert log.channel is NotificationChannel.IN_APP
    assert log.related_type == RELATED_TYPE_INCIDENT
    assert log.related_id == incident_id
    assert log.recipient_user_id == manager_id


@pytest.mark.parametrize(
    "builder", [incident_critical_notification, incident_high_notification]
)
def test_a_severity_alert_has_no_sla_deadline(builder) -> None:
    """R5.5, and it is unreachable rather than merely absent (design D10).

    Measured reason: `dispatch_notifications` moves `PENDING → SENT` every minute and
    `list_sla_breach_candidates` requires `SENT`, so a deadline here would produce a real
    breach candidate against a type `escalation_for` returns `None` for — the row would be
    marked breached and escalate to nobody.
    """
    log = builder(
        tenant_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        manager_id=uuid.uuid4(),
        recipient_contact="manager@example.com",
        now=NOW,
    )

    assert log.sla_deadline_at is None


@pytest.mark.parametrize(
    "builder", [incident_critical_notification, incident_high_notification]
)
def test_a_severity_alert_accepts_exactly_the_identifiers_and_nothing_else(builder) -> None:
    """R5.4 as a property of the signature, which is the only form that actually holds.

    The free-text test below can only fail if a builder interpolates prose it was **given**.
    That would catch a new *required* prose parameter — the call would raise `TypeError` —
    but not an optional `title: str | None = None` that a caller then feeds `incident.title`
    into. Raised by the section-4 security panel, whose own words for why the weaker form is
    not enough: the contract "se sostiene por disciplina del llamante, no hay punto único de
    paso". Pinning the exact parameter set turns that discipline into a shape the suite
    enforces, the same way the deadline test does for R5.5.
    """
    import inspect

    assert set(inspect.signature(builder).parameters) == {
        "tenant_id",
        "incident_id",
        "property_id",
        "manager_id",
        "recipient_contact",
        "now",
        # `notification-channel-routing` R2/R4 (design D2, D3): the fan-out dispatcher calls
        # every builder once per resolved channel, passing the channel and its contact.
        "channel",
        "contact",
    }


@pytest.mark.parametrize(
    "builder", [incident_critical_notification, incident_high_notification]
)
def test_a_severity_alert_takes_no_deadline_parameter(builder) -> None:
    """D10 again, but as a property of the signature rather than of one call.

    The test above would pass against a builder that merely defaults its deadline to `None`;
    this one fails unless there is **no way** to pass one. That is the difference between
    R5.5 holding and R5.5 being remembered.
    """
    import inspect

    parameters = set(inspect.signature(builder).parameters)

    assert not {p for p in parameters if "sla" in p or "deadline" in p or "minutes" in p}


@pytest.mark.parametrize(
    "builder", [incident_critical_notification, incident_high_notification]
)
def test_a_severity_alert_carries_no_incident_free_text(builder) -> None:
    """R5.4 / rule 11 of `steering/security.md`: a constant plus identifiers, nothing else.

    The three columns this must never read are named explicitly, because the incident is the
    one entity in this module that carries guest-typed prose: `title` and `description` come
    from the guest portal, and `ai_summary` is generated from them.
    """
    incident_id = uuid.uuid4()
    property_id = uuid.uuid4()
    leaked = {
        "title": "BOILER LEAKING ONTO THE NEIGHBOUR",
        "description": "the guest wrote their document number here",
        "ai_summary": "a summary that quotes the guest back",
    }

    log = builder(
        tenant_id=uuid.uuid4(),
        incident_id=incident_id,
        property_id=property_id,
        manager_id=uuid.uuid4(),
        recipient_contact="manager@example.com",
        now=NOW,
    )

    for value in leaked.values():
        assert value not in log.body
        assert value not in log.subject
    # Everything variable in the body is an identifier this module was handed.
    for token in log.body.replace(",", " ").replace(".", " ").split():
        if len(token) == 36 and "-" in token:
            assert uuid.UUID(token) in {incident_id, property_id}


def test_the_two_severity_alerts_are_distinguishable_to_a_reader() -> None:
    """They are two different facts (R1.4), so the row a manager reads must say which.

    R1.4 lets both exist for one incident when it is raised from HIGH to CRITICAL, so a
    subject shared between them would leave the inbox showing the same line twice.
    """
    kwargs = dict(
        tenant_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        manager_id=uuid.uuid4(),
        recipient_contact="manager@example.com",
        now=NOW,
    )

    critical = incident_critical_notification(**kwargs)
    high = incident_high_notification(**kwargs)

    assert critical.notification_type != high.notification_type
    assert critical.subject != high.subject
