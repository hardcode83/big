import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
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
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_id_email"),
        # Backstop for design D19: `normalize_email` lowercases on every write, but a
        # future writer that forgets would let two case variants coexist in one tenant,
        # and D16's "exactly one match" rule would then lock BOTH accounts out for good.
        # This makes the invariant structural instead of a convention.
        Index(
            "uq_users_tenant_id_lower_email",
            "tenant_id",
            func.lower(column("email")),
            unique=True,
        ),
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
