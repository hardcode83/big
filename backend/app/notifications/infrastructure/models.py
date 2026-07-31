import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.notifications.domain.enums import NotificationChannel, NotificationStatus


class NotificationLogModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """Three cleartext sinks. The contract is rule 11 of steering/security.md.

    `subject`/`body` are the ONE exception it grants: an access code may appear as
    `****XX`. `last_error` is not covered by that exception — structured form, no
    rule-3 value at all — because a delivery diagnostic never needs to show anyone the
    code, and a provider SDK's exception routinely embeds the message it failed to
    send.

    Why this table matters more than it looks: PRD §17 has the access code reach the
    guest through one of these channels, so `body` is the one column that could
    quietly reopen a door `AccessRecordModel` deliberately closed — it stores
    `code_masked` only, with no plaintext column at all.

    Nothing writes here yet; `access-notifications` inherits the contract with its own
    test. Do not restate rule 11 here — it lives in one place on purpose.
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
