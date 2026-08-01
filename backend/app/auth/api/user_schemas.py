"""Request/response DTOs of the user-administration endpoints (PRD §23, R1, R2, R3, R4).

Three rules this module exists to enforce:

* **No request schema has a `tenant_id`** — the effective tenant comes only from the verified
  token (R1.3), so one sent in a body is rejected by `extra="forbid"` and never reaches a use
  case.
* **The temporary password lives in its own response types.** `UserResponse` structurally has
  no such field, so it cannot leak into a listing or a detail by somebody adding an optional
  attribute "just in case" (design D10). A `str | None` on one shared model is precisely the
  shape that ends up populated by accident.
* **`password_hash` is never serialised.** Response fields are enumerated, never dumped from
  the entity, for the same reason `reservations` enumerates its own (R2.5).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth.application.user_admin import PATCHABLE
from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.repositories import MAX_PAGE, MAX_PER_PAGE

# Column widths of `users` (app/auth/infrastructure/models.py). Bounded here so an oversized
# value is a `422` in the PRD §23 envelope rather than a driver error mid-transaction — the
# same reasoning `reservations` applies to its CSV columns.
MAX_NAME = 200
MAX_EMAIL = 255
MAX_PHONE = 30

LANGUAGES = ("es", "en")

# Deliberately a pattern and NOT pydantic's `EmailStr`. `EmailStr` needs the
# `email-validator` package, and a new dependency is a review trigger in
# `steering/security.md` ("dependencias nuevas") — `auth-tenancy` already types the login
# address as a bounded `str` (`app/auth/api/schemas.py`), so this follows the codebase instead
# of introducing a package for one admin field.
#
# `ASSUMPTION`: this is not RFC 5322. It catches the mistakes that actually happen
# when somebody types a colleague's address — no `@`, whitespace, a domain with no dot, a
# trailing dot — and accepts some addresses a strict validator would reject. It cannot be the
# thing that decides whether mail is deliverable; nothing here can. What protects the tenant
# from a typo is the reset endpoint (R4), not this regex.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$"

# `SUPER_ADMIN` is refused at the schema boundary as well as in the entity (R1.6). Two layers
# on purpose: the entity is the invariant, and this turns it into a `422` that names the field
# instead of an error the client has to interpret.
ASSIGNABLE_ROLES = tuple(role for role in UserRole if role is not UserRole.SUPER_ADMIN)

# The only nullable column of `users` a caller may clear. Everything else is NOT NULL, so
# sending `null` for it is a `422` and not a write — see `_reject_explicit_nulls`.
NULLABLE_FIELDS = frozenset({"phone"})


def _reject_super_admin(value: UserRole) -> UserRole:
    if value is UserRole.SUPER_ADMIN:
        raise ValueError(
            "SUPER_ADMIN cannot be assigned through the API: its powers in PRD §6 are global, "
            "not the operation of one tenant"
        )
    return value


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
    email: Annotated[str, Field(min_length=3, max_length=MAX_EMAIL, pattern=EMAIL_PATTERN)]
    role: UserRole
    phone: Annotated[str | None, Field(default=None, max_length=MAX_PHONE)] = None
    preferred_language: Annotated[str, Field(pattern=r"^(es|en)$")] = "es"

    _check_role = field_validator("role")(_reject_super_admin)


class UpdateUserRequest(BaseModel):
    """Every field optional; only those present are applied (R3.1).

    `model_fields_set` is what distinguishes "not sent" from "sent as null", so a caller can
    clear `phone` by sending `null` without every other unsent field being treated as a clear
    — the same distinction `reservations` draws in its own PATCH schema.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(default=None, min_length=1, max_length=MAX_NAME)] = None
    email: Annotated[
        str | None,
        Field(default=None, min_length=3, max_length=MAX_EMAIL, pattern=EMAIL_PATTERN),
    ] = None
    phone: Annotated[str | None, Field(default=None, max_length=MAX_PHONE)] = None
    preferred_language: Annotated[str | None, Field(default=None, pattern=r"^(es|en)$")] = None
    role: UserRole | None = None
    status: UserStatus | None = None

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: UserRole | None) -> UserRole | None:
        return None if value is None else _reject_super_admin(value)

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "UpdateUserRequest":
        """`null` is only a legal value for the columns that are actually nullable.

        Every field here is `X | None` because `None` is how "not sent" is spelled, but that is
        NOT the same as the caller sending `null` — and `model_fields_set` cannot tell them
        apart once they reach `changes()`. The security panel of sections 2-6 showed what that
        costs: `PATCH {"email": null}` answered `200` and wrote the literal string `"none"` into
        the login identity, locking the account out of a product whose identity IS its email
        (ADR 0005); `{"status": null}` reached the database and came back as an unmapped `500`.

        Only `phone` is nullable in `users`, so only `phone` may be cleared.
        """
        sent_nulls = {
            field
            for field in self.model_fields_set
            if field not in NULLABLE_FIELDS and getattr(self, field) is None
        }
        if sent_nulls:
            raise ValueError(
                f"{', '.join(sorted(sent_nulls))} cannot be null; only "
                f"{', '.join(sorted(NULLABLE_FIELDS))} can be cleared"
            )
        return self

    def changes(self) -> dict[str, Any]:
        """Only the fields the caller actually sent.

        The set of patchable fields is imported from `application/`, not restated here: two
        copies of one rule is how they drift, and the architecture review of sections 2-6 caught
        this file having its own (identical, for now) list.
        """
        return {
            field: getattr(self, field)
            for field in self.model_fields_set
            if field in PATCHABLE
        }


class UserResponse(BaseModel):
    """One user. Structurally without `password_hash` and without any temporary password."""

    id: uuid.UUID
    name: str
    email: str
    role: UserRole
    status: UserStatus
    phone: str | None
    preferred_language: str
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            status=user.status,
            phone=user.phone,
            preferred_language=user.preferred_language,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class UserPageResponse(BaseModel):
    """The pagination envelope of PRD §23."""

    data: list[UserResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

    @classmethod
    def build(
        cls, users: tuple[User, ...], *, total: int, page: int, per_page: int
    ) -> "UserPageResponse":
        return cls(
            data=[UserResponse.from_domain(user) for user in users],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page if per_page else 0,
        )


class CreatedUserResponse(BaseModel):
    """A separate type, and the only shape that carries the one-time secret (design D10).

    Returned by `POST /users` and `POST /users/{id}/reset-password`, both with
    `Cache-Control: no-store`. It is never reachable from a `GET`.
    """

    user: UserResponse
    temporary_password: str

    @classmethod
    def build(cls, user: User, temporary_password: str) -> "CreatedUserResponse":
        return cls(
            user=UserResponse.from_domain(user), temporary_password=temporary_password
        )


# Re-exported so the router declares its query bounds from the same constants the domain uses.
__all__ = [
    "MAX_PAGE",
    "MAX_PER_PAGE",
    "ASSIGNABLE_ROLES",
    "CreateUserRequest",
    "CreatedUserResponse",
    "UpdateUserRequest",
    "UserPageResponse",
    "UserResponse",
]
