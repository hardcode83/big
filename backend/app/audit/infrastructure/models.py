import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, UUIDPrimaryKeyMixin


class AuditLogModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """A cleartext diff sink. Structured form, per rule 11 of steering/security.md.

    Rule 9 makes an audit entry mandatory for "acceso y modificación de datos de
    documento de Guest", and §7.25 shapes `changes` as `{field: {old: val, new: val}}`
    — so the natural implementation takes the diff where the value is already
    decrypted. Masking would not save it either:
    `ix_audit_logs_tenant_id_entity_type_entity_id` makes listing every Guest diff
    cheap, and rule 4 keeps the document number out of listings entirely.

    Nothing writes here yet; `user-management` (role changes) and whoever first audits
    guest documents inherit the contract. Do not restate rule 11 here.
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
