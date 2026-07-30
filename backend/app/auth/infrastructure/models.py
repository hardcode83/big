import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Uuid,
    column,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
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


class UserSessionModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """Server-side state of one refresh token (design D5).

    The primary key is the refresh token's `jti`, so the token is never stored.
    Not part of the PRD §7 entity list: PRD §22 requires refresh token rotation
    without saying where the state lives, and rotation, reuse detection and logout
    are all impossible without durable server-side state.
    """

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_tenant_id_user_id", "tenant_id", "user_id"),
        Index("ix_user_sessions_family_id", "family_id"),
        Index("ix_user_sessions_expires_at", "expires_at"),
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
