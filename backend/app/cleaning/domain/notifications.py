"""The notifications a cleaning assignment produces (R6, `notification-channel-routing` R2/R4).

Pure builders, so the **content** of what gets written is testable without a session and
lives next to the rule that shapes it — rule 11 of `sdd/steering/security.md`, which is where
the contract for `notification_logs.subject`/`body` and its writers are declared. This module
does not derive a contract of its own; it complies with the one that exists.

What that means concretely, and it is the same discipline as `_escalation_row`
(`app/notifications/application/use_cases.py:198-232`): the body carries **ids and a type**,
never the content of another row. There is no access code and no credential anywhere near a
cleaning assignment, but the shape is what keeps it that way when somebody later adds the
property's address or the WiFi to the message.

**Channel + contact (notification-channel-routing R2, R4, design D2, D3).** Each builder
accepts `channel: NotificationChannel = IN_APP` and `contact: str | None = None` as
**optional** kwargs, and decides what to do with the row from there:

  * `recipient_contact` is `contact` when given, the legacy parameter otherwise. The
    legacy parameter is kept so existing tests that construct a single row continue to
    work without a dispatch step (R6.1, R6.3).
  * `sla_deadline_at` is set only when `channel == IN_APP` (R4.1) — the row the inbox
    actually shows is the one that carries the deadline; its siblings, if any, are
    `NULL` and therefore unreachable by `list_sla_breach_candidates`.

`dispatch_channels` (`app/notifications/application/channel_dispatch.py`) is the
function that calls each builder once per resolved channel with the right contact.
"""

import uuid
from datetime import datetime, timedelta

from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

RELATED_TYPE_CLEANING_TASK = "cleaning_task"

def assignment_notification(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    property_id: uuid.UUID,
    cleaner_id: uuid.UUID,
    recipient_contact: str = "",
    sla_minutes: int,
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """What the cleaner is told when a task is handed to them (R6.1).

    `status = PENDING` — queued work for the sender of `access-notifications`, exactly as
    `NotificationLogRepository.add` documents. **Not `SENT`**: nothing has been sent, and that
    column is what the future sender will read to decide what to send.

    The consequence is measured and recorded in the change's `BLOCKED.md` (OQ1):
    `list_sla_breach_candidates` requires `status = SENT`, so until that sender exists this
    deadline never produces an escalation. Writing `SENT` here would buy the escalation by
    asserting a delivery that did not happen.

    **Channel fan-out (R4.1)**: only the IN_APP row carries `sla_deadline_at`; siblings are
    `NULL`. The deadline is opened here and cancelled by `accept` and by a reassignment,
    both through `cancel_sla_deadline` on this same `related_type`/`related_id` pair, which
    is why the pair points at the **task** and not at this row.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=cleaner_id,
        recipient_contact=contact if contact is not None else recipient_contact,
        channel=channel,
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
        sla_deadline_at=now + timedelta(minutes=sla_minutes)
        if channel == NotificationChannel.IN_APP
        else None,
    )

def no_cleaner_available_notification(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    property_id: uuid.UUID,
    manager_id: uuid.UUID,
    recipient_contact: str = "",
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
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
        recipient_contact=contact if contact is not None else recipient_contact,
        channel=channel,
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

def completion_notification(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    property_id: uuid.UUID,
    recipient_id: uuid.UUID,
    recipient_contact: str = "",
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """What the manager is told when a cleaning is finished (R2.1).

    Closes half of the loop PRD §11 asks for: the validation step existed, but nothing told
    the manager there was anything to validate, so it depended on somebody opening the list.

    **No `sla_deadline_at`, and no parameter to give it one** (R5.5, design D10). Completion
    is not an assignment: nobody's silence can breach it. A deadline here would produce a
    breach candidate against a type `escalation_for` returns `None` for — a row marked
    breached that escalates to nobody.

    Subject and body are a constant plus identifiers, never the content of another row — the
    contract rule 11 of `sdd/steering/security.md` fixes for `notification_logs.subject`/`body`.
    Nothing here reads the checklist, the completion note, or any text the cleaner typed.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=recipient_id,
        recipient_contact=contact if contact is not None else recipient_contact,
        channel=channel,
        notification_type=NotificationType.CLEANING_COMPLETED.value,
        created_at=now,
        updated_at=now,
        subject="Cleaning completed",
        body=(
            f"A cleaning task has been completed and is awaiting validation. "
            f"Task {task_id}, property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_CLEANING_TASK,
        related_id=task_id,
    )

def validation_failed_notification(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    property_id: uuid.UUID,
    recipient_id: uuid.UUID,
    recipient_contact: str = "",
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """What the **cleaner** is told when their cleaning does not pass validation (R2.2).

    The other half of the loop, and it deliberately goes to the cleaner rather than the
    manager: the manager is the one who just issued the verdict, and telling them what they
    themselves decided is noise. `CLEANER` already holds `READ_OWN_NOTIFICATIONS`, so the
    role can read it.

    **No `sla_deadline_at`** (R5.5, D10), for the same reason as its sibling — and here the
    absence matters twice over, because a deadline on a row addressed to the cleaner would
    escalate the cleaner's silence about a verdict they cannot change.

    Subject and body are a constant plus identifiers. In particular this does **not** carry
    the manager's reason for failing the validation, which is free text a human typed and
    exactly what rule 11 keeps out of this column — the cleaner reads the verdict in the app,
    where the task's own fields live behind the task's own authorisation.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=recipient_id,
        recipient_contact=contact if contact is not None else recipient_contact,
        channel=channel,
        notification_type=NotificationType.CLEANING_FAILED.value,
        created_at=now,
        updated_at=now,
        subject="Cleaning validation failed",
        body=(
            f"A cleaning you completed did not pass validation. "
            f"Task {task_id}, property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_CLEANING_TASK,
        related_id=task_id,
    )

def staff_message_notification(
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    message_id: uuid.UUID,
    recipient_id: uuid.UUID,
    recipient_contact: str = "",
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """What the other side of a task's message thread is told (`staff-messaging` R4).

    Same shape as `assignment_notification`/`no_cleaner_available_notification`, and the
    same discipline on `body` (rule 11 of `sdd/steering/security.md`, design D8): it carries
    only `message_id` and `task_id` plus a constant text, **never `content`** — the message
    itself lives behind the thread's own authorisation, not in a notification row a much
    wider set of code paths can read.

    **No `sla_deadline_at`** (design D8): a staff message has no response deadline, so there
    is nothing here for `list_sla_breach_candidates` to ever pick up.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=recipient_id,
        recipient_contact=contact if contact is not None else recipient_contact,
        channel=channel,
        notification_type=NotificationType.CLEANING_TASK_MESSAGE.value,
        created_at=now,
        updated_at=now,
        subject="New cleaning task message",
        body=(
            f"You have a new message on a cleaning task. "
            f"Task {task_id}, message {message_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_CLEANING_TASK,
        related_id=task_id,
    )