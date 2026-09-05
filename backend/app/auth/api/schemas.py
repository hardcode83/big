"""Request/response DTOs for the auth endpoints (PRD §23).

No request schema has a `tenant_id` field, deliberately: the effective tenant comes
only from the verified token, so one sent in a body is dropped by Pydantic and never
reaches a use case (R4.1, design D6).
"""

import uuid

from fastapi import Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole

# `auth-session-persistence` design D4. Name and attributes live as a single constant plus
# one helper, deliberately not a separate cookie-attributes module: there is exactly one
# cookie and three callers (login, refresh, logout — sections 2 and 3, not this one).
SESSION_REFRESH_COOKIE = "autohostai.session.refresh"


def emit_refresh_cookie(
    response: Response,
    value: str,
    *,
    secure: bool,
    max_age_seconds: int,
) -> None:
    """Sets the refresh-token cookie with its full, fixed attribute set (design D4).

    The caller passes only the value and the two things that vary per request: whether the
    effective client scheme is HTTPS (`resolve_cookie_secure`, R7.2/R7.3) and the refresh
    token's TTL. Everything else is fixed:

    - `HttpOnly`: the token is never readable from JS, which is the whole point of moving
      it out of memory (R1, R2).
    - `SameSite=Lax`: the only value that still lets a top-level navigation from an email
      link to `/login` carry the cookie back through a `POST`; `Strict` would break
      reload-after-email-link.
    - `Path=/api/v1/auth`: keeps the cookie off every other route — `Path=/` would send it
      on every request, wider than the contract asks for.
    """
    response.set_cookie(
        key=SESSION_REFRESH_COOKIE,
        value=value,
        max_age=max_age_seconds,
        path="/api/v1/auth",
        secure=secure,
        httponly=True,
        samesite="lax",
    )


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class ForgotPasswordRequest(BaseModel):
    """The address to send a recovery link to."""

    # This docstring is the PUBLIC schema description in `backend/openapi.json` and the
    # generated frontend types, so it says what a client needs. Reasoning stays here.
    #
    # No `tenant_id` field, and `extra="forbid"` keeps it that way (R2.3): the tenant is
    # derived from the row `find_by_email_globally` resolves, never from the body. A body that
    # could name a tenant would let the caller supply the scope of an unscoped query, which is
    # the shape design D3 rejects for the token itself.
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)


class ForgotPasswordResponse(BaseModel):
    """The same acknowledgement for every request.

    It does not indicate whether the address belongs to an account.
    """

    # Public description above, reasoning here — the same split `ChangePasswordRequest` uses,
    # and the documentation panel of section 6 was right that this class had not followed it.
    #
    # R2.1/R2.2: one `202` and one text answer an address with an account, one without, an
    # inactive user, an inactive tenant, and an account already holding its quota of live
    # links. Anything that varied would make this an anonymous user-enumerator open to the
    # internet — the reasoning `auth-tenancy` used to make its five login failures identical.
    #
    # A constant, not a field the caller can influence. `Field(default=...)` rather than a
    # bare class attribute so it still appears in the schema and the frontend types.
    detail: str = Field(
        default="If the address belongs to an account, a recovery link has been sent."
    )


class ResetPasswordRequest(BaseModel):
    """The recovery token from the emailed link, and the new password."""

    # Public description above, reasoning here — same split as the other schemas in this file.
    #
    # `extra="forbid"` and no user or tenant field (R3.3, design D3): the token IS the
    # subject. A body that could name an account would let the caller supply the scope of the
    # deliberately unscoped `consume_globally`, which is precisely the shape D3 rejects.
    #
    # Bounds only, never the policy: the rule lives in `app/auth/domain/password_policy.py`
    # and answers `422` naming what it broke (R1.5, reused by R3.1). `max_length` on the token
    # is a denial-of-service bound — it is hashed, so an unbounded body is free CPU for the
    # caller — and 512 is far past `secrets.token_urlsafe(32)`'s 43 characters.
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(BaseModel):
    """The current password and the replacement.

    The account is the one the access token belongs to; this body cannot name a user.
    A new password that breaks the password policy is answered with `422` saying which
    rule it broke.
    """

    # This docstring becomes the PUBLIC description of the schema in `backend/openapi.json`
    # and in the generated frontend types, so it says what a client needs and no more. The
    # reasoning below stays in comments for the same reason.
    #
    # `extra="forbid"` is what keeps the subject unforgeable (R1.4): a body carrying
    # `user_id` or `email` is rejected outright rather than silently ignored, because
    # silent ignoring is how somebody believes they reset another person's password.
    #
    # Bounds only, never the policy. `min_length=1` because an empty string is a malformed
    # request, not a weak password; the real rule lives in
    # `app/auth/domain/password_policy.py` and answers `422` naming the rule it broke
    # (R1.5). Encoding "at least 12" here would put the policy in two places, and the
    # schema's copy would answer with pydantic's message instead of the named rule.
    # `max_length` is a denial-of-service bound — bcrypt is CPU-bound, so an unbounded
    # body is a way to spend our CPU — and matches `LoginRequest.password` above.
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class TokenPairResponse(BaseModel):
    # `refresh_token` is deliberately absent (`auth-session-persistence` R1.2, design D3):
    # the refresh token travels exclusively via the `SESSION_REFRESH_COOKIE` `Set-Cookie`
    # header (`emit_refresh_cookie` above), never in this JSON body. No dual period — see
    # the design's rejected-alternatives note on this point.
    access_token: str
    token_type: str
    expires_in: int


class CurrentUserResponse(BaseModel):
    """Fields are enumerated rather than serialised from the entity.

    `password_hash` lives on `User`, so a `from_attributes` dump would leak it. Also
    omitted: `status`, which is an internal detail the caller does not need (R2.6).
    """

    id: uuid.UUID
    # `None` for `SUPER_ADMIN` (`super-admin-identity` R2.4, design D5): the role has no
    # tenant, and this field is what makes `GET /auth/me` say so instead of 500ing on a
    # non-optional `uuid.UUID` at the API boundary.
    tenant_id: uuid.UUID | None
    name: str
    email: str
    role: UserRole
    preferred_language: str
    # `auth-account-recovery` R5.6. Exposed HERE and nowhere else (open question 3 of the
    # design): the frontend needs it to redirect instead of discovering the state from a
    # `403` on some unrelated call. Deliberately NOT added to `GET /api/v1/users` or
    # `GET /api/v1/users/{id}`, which would widen the contract past what any requirement
    # asks for.
    must_change_password: bool

    @classmethod
    def from_domain(cls, user: User) -> "CurrentUserResponse":
        return cls(
            id=user.id,
            tenant_id=user.tenant_id,
            name=user.name,
            email=user.email,
            role=user.role,
            preferred_language=user.preferred_language,
            must_change_password=user.must_change_password,
        )
