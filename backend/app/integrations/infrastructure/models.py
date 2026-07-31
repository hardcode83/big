import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


class WebhookEventModel(Base, UUIDPrimaryKeyMixin):
    """The one table in the schema whose `tenant_id` is nullable (§7.26).

    It deliberately does NOT use `TenantScopedMixin`, which hard-codes
    `nullable=False`. The column is declared by hand instead, keeping the mixin's
    `Uuid` type, FK to `tenants.id` and index.

    **Consequence, and it is not a bug**: `tenant_scoped_classes()` selects by column
    presence, not by mixin, so this table IS inside the global filter — and on a
    session marked with a tenant, `tenant_id == X` hides exactly the `NULL` rows,
    which are the ones `reservations-webhooks` will need to process. That job must
    read them from an UNMARKED session, the same way Celery and the anonymous login
    path already do (second limit in the docstring of `_scope_statement_to_tenant`).
    Pinned by `tests/test_tenant_filter.py::test_webhook_events_without_a_tenant_are_invisible_to_a_marked_session`.

    **`payload` and `error` are cleartext sinks fed by an external party**, and more
    exposed than the other two in this change: PRD §16 has the provider POST this body
    and §7.26 has it persisted verbatim. A PMS check-in event can carry
    `document_number`, which steering/security.md rule 3 forbids storing unencrypted
    and rule 4 forbids surfacing in listings.

    **The contract, binding on `reservations-webhooks`** — the STRUCTURED form, the
    same one `AuditLogModel.changes` carries: a field covered by rules 3 or 4 is
    stripped before persisting and its value does not survive at all, not even masked.
    `error` must never echo the raw body back, which would reintroduce through the
    text column what `payload` just dropped.

    `NotificationLogModel.last_error` carries this same form — it is the same data
    class as `error` here, a provider diagnostic. The only column in the change with a
    looser rule is `NotificationLogModel.subject`/`body`, and only for **access
    codes**, because those render a message a guest is meant to receive. Nothing reads
    a webhook payload or a delivery error to be shown it, so that permission does not
    reach here.

    This change creates the table and nothing writes to it, so the constraint is
    stated rather than enforced — the writer inherits it with its own test.
    """

    __tablename__ = "webhook_events"
    __table_args__ = (
        Index(
            "ix_webhook_events_provider_processed_received_at",
            "provider",
            "processed",
            "received_at",
        ),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=True, index=True, default=None
    )
    provider: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error: Mapped[str | None] = mapped_column(default=None)
    # No TimestampMixin: §7.26 declares received_at as the only timestamp.
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
