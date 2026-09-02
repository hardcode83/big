import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Uuid,
    column,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """`tenant_id` is nullable (`super-admin-identity` R1.1, design D1).

    Does NOT use `TenantScopedMixin`, which hard-codes `nullable=False` — the column is
    declared by hand instead, mirroring `WebhookEventModel`
    (`app/integrations/infrastructure/models.py`), the one other table with a nullable
    `tenant_id`. `tenant_scoped_classes()` (`app/core/db.py`) selects by column presence,
    not by mixin, so `users` stays inside the global tenant filter: a session marked with
    a tenant still only sees that tenant's users, exactly as before. Only a `SUPER_ADMIN`
    row — the one with `tenant_id IS NULL` — is reachable from an unmarked session, the
    same mechanism that already protects `webhook_events`.

    `ck_users_super_admin_tenant_id_null` holds the OTHER half of R1 (R1.2): relaxing the
    column relaxes it for every role, not only `SUPER_ADMIN`'s, and nothing else in this
    entity or its repository enforces that only `SUPER_ADMIN` may have a null tenant —
    found by the review panel of `super-admin-identity`. Without it, a
    `TENANT_OWNER`/`PROPERTY_MANAGER`/`CLEANER`/`TECHNICIAN` row that ever acquired
    `tenant_id IS NULL` would authenticate with its session left unmarked by
    `get_authenticated_request` (which keys that decision on `tenant_id` nullity, not on
    `role`) while still holding that role's full operational permissions — the same
    unmarked state R3 scopes to `SUPER_ADMIN` alone.
    """

    __tablename__ = "users"
    __table_args__ = (
        # A normalised email identifies ONE user in the whole installation, not one
        # per tenant (design D16, ADR 0005). This deviates from PRD §7.3, which
        # specifies UNIQUE(tenant_id, email): with login by email only and no tenant
        # discriminator, per-tenant uniqueness means the address does not identify the
        # account, and creating a user in tenant B with the address of tenant A's owner
        # locks that owner out of a product with no unlock endpoint.
        #
        # `lower(email)` rather than `email` because the lookup is case-insensitive:
        # a case-sensitive constraint would let `Jose@x.com` and `jose@x.com` coexist
        # and both then resolve to the same login (design D19).
        #
        # No UNIQUE(tenant_id, email) alongside it — global uniqueness already implies
        # it, and two constraints for one rule is how they drift apart.
        Index("uq_users_lower_email", func.lower(column("email")), unique=True),
        Index("ix_users_tenant_id_role", "tenant_id", "role"),
        Index("ix_users_tenant_id_status", "tenant_id", "status"),
        CheckConstraint(
            "(role = 'SUPER_ADMIN') = (tenant_id IS NULL)",
            name="ck_users_super_admin_tenant_id_null",
        ),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role", native_enum=True))
    phone: Mapped[str | None] = mapped_column(String(30), default=None)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", native_enum=True),
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    preferred_language: Mapped[str] = mapped_column(String(5), default="es", server_default="es")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # `auth-account-recovery` R5.1. `server_default false` so the migration needs no backfill:
    # existing accounts keep today's behaviour, because a deployment must not lock anybody out.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )


class UserSessionModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Server-side state of one refresh token (design D5).

    The primary key is the refresh token's `jti`, so the token is never stored.
    Not part of the PRD §7 entity list: PRD §22 requires refresh token rotation
    without saying where the state lives, and rotation, reuse detection and logout
    are all impossible without durable server-side state.

    `tenant_id` is nullable (`super-admin-identity` R1.1, R2, design D1), the same shape
    as `UserModel` above and for the same reason: a `SUPER_ADMIN` login persists a
    session row with no tenant to attribute it to. Not `TenantScopedMixin` — declared by
    hand, mirroring `WebhookEventModel`.
    """

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_tenant_id_user_id", "tenant_id", "user_id"),
        Index("ix_user_sessions_family_id", "family_id"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user_sessions.id"), default=None
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_reason: Mapped[SessionRevokedReason | None] = mapped_column(
        Enum(SessionRevokedReason, name="session_revoked_reason", native_enum=True), default=None
    )


class PasswordResetTokenModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """One recovery link's server-side state (`auth-account-recovery` R3.1, design D1).

    Not part of the PRD §7 entity list: PRD §24 lists `/forgot-password` without saying where
    the token lives, and single use is impossible without durable server-side state — the same
    reasoning that put `user_sessions` here.

    Tenant-scoped like everything else, so the global filter of `app/core/db.py` covers it.
    That matters even though the consuming query is deliberately unscoped (design D3): the
    unscoped lookup is one named method, and every OTHER access to this table is caught by the
    net.
    """

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        # UNIQUE, not merely indexed. It is what makes the conditional `UPDATE ... WHERE
        # token_hash = :h` of design D1 address at most one row, so `rowcount` is a decision
        # and not a count. A duplicate digest would mean two tokens sharing a fate.
        Index("uq_password_reset_tokens_token_hash", "token_hash", unique=True),
        # Serves `count_live` (the per-account cap of design D7) and `revoke_other_live`.
        Index("ix_password_reset_tokens_tenant_id_user_id", "tenant_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    # SHA-256 in hexadecimal: 64 characters, fixed. The cleartext token is NEVER stored —
    # R4.1 requires that the row not permit reconstructing it.
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
