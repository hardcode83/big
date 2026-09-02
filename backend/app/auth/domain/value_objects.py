import uuid
from dataclasses import dataclass
from datetime import datetime

from app.auth.domain.enums import UserRole


def normalize_email(value: str) -> str:
    """The single definition of "the same email address".

    Normalisation happens in Python on BOTH write and read, and the SQL comparison
    is then a plain equality — never `lower()` in the query. That matters: Postgres
    and Python do not agree on case folding (Postgres `lower('İ')` is one character,
    Python `'İ'.lower()` is two), so folding on one side and storing raw on the other
    would let two rows that the lookup considers identical coexist in one tenant,
    and both accounts would then fail login forever on D16's "exactly one" rule.
    """
    return value.strip().lower()


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    # `None` for a `SUPER_ADMIN` token (`super-admin-identity` R2.1, design D2/D4): the
    # claim key is always present in the JWT payload, its value is `null`.
    tenant_id: uuid.UUID | None
    role: UserRole
    token_id: uuid.UUID
    # The refresh family this access token was issued alongside (design D18).
    # Without it logout could not satisfy R2.3: the endpoint authenticates with the
    # access token, whose own jti is random and links to no session.
    family_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class RefreshTokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: UserRole
    token_id: uuid.UUID
    family_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"
