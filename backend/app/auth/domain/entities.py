import uuid
from dataclasses import dataclass
from datetime import datetime

from app.auth.domain.enums import UserRole, UserStatus


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
