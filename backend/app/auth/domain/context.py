import uuid
from dataclasses import dataclass

from app.auth.domain.enums import UserRole
from app.core.i18n import Locale


@dataclass(frozen=True)
class RequestContext:
    """Who is acting, on which tenant, and in which language (R4.1, design D6).

    The only carrier of the effective tenant. It is built from verified token
    claims plus the current database state, never from request input — a
    `tenant_id` in a body, query string or header must not reach this object.

    `preferred_language` joined it in `dashboard-api` (its design D3) and follows the same
    rule: it is the *stored* preference of the authenticated user, not `Accept-Language`.
    PRD:205 says "idioma del dashboard: preferencia del usuario autenticado", which is the
    row and not the browser. It has no default on purpose — every construction site states
    the language, so no future endpoint answers in Spanish because someone forgot.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: UserRole
    preferred_language: Locale

    def __post_init__(self) -> None:
        for field_name in ("user_id", "tenant_id"):
            if not isinstance(getattr(self, field_name), uuid.UUID):
                raise ValueError(f"{field_name} must be a UUID")
        if not isinstance(self.role, UserRole):
            raise ValueError("role must be a UserRole")
        if not isinstance(self.preferred_language, Locale):
            raise ValueError("preferred_language must be a Locale")
