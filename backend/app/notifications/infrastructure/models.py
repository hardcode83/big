import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Uuid, text
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

    Who writes `subject`, `body` and `last_error`, and under what contract, is declared in the
    rule 11 table of `sdd/steering/security.md` and nowhere else. Do not restate it here — it
    lives in one place on purpose.
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
        Index(
            "ix_notification_logs_tenant_id_recipient_user_id_created_at",
            "tenant_id",
            "recipient_user_id",
            text("created_at DESC"),
        ),
        # Partial on purpose (`notifications-inbox-web` design D1): the unread counter is the
        # one query every connected user issues every 60 s, and the only one whose cost grows
        # without bound as read rows pile up. A partial index holds only what is unread.
        Index(
            "ix_notification_logs_unread",
            "tenant_id",
            "recipient_user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
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
    # Nullable with no server default (`notifications-inbox-web` design D1): every row written
    # before this column existed has been read by nobody, and a default of `now()` would have
    # declared them all read.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
