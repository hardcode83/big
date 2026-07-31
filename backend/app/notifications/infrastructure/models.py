import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.notifications.domain.enums import NotificationChannel, NotificationStatus


class NotificationLogModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """`subject`, `body` and `last_error` are cleartext: never a rule-3 secret.

    steering/security.md rule 3 forbids storing access codes, WiFi passwords or
    document numbers unencrypted, and rule 4 requires access codes to be masked
    (`****XX`). This table is the delivery record for exactly those notifications
    (PRD §17: the access code reaches the guest through one of these channels), so
    `body` is the one column in the schema that could quietly reopen a door
    `AccessRecordModel` deliberately closed — it stores `code_masked` only, with no
    plaintext column at all.

    **The contract, binding on `access-notifications`.** The discriminator is not
    "is it prose" but *does the column's purpose require showing the value to a human
    recipient*:

    - `subject`/`body` render a message a guest or owner is meant to receive, so an
      **access code** may appear in its rule-4 masked form (`****XX`) and never raw.
      That permission is granted to access codes ONLY: rule 4 gives no masked form to
      `document_number` — it demands absence from listings — and none to
      `wifi_password`. Those two follow the structured form below in every column of
      this table.
    - `last_error` is a delivery diagnostic. Nobody needs to be shown the code to
      debug a failed send, so it takes the **structured form**: no rule-3 value at
      all, masked or otherwise. This matches `WebhookEventModel.error`, which is the
      same data class — a provider SDK's exception routinely embeds the message it
      failed to send, so a raw error would put the code back in the clear one column
      over from a masked `body`.

    `AuditLogModel.changes` and `WebhookEventModel.payload`/`error` are all structured
    form. Do not copy the `subject`/`body` permission into any of them.

    This change creates the table and nothing writes to it yet, so the constraint is
    stated here rather than enforced — the writer inherits it with its own test.
    """

    __tablename__ = "notification_logs"
    __table_args__ = (
        Index(
            "ix_notification_logs_tenant_id_status_sla_deadline_at",
            "tenant_id",
            "status",
            "sla_deadline_at",
        ),
        Index("ix_notification_logs_related_type_related_id", "related_type", "related_id"),
    )

    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    recipient_contact: Mapped[str] = mapped_column(String(255))
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel", native_enum=True)
    )
    notification_type: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str | None] = mapped_column(String(500), default=None)
    body: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status", native_enum=True),
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(default=None)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Polymorphic pair (§7.24): related_id points at a different table depending on
    # related_type, so it deliberately carries no ForeignKey. Not an oversight.
    related_type: Mapped[str | None] = mapped_column(String(100), default=None)
    related_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    sla_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
