"""The notifications an incident produces, and the SLA deadline one of them opens (R3, design D12).

Pure builders, calqued on `app/cleaning/domain/notifications.py`, so the **content** of what
gets written is testable without a session and lives next to the rule that shapes it — rule 11
of `sdd/steering/security.md`, whose contract for `notification_logs.subject`/`body` was fixed
by `celery-jobs`. This change does not derive a new one; it complies with the one that exists:
the body carries **ids and a type**, never the content of another row. Nothing here reads the
incident's `title`, `description` or `ai_summary`.

**No second SLA machinery** (R3.2): the deadline is a `sla_deadline_at` on the row, which is
what `list_sla_breach_candidates` / `mark_breached` / `cancel_sla_deadline` already read, and
the escalation `TECHNICIAN_ASSIGNED → TECHNICIAN_NO_RESPONSE → PROPERTY_MANAGER` is already
declared in `app/notifications/domain/escalation.py` — it said `SLA_BREACH` until
`notification-writers-gap` R3.1 gave the technician branch its own name. Unlike when `cleaning` wrote its own, the deadline
now works end to end: `access-notifications` left a `dispatch_notifications` that moves
`PENDING → SENT`, and `SENT` is what the breach query requires.
"""

import uuid
from datetime import datetime, timedelta

from app.maintenance.domain.enums import IncidentSeverity
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.tenants.domain.entities import TenantConfig

#: `related_type` for a row that points at `incidents`. A constant because the SLA job reads
#: it back through the polymorphic pair and a second spelling would orphan those rows — and
#: because `cancel_sla_deadline` is called with the same literal from three use cases.
RELATED_TYPE_INCIDENT = "incident"

#: Which `TenantConfig` field carries the deadline of each severity (R3.2, PRD §11). A
#: mapping rather than a chain of `if`s so that a severity added to the enum later fails
#: loudly in `sla_minutes_for` instead of silently inheriting somebody else's deadline.
_SLA_FIELD_BY_SEVERITY: dict[IncidentSeverity, str] = {
    IncidentSeverity.CRITICAL: "sla_critical_minutes",
    IncidentSeverity.HIGH: "sla_high_minutes",
    IncidentSeverity.MEDIUM: "sla_medium_minutes",
    IncidentSeverity.LOW: "sla_low_minutes",
}


def sla_minutes_for(severity: IncidentSeverity, config: TenantConfig) -> int:
    """How long the technician has, per the tenant's own configuration (R3.2).

    Pure, and the only place the severity-to-field correspondence is written: an incident
    that is `CRITICAL` for the deadline and `HIGH` for the escalation would be a bug nobody
    could see from either side.
    """
    field = _SLA_FIELD_BY_SEVERITY.get(severity)
    if field is None:
        raise KeyError(f"No SLA deadline is configured for severity {severity!r}")
    return int(getattr(config, field))


def technician_assignment_notification(
    *,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    property_id: uuid.UUID,
    technician_id: uuid.UUID,
    recipient_contact: str,
    sla_minutes: int,
    now: datetime,
) -> NotificationLog:
    """What the technician is told when an incident is handed to them (R3.1, R3.2).

    `status = PENDING` — queued work for the sender `access-notifications` left running,
    which is what moves it to `SENT` and therefore what makes `sla_deadline_at` reachable by
    `list_sla_breach_candidates`.

    The deadline is opened here and cancelled by `accept` (R3.3) and by a reassignment
    (R3.5), both through `cancel_sla_deadline` on this same `related_type`/`related_id`
    pair — which is why the pair points at the **incident** and not at this row.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=technician_id,
        recipient_contact=recipient_contact,
        channel=NotificationChannel.IN_APP,
        notification_type=NotificationType.TECHNICIAN_ASSIGNED.value,
        created_at=now,
        updated_at=now,
        subject="Incident assigned",
        body=(
            f"An incident has been assigned to you. Incident {incident_id}, "
            f"property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_INCIDENT,
        related_id=incident_id,
        sla_deadline_at=now + timedelta(minutes=sla_minutes),
    )


#: The `notification_type` of the row a refusal leaves for the manager (R1.4, design D3).
#:
#: A **plain string constant and not a member of `NotificationType`**, which is what `guests`
#: already does with `LEGAL_REGISTRATION_FAILED`, and for its three reasons: `NotificationType`
#: is the sixteen canonical names of PRD §14 and this is not one of them; the column is free
#: text since `domain-foundation-financial`, so there is **no migration**; and
#: `escalation_for` returns `None` for a type it does not recognise, which is exactly the "no
#: SLA deadline and no escalation" R1.4 demands — obtained by construction rather than by an
#: omission somebody could later fill in.
NOTIFICATION_TYPE_INCIDENT_REJECTED = "INCIDENT_REJECTED"


def incident_rejection_notification(
    *,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    property_id: uuid.UUID,
    manager_id: uuid.UUID,
    recipient_contact: str,
    now: datetime,
) -> NotificationLog:
    """What the manager is told when the technician says no (R1.4).

    **No `sla_deadline_at`, on purpose** (D3): a refusal *is* the answer, so nobody is late —
    the deadline the assignment opened is cancelled by the use case, and this row opens no new
    one. There is no escalation policy for this type either, so a deadline here would produce a
    breach that escalates to nobody, which is the same reasoning `owner_approval_notification`
    records above.

    Subject and body are a constant plus identifiers, never the content of another row — the
    contract rule 11 of `sdd/steering/security.md` fixes for
    `notification_logs.subject`/`body`. Nothing here reads the incident's `title`,
    `description`, `ai_summary` or the note the manager had written for the technician.

    The polymorphic pair points at the **incident** like its two siblings, so everything this
    module notifies about one incident is reachable by one query.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=manager_id,
        recipient_contact=recipient_contact,
        channel=NotificationChannel.IN_APP,
        notification_type=NOTIFICATION_TYPE_INCIDENT_REJECTED,
        created_at=now,
        updated_at=now,
        subject="Incident rejected by the technician",
        body=(
            f"A technician rejected an incident and it is awaiting reassignment. "
            f"Incident {incident_id}, property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_INCIDENT,
        related_id=incident_id,
    )


