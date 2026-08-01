import uuid
from dataclasses import dataclass
from datetime import datetime

from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus


@dataclass
class User:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    email: str
    password_hash: str
    role: UserRole
    created_at: datetime
    updated_at: datetime
    phone: str | None = None
    status: UserStatus = UserStatus.ACTIVE
    preferred_language: str = "es"
    last_login_at: datetime | None = None


@dataclass
class UserSession:
    """One refresh token's server-side state (R2.1, R2.2, design D5).

    The `id` is the refresh token's `jti`, so the token itself is never stored:
    its signature proves authenticity and this row carries the state. Sessions
    rotated from one another share a `family_id`, which is what makes revoking a
    whole lineage possible when a used token is presented again.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    family_id: uuid.UUID
    expires_at: datetime
    parent_id: uuid.UUID | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_reason: SessionRevokedReason | None = None

    def __post_init__(self) -> None:
        _require_aware(self.expires_at, "expires_at")

    def is_usable(self, now: datetime) -> bool:
        _require_aware(now, "now")
        return self.used_at is None and self.revoked_at is None and self.expires_at > now

    def rotate(self, new_id: uuid.UUID, expires_at: datetime, now: datetime) -> "UserSession":
        """Consume this session and return its replacement in the same family."""
        if not self.is_usable(now):
            raise ValueError("Cannot rotate a session that is used, revoked or expired")
        self.used_at = now
        return UserSession(
            id=new_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            family_id=self.family_id,
            expires_at=expires_at,
            parent_id=self.id,
        )

    def revoke(self, reason: SessionRevokedReason, now: datetime) -> None:
        _require_aware(now, "now")
        if self.revoked_at is not None:
            return
        self.revoked_at = now
        self.revoked_reason = reason


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
