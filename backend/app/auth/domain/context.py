import uuid
from dataclasses import dataclass

from app.auth.domain.enums import UserRole


@dataclass(frozen=True)
class RequestContext:
    """Who is acting, and on which tenant (R4.1, design D6).

    The only carrier of the effective tenant. It is built from verified token
    claims plus the current database state, never from request input — a
    `tenant_id` in a body, query string or header must not reach this object.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: UserRole

    def __post_init__(self) -> None:
        for field_name in ("user_id", "tenant_id"):
            if not isinstance(getattr(self, field_name), uuid.UUID):
                raise ValueError(f"{field_name} must be a UUID")
        if not isinstance(self.role, UserRole):
            raise ValueError("role must be a UserRole")
