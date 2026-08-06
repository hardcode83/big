import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope

pms_provider_enum = Enum(PMSProvider, name="pms_provider", native_enum=True)
"""Shared: used by `pms_credentials.provider` AND `properties.pms_provider`.

A module-level object rather than two inline `Enum(...)` calls, following
`properties/infrastructure/models.py`, so both columns reference one Postgres type instead of
SQLAlchemy trying to create it twice.
"""


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

    **`payload` and `error` are cleartext sinks fed by an external party.** Structured
    form, per rule 11 of steering/security.md — and the most exposed of the six, since
    PRD §16 has the provider POST this body and §7.26 has it persisted verbatim, so a
    PMS check-in event carrying `document_number` lands here by default rather than by
    mistake. `error` must never echo the raw body back: that would reintroduce through
    the text column what `payload` just dropped.

    Nothing writes here yet; `reservations-webhooks` inherits the contract with its own
    test. Do not restate rule 11 here.
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


class PmsCredentialModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """Provider credentials, encrypted, at the three granularities of ADR 0006 decision 7.

    **Its own table, not columns on `properties`.** The ADR's literal sentence says the latter,
    and its own next paragraph contradicts it — correctly, because the measurement does: Beds24's
    real credential is an **account** refresh token, Channex's an account API key, and the only
    per-property credential Beds24 has is the Arrivals API access key, which belongs to the
    access layer the ADR defers in decision 5. Columns on `properties` would store one account
    secret once per row: N places to rotate, and a partial rotation leaving some properties
    authenticating with a dead token.

    There is also a mechanical reason that is not negotiable: `AuditLog.entity_id` is a required
    UUID, and R4.2 obliges auditing the read and rotation of a credential. A credential spread
    across columns of `properties` has no id of its own to name, so the audit row would have to
    point at the property and pretend that is the entity that was read. As a row, it has one.

    `TenantScopedMixin`, so it joins `tenant_scoped_classes()` and the global filter — pinned by
    its own test, because a scoping failure here does not disclose data, it grants **write**
    access to another client's calendar, pricing and messaging (rule 1, and the reason ADR 0006
    demands a dedicated isolation test rather than the module's generic one).
    """

    __tablename__ = "pms_credentials"
    __table_args__ = (
        # One credential per (tenant, provider, scope, property). `property_id` is NULL for the
        # account and organization scopes; Postgres treats NULLs as distinct in a UNIQUE index,
        # so this does NOT prevent two account-scope rows for the same provider. That gap is
        # closed by the partial index below, which is the only way to say "at most one".
        UniqueConstraint(
            "tenant_id",
            "provider",
            "scope",
            "property_id",
            name="uq_pms_credentials_tenant_provider_scope_property",
        ),
        # `property_id` is set EXACTLY when the scope is PROPERTY. Without this, a mis-scoped
        # ACCOUNT row carrying a `property_id` slips past the partial index below (whose
        # predicate is `property_id IS NULL`), and then survives every rotation — because
        # rotation writes the `property_id IS NULL` coordinates, leaving the old account token
        # at rest, decryptable, in a row nobody reads. Reproduced by the security panel.
        CheckConstraint(
            "(scope = 'PROPERTY') = (property_id IS NOT NULL)",
            name="ck_pms_credentials_property_id_matches_scope",
        ),
        Index(
            "uq_pms_credentials_account_scope",
            "tenant_id",
            "provider",
            "scope",
            unique=True,
            postgresql_where=text("property_id IS NULL"),
        ),
    )

    provider: Mapped[PMSProvider] = mapped_column(pms_provider_enum)
    scope: Mapped[PmsCredentialScope] = mapped_column(
        Enum(PmsCredentialScope, name="pms_credential_scope", native_enum=True)
    )
    # NULL for ACCOUNT and ORGANIZATION. `ON DELETE CASCADE`: a deleted property must not leave
    # its credential behind, orphaned and still decryptable.
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=True, default=None
    )
    # Fernet ciphertext, from the migration that creates the column — R3.1 admits no
    # intermediate state where this accepts plaintext. Never returned by any API response,
    # not even masked (rule 3(a)); there is no Property endpoint today, and this column is a
    # reason not to add one carelessly.
    secret_encrypted: Mapped[str] = mapped_column(Text)
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
