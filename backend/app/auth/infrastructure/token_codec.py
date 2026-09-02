"""PyJWT adapter for the TokenCodec port (R1.5, R1.6, R2.5, design D3).

HS256 is pinned in code, never configurable, and `algorithms=` is always passed
explicitly on decode — that is what makes an `alg: none` token unusable.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.auth.domain.enums import UserRole
from app.auth.domain.exceptions import InvalidTokenError, TokenTypeMismatchError
from app.auth.domain.value_objects import AccessTokenClaims, RefreshTokenClaims
from app.core.config import JWT_ALGORITHM

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


class JwtTokenCodec:
    def __init__(self, secret: str, access_minutes: int, refresh_days: int) -> None:
        self._secret = secret
        self._access_ttl = timedelta(minutes=access_minutes)
        self._refresh_ttl = timedelta(days=refresh_days)

    @property
    def access_ttl_seconds(self) -> int:
        return int(self._access_ttl.total_seconds())

    @property
    def refresh_ttl(self) -> timedelta:
        return self._refresh_ttl

    def issue_access(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        role: UserRole,
        family_id: uuid.UUID,
        now: datetime,
    ) -> str:
        return self._encode(
            self._base_claims(user_id, tenant_id, role, now, self._access_ttl)
            | {
                "type": ACCESS_TOKEN_TYPE,
                "jti": str(uuid.uuid4()),
                # Carried so logout can revoke this session's family (design D18).
                "fam": str(family_id),
            }
        )

    def issue_refresh(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        role: UserRole,
        session_id: uuid.UUID,
        family_id: uuid.UUID,
        now: datetime,
    ) -> str:
        return self._encode(
            self._base_claims(user_id, tenant_id, role, now, self._refresh_ttl)
            | {
                "type": REFRESH_TOKEN_TYPE,
                # The jti IS the user_sessions row id (design D5).
                "jti": str(session_id),
                "fam": str(family_id),
            }
        )

    def decode_access(self, token: str) -> AccessTokenClaims:
        claims = self._decode(token, ACCESS_TOKEN_TYPE)
        return AccessTokenClaims(
            user_id=_uuid_claim(claims, "sub"),
            tenant_id=_optional_uuid_claim(claims, "tenant_id"),
            role=_role_claim(claims),
            token_id=_uuid_claim(claims, "jti"),
            family_id=_uuid_claim(claims, "fam"),
            issued_at=_time_claim(claims, "iat"),
            expires_at=_time_claim(claims, "exp"),
        )

    def decode_refresh(self, token: str) -> RefreshTokenClaims:
        claims = self._decode(token, REFRESH_TOKEN_TYPE)
        return RefreshTokenClaims(
            user_id=_uuid_claim(claims, "sub"),
            tenant_id=_optional_uuid_claim(claims, "tenant_id"),
            role=_role_claim(claims),
            token_id=_uuid_claim(claims, "jti"),
            family_id=_uuid_claim(claims, "fam"),
            issued_at=_time_claim(claims, "iat"),
            expires_at=_time_claim(claims, "exp"),
        )

    def _base_claims(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        role: UserRole,
        now: datetime,
        ttl: timedelta,
    ) -> dict[str, Any]:
        return {
            "sub": str(user_id),
            # `SUPER_ADMIN` carries no tenant (`super-admin-identity` R2.1, design D4): the
            # claim key stays present so a reader sees "null", not "absent" — NOT because
            # PyJWT's `require=[...]` below demands it (it does not; `tenant_id` is
            # deliberately excluded from that list, see `_decode`).
            "tenant_id": str(tenant_id) if tenant_id is not None else None,
            "role": role.value,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
        }

    def _encode(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._secret, algorithm=JWT_ALGORITHM)

    def _decode(self, token: str, expected_type: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                # `tenant_id` is deliberately NOT in `require` (`super-admin-identity` D4,
                # amended): PyJWT's `_validate_required_claims` tests `payload.get(claim) is
                # None`, so it cannot tell "key absent" from "key present with value null" —
                # it would reject every SUPER_ADMIN token as malformed. Dropping it DOES
                # widen what decodes: a token whose payload omits the key entirely — before,
                # rejected outright by `require` — now decodes via `_optional_uuid_claim`
                # below as `tenant_id=None`. That is safe for reasons this exclusion does not
                # itself provide: minting any token still needs the HS256 signing secret, and
                # the resulting identity is re-validated against the database on every
                # request (`get_active_by_id(tenant_id, user_id)`).
                options={"require": ["sub", "role", "type", "jti", "fam", "iat", "exp"]},
            )
        except jwt.InvalidTokenError as exc:
            # Covers expired, bad signature, malformed, alg mismatch and missing
            # required claims. The message stays generic: the caller gets 401.
            raise InvalidTokenError("Token is not valid") from exc
        except (TypeError, ValueError) as exc:
            # PyJWT's own iat/exp validation does `int(payload[claim])` catching only
            # ValueError, so an `exp` that is a JSON object or array raises TypeError
            # from inside jwt.decode — which would escape as a 500 where R2.5
            # requires a 401.
            raise InvalidTokenError("Token is not valid") from exc

        if claims.get("type") != expected_type:
            raise TokenTypeMismatchError(f"Expected a {expected_type} token")
        return claims


def _uuid_claim(claims: dict[str, Any], name: str) -> uuid.UUID:
    value = claims.get(name)
    # The isinstance check is load-bearing: uuid.UUID(123) raises AttributeError,
    # which would escape as a 500 instead of the 401 R2.5 demands for a malformed
    # token. PyJWT type-checks `sub` and `jti` but not our own claims.
    if not isinstance(value, str):
        raise InvalidTokenError(f"Claim {name} is not a valid identifier")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise InvalidTokenError(f"Claim {name} is not a valid identifier") from exc


def _optional_uuid_claim(claims: dict[str, Any], name: str) -> uuid.UUID | None:
    """Like `_uuid_claim`, except JSON `null` is a legitimate value (`tenant_id` only).

    Used only for `tenant_id`: `user_id`, `role`, `jti` and `fam` can never legitimately
    be absent, so they keep the strict `_uuid_claim`/`_role_claim` (`super-admin-identity`
    design D4).
    """
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidTokenError(f"Claim {name} is not a valid identifier")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise InvalidTokenError(f"Claim {name} is not a valid identifier") from exc


def _role_claim(claims: dict[str, Any]) -> UserRole:
    try:
        return UserRole(claims["role"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("Claim role is not a known role") from exc


def _time_claim(claims: dict[str, Any], name: str) -> datetime:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidTokenError(f"Claim {name} is not a valid timestamp")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (ValueError, OSError, OverflowError) as exc:
        # An out-of-range exp (e.g. 10**20) raises OverflowError, which would
        # otherwise escape as a 500 rather than the 401 of R2.5.
        raise InvalidTokenError(f"Claim {name} is not a valid timestamp") from exc
