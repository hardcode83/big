"""Response DTOs for the in-app notifications endpoint (PRD §23, design D6).

**Fields are enumerated, never dumped from the entity**, and here that rule carries more
than style. `NotificationLog` holds three things this surface must not publish:

* `recipient_contact` — an email or phone number. The caller already knows their own, and
  publishing it makes the row a directory entry.
* `last_error` — a delivery diagnostic. Rule 11 of `steering/security.md` governs what may
  live in it; nothing governs who may *read* it, so it stays server-side.
* `sla_deadline_at` / `sla_breached` — operational state of the escalation machinery, not
  something the recipient acts on.

`subject` and `body` DO travel: they are the message, and rule 11's single sanctioned
exception (a masked access code, `****XX`) exists precisely so the recipient can read it.
The web inbox does not paint them (`notifications-inbox-web` R4.2 — they are written in
English, for an operator, and carry raw UUIDs), but they stay published: another client may
want them, and this change does not narrow a contract it did not come to narrow.

`read_at` joins them with `notifications-inbox-web` (R2.1). The four retained fields above
stay retained: that change does not reopen them.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)


class NotificationResponse(BaseModel):
    id: uuid.UUID
    #: `NotificationType | str`, and the union is load-bearing (`notifications-inbox-web`
    #: D7). The column is a free `String(100)` that admits values written before the enum
    #: existed, so narrowing it to the enum would turn the case R4.3 orders us to tolerate
    #: into a `500` at serialisation time. Publishing the union instead puts
    #: `components["schemas"]["NotificationType"]` — the seventeen names — into the
    #: contract, which is what lets the frontend's copy catalogue be typed by it and makes
    #: a missing translation a `npm run typecheck` failure rather than a reviewer's job.
    notification_type: NotificationType | str
    channel: NotificationChannel
    status: NotificationStatus
    subject: str | None
    body: str | None
    related_type: str | None
    related_id: uuid.UUID | None
    sent_at: datetime | None
    created_at: datetime
    read_at: datetime | None

    @classmethod
    def from_domain(cls, log: NotificationLog) -> "NotificationResponse":
        return cls(
            id=log.id,
            notification_type=log.notification_type,
            channel=log.channel,
            status=log.status,
            subject=log.subject,
            body=log.body,
            related_type=log.related_type,
            related_id=log.related_id,
            sent_at=log.sent_at,
            created_at=log.created_at,
            read_at=log.read_at,
        )


class UnreadCountResponse(BaseModel):
    """The bell's counter (R2.2, design D4). Its own shape, not a field of the envelope."""

    unread: int


class MarkAllReadResponse(BaseModel):
    """How many rows "mark all as read" moved (R5.2, design D6). Zero is a normal answer."""

    updated: int


class NotificationPageResponse(BaseModel):
    data: list[NotificationResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, items, total: int, page: int, per_page: int
    ) -> "NotificationPageResponse":
        return cls(
            data=[NotificationResponse.from_domain(item) for item in items],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )
