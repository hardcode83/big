import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, UUIDPrimaryKeyMixin


class AuditLogModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """`changes` is a cleartext diff sink: rule-3 values go in redacted, never raw.

    steering/security.md rule 9 makes an audit entry mandatory for "acceso y
    modificación de datos de documento de Guest", and §7.25 shapes `changes` as
    `{field: {old: val, new: val}}`. A diff taken where the value is already
    decrypted would land `document_number` here in the clear — and rule 4 forbids the
    document number even in a listing, which
    `ix_audit_logs_tenant_id_entity_type_entity_id` makes cheap.

    **The contract, binding on `user-management` (role changes) and on whoever first
    audits guest documents** — this is the STRUCTURED form of the rule: a field
    covered by rules 3 or 4 (`document_number`, `wifi_password`, access codes) is
    recorded as `{"changed": true}` and its value does not survive at all, not even
    masked. Masking is not enough here: rule 4 keeps the document number out of
    listings entirely, and `ix_audit_logs_tenant_id_entity_type_entity_id` makes
    listing every Guest diff cheap.

    `WebhookEventModel.payload`/`error` and `NotificationLogModel.last_error` carry
    the same structured form. The single exception in the whole change is
    `NotificationLogModel.subject`/`body`, and only for **access codes**: those render
    a message a guest is meant to receive, so rule 4's `****XX` is allowed there.
    Never for `document_number`, and never here.

    This change creates the table and nothing writes to it yet, so the constraint is
    stated rather than enforced.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_id_entity_type_entity_id", "tenant_id", "entity_type", "entity_id"),
        Index(
            "ix_audit_logs_tenant_id_actor_user_id_created_at",
            "tenant_id",
            "actor_user_id",
            text("created_at DESC"),
        ),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    actor_ip: Mapped[str | None] = mapped_column(String(45), default=None)
    action: Mapped[str] = mapped_column(String(200))
    entity_type: Mapped[str] = mapped_column(String(100))
    # Polymorphic pair (§7.25): entity_id points at whatever table entity_type names,
    # so it deliberately carries no ForeignKey. Not an oversight.
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    # No TimestampMixin: §7.25 declares created_at only — an audit row is immutable.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