def owner_approval_notification(
    *,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    property_id: uuid.UUID,
    approval_id: uuid.UUID,
    owner_id: uuid.UUID,
    recipient_contact: str,
    now: datetime,
) -> NotificationLog:
    """What the owner is told when a cost needs their answer (R2.3).

    **No `sla_deadline_at`, on purpose** (D12): nobody has defined how long the owner may
    take, and `escalation_for` has no rule for `OWNER_APPROVAL_REQUIRED`, so a deadline here
    would produce a breach that escalates to nobody.

    The pair points at the incident like its sibling, so everything this module notifies
    about one incident is reachable by one query; the approval is named in the body, which
    is an identifier and therefore within what rule 11 allows this column.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=owner_id,
        recipient_contact=recipient_contact,
        channel=NotificationChannel.IN_APP,
        notification_type=NotificationType.OWNER_APPROVAL_REQUIRED.value,
        created_at=now,
        updated_at=now,
        subject="Owner approval required",
        body=(
            f"An incident needs your approval. Incident {incident_id}, "
            f"property {property_id}, approval {approval_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_INCIDENT,
        related_id=incident_id,
    )


def incident_critical_notification(
    *,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    property_id: uuid.UUID,
    manager_id: uuid.UUID,
    recipient_contact: str,
    now: datetime,
) -> NotificationLog:
    """What the manager is told when an incident turns out to be CRITICAL (R1.1).

    **No `sla_deadline_at`, and no parameter to give it one** (R5.5, design D10). The reason
    is measured rather than stylistic: `dispatch_notifications` moves `PENDING → SENT` every
    minute and `list_sla_breach_candidates` requires `SENT`, so a deadline here would produce
    a real breach candidate against a type `escalation_for` has no rule for — the row would be
    marked breached and escalate to nobody. Leaving the parameter out of the signature is what
    makes that unreachable instead of merely remembered.

    Subject and body are a constant plus identifiers, never the content of another row — the
    contract rule 11 of `sdd/steering/security.md` fixes for `notification_logs.subject`/`body`.
    Nothing here reads the incident's `title`, `description` or `ai_summary`, and on this
    entity that matters more than on its siblings: `title` and `description` are typed by the
    guest in the portal, and `ai_summary` is generated from them.

    **A separate constructor from its HIGH twin on purpose** (design D4). A single builder
    parameterised by severity would leave `R6`'s census with no literal to read, and both
    types would go on counting as orphans in the very change that gives them writers.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=manager_id,
        recipient_contact=recipient_contact,
        channel=NotificationChannel.IN_APP,
        notification_type=NotificationType.INCIDENT_CREATED_CRITICAL.value,
        created_at=now,
        updated_at=now,
        subject="Critical incident",
        body=(
            f"An incident has been classified as critical. Incident {incident_id}, "
            f"property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_INCIDENT,
        related_id=incident_id,
    )


def incident_high_notification(
    *,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    property_id: uuid.UUID,
    manager_id: uuid.UUID,
    recipient_contact: str,
    now: datetime,
) -> NotificationLog:
    """What the manager is told when an incident turns out to be HIGH (R1.2).

    The twin of `incident_critical_notification`, and deliberately a copy rather than a shared
    constructor with a severity argument — see that docstring and design D4 for why the census
    of R6 depends on the literal being written out here.

    Same contract: no deadline and no way to pass one (R5.5, D10), and a subject and body of a
    constant plus identifiers, never the incident's own text (R5.4, rule 11).

    Its subject differs from the CRITICAL one because R1.4 lets both rows exist for the same
    incident when a triage raises it from HIGH to CRITICAL, and an inbox showing the same line
    twice would hide exactly the escalation the manager needs to see.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=manager_id,
        recipient_contact=recipient_contact,
        channel=NotificationChannel.IN_APP,
        notification_type=NotificationType.INCIDENT_CREATED_HIGH.value,
        created_at=now,
        updated_at=now,
        subject="High severity incident",
        body=(
            f"An incident has been classified as high severity. Incident {incident_id}, "
            f"property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_INCIDENT,
        related_id=incident_id,
    )
