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
    rule: it is the *stored* preference of the authenticated user, read off the user row,
    not `Accept-Language`. It has no default on purpose — every construction site states
    the language, so no future endpoint answers in Spanish because someone forgot.

    **It is not the language the answer is painted in.** The two came apart in
    `frontend-verification-fixes` (design D3): the interface states its active language per
    request in the `X-Locale` header, and what a route renders composed text in is that,
    falling back to this column and then to `es`. That resolution lives in
    `RequestLocaleDep` (`app/auth/api/dependencies.py`) and stays there precisely so the
    "never from request input" rule above keeps holding literally for this object — a
    header value has no business inside the carrier tenant isolation rests on. So a route
    composing user-facing text wants `RequestLocaleDep`; this field is the stored
    preference, and reading it to render is the mistake a structural guard in
    `tests/test_layering.py` now fails on.

    PRD:205 ("idioma del dashboard: preferencia del usuario autenticado") is where the
    original reading came from, and it is superseded on this point rather than wrong: the
    stored preference is still what decides the language when the request states none, so
    it remains the answer for any caller that is not our interface.
    """

    user_id: uuid.UUID
    # `None` for a `SUPER_ADMIN` request only (`super-admin-identity` R2.2, design D2): the
    # role has no tenant to act on. `user_id` stays strictly a `uuid.UUID` — a `SUPER_ADMIN`
    # always has an identity, just not a tenant.
    tenant_id: uuid.UUID | None
    role: UserRole
    preferred_language: Locale

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, uuid.UUID):
            raise ValueError("user_id must be a UUID")
        if self.tenant_id is not None and not isinstance(self.tenant_id, uuid.UUID):
            raise ValueError("tenant_id must be a UUID or None")
        if not isinstance(self.role, UserRole):
            raise ValueError("role must be a UserRole")
        if not isinstance(self.preferred_language, Locale):
            raise ValueError("preferred_language must be a Locale")
