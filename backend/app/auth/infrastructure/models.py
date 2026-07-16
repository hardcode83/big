from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.domain.enums import UserRole, UserStatus
from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_id_email"),
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
