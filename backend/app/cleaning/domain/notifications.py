"""The notifications a cleaning assignment produces (R6).

Pure builders, so the **content** of what gets written is testable without a session and
lives next to the rule that shapes it — rule 11 of `sdd/steering/security.md`, whose contract
for `notification_logs.subject`/`body` was fixed by `celery-jobs` (the first writer). This
change does not derive a new one; it complies with the one that exists.

What that means concretely, and it is the same discipline as `_escalation_row`
(`app/notifications/application/use_cases.py:198-232`): the body carries **ids and a type**,
never the content of another row. There is no access code and no credential anywhere near a
cleaning assignment, but the shape is what keeps it that way when somebody later adds the
property's address or the WiFi to the message.
"""

import uuid
from datetime import datetime, timedelta

from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

#: `related_type` for a row that points at `cleaning_tasks`. A constant because the SLA job
#: reads it back through the polymorphic pair and a second spelling would orphan those rows.
RELATED_TYPE_CLEANING_TASK = "cleaning_task"


def assignment_notification(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    property_id: uuid.UUID,
    cleaner_id: uuid.UUID,
    recipient_contact: str,
    sla_minutes: int,
    now: datetime,
) -> NotificationLog:
    """What the cleaner is told when a task is handed to them (R6.1).

    `status = PENDING` — queued work for the sender of `access-notifications`, exactly as
    `NotificationLogRepository.add` documents. **Not `SENT`**: nothing has been sent, and that
    column is what the future sender will read to decide what to send.

    The consequence is measured and recorded in the change's `BLOCKED.md` (OQ1):
    `list_sla_breach_candidates` requires `status = SENT`, so until that sender exists this
    deadline never produces an escalation. Writing `SENT` here would buy the escalation by
    asserting a delivery that did not happen.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=cleaner_id,
        recipient_contact=recipient_contact,
        channel=NotificationChannel.IN_APP,
        notification_type=NotificationType.CLEANING_TASK_ASSIGNED.value,
        created_at=now,
        updated_at=now,
        subject="Cleaning assigned",
        body=(
            f"A cleaning task has been assigned to you. Task {task_id}, "
            f"property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_CLEANING_TASK,
        related_id=task_id,
        # R6.1: `TenantConfig.sla_medium_minutes`, default 240 (PRD §11). The escalation this
        # deadline feeds is already defined — `CLEANING_TASK_ASSIGNED` → `SLA_BREACH` to the
        # `PROPERTY_MANAGER` (`app/notifications/domain/escalation.py:53-57`) — and this is its
        # first writer.
        sla_deadline_at=now + timedelta(minutes=sla_minutes),
    )


def no_cleaner_available_notification(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    property_id: uuid.UUID,
    manager_id: uuid.UUID,
    recipient_contact: str,
    now: datetime,
) -> NotificationLog:
    """PRD §11: "Si no hay limpiadora disponible: alertar a manager inmediatamente" (R6.3).

    **No `sla_deadline_at`**, and that is the point of the word *inmediatamente*: there is
    nobody whose silence could breach a deadline. A deadline here would escalate the manager
    to the manager.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=manager_id,
        recipient_contact=recipient_contact,
        channel=NotificationChannel.IN_APP,
        notification_type=NotificationType.CLEANING_NO_RESPONSE.value,
        created_at=now,
        updated_at=now,
        subject="Cleaning unassigned",
        body=(
            f"A cleaning task has no cleaner to assign. Task {task_id}, "
            f"property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_CLEANING_TASK,
        related_id=task_id,
    )
