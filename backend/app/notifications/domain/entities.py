import uuid
from dataclasses import dataclass
from datetime import datetime

from app.notifications.domain.enums import NotificationChannel, NotificationStatus


@dataclass
class NotificationLog:
    id: uuid.UUID
    tenant_id: uuid.UUID
    recipient_contact: str
    channel: NotificationChannel
    notification_type: str
    created_at: datetime
    updated_at: datetime
    recipient_user_id: uuid.UUID | None = None
    subject: str | None = None
    body: str | None = None
    status: NotificationStatus = NotificationStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    sent_at: datetime | None = None
    related_type: str | None = None
    related_id: uuid.UUID | None = None
    sla_deadline_at: datetime | None = None
    sla_breached: bool = False
