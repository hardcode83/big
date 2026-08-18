import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func, text
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

    Who writes this column, and under what contract, is declared in the rule 11 table of
    `sdd/steering/security.md` and nowhere else. Do not restate it here.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        # R1.2/R6.4 of `guest-portal-api`, enforced by the database and not only by
        # `AuditLogFactory`. The realistic accident is writing the **token** instead of its
        # digest: `secrets.token_urlsafe(32)` is 43 characters, so `String(64)` accepts it
        # without complaint and an append-only table would then hold live portal credentials.
        # The factory rejects it too, with a better message — but `AuditLog` is a plain
        # mutable dataclass and nothing forces a writer through the factory, which is the same
        # argument by which the cross-tenant guard lives in the repository rather than in the
        # use case (limit 3 of `app/core/db.py`). Raised by the security panel of section 1.
        CheckConstraint(
            "actor_guest_token_hash IS NULL OR actor_guest_token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_audit_logs_actor_guest_token_hash_is_a_digest",
        ),
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
    # The actor of the anonymous guest portal, named by the hash of the token they presented
    # (`guest-portal-api` design D11). 64 because it is a SHA-256 hex digest, the same width
    # as `guest_access_tokens.token_hash`.
    #
    # **A declared divergence from PRD §7.25**, which enumerates this table's columns and does
    # not include it. It is justified because §23 declares an anonymous guest surface and rule
    # 9 requires knowing who touched the data: the two sentences are only compatible with a
    # column. The alternatives were closed rather than merely rejected — `changes` cannot hold
    # it (`token_hash` is on rule 11's denylist, so `diff()` raises, and it is not a field of
    # the `GUEST` entity either), and leaving the actor NULL contradicts R6.1, which asks for
    # the bearer identified by their non-reversible reference.
    #
    # `ix_audit_logs_tenant_id_actor_user_id_created_at` is deliberately NOT extended to cover
    # it: these rows fall in that index's NULL bucket, and the question it answers ("everything
    # this person did") is about users.
    actor_guest_token_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    actor_ip: Mapped[str | None] = mapped_column(String(45), default=None)
    action: Mapped[str] = mapped_column(String(200))
    entity_type: Mapped[str] = mapped_column(String(100))
    # Polymorphic pair (§7.25): entity_id points at whatever table entity_type names,
    # so it deliberately carries no ForeignKey. Not an oversight.
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # **The same trap `incidents.ai_classification` fell into is dormant here**, and it is
    # written down rather than fixed because nothing triggers it today (found by the QA panel
    # of `maintenance`, 2026-08-15). Without `none_as_null=True`, SQLAlchemy stores a Python
    # `None` **assigned to the attribute** as JSON `'null'`, not as SQL `NULL`; only an
    # attribute nobody sets falls through to this default. Every reader of this column today
    # checks `entry.changes is None` in Python, which deserialises either form the same way,
    # so no behaviour depends on the difference. The day something filters `audit_logs` by
    # `changes IS NULL` **in SQL**, it will silently match none of the rows a writer that
    # passes the field explicitly produced. Change the flag then, with that query's test.
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    # No TimestampMixin: §7.25 declares created_at only — an audit row is immutable.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
