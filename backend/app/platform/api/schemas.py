"""Request/response DTOs of the platform endpoints (`platform-admin-api` R1, R3, design D5).

Two routes, four types. The bodies are short because the contracts of PRD §23 are: a tenant
gets a single nested resource, and a user-creation response carries the one-time secret
exactly once (the same shape `auth-account-recovery` already publishes via `CreatedUserResponse`).

`model_config = ConfigDict(from_attributes=True, extra="forbid")` on every type, because:

* `from_attributes=True` lets the response mappers read fields off the domain entities without
  hand-written shims for each one — `TenantResponse.from_settings` (in `app.tenants.api.schemas`,
  reused here for the platform mapper) is shared by both routers, so the change has one mapper.
* `extra="forbid"` is the project's standing rule: a caller that adds a field gets a `422`
  naming it, rather than the field silently being ignored — the same shape
  `UpdateTenantRequest` and `CreateUserRequest` apply to their own bodies.

`EmailStr` (Pydantic's `EmailStr`) is used rather than the `EMAIL_PATTERN` regex the
`auth-account-recovery` endpoints use. The pattern there was a deliberate choice to avoid
the `email-validator` dependency, but `EmailStr` is the explicit type the task names for the
platform surface, and the operator typing in an installation's billing address is exactly
where the stricter check earns its dependency.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.auth.api.user_schemas import MAX_PHONE
from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus

MAX_NAME = 200
MAX_COUNTRY = 2
MAX_TIMEZONE = 50


class CreateTenantRequest(BaseModel):
    """What `POST /api/v1/platform/tenants` accepts (R1.1, R1.3).

    The five fields are the same ones `Tenant.update` accepts on a PATCH — reusing them keeps
    the boundary `Tenant` enforces ("every guard is the same function `update` uses", design
    D2). No `status`: a tenant is born ACTIVE.

    `name` requires `min_length=1` so an empty string is a `422` naming the field, not a
    row created from a blank value (R1.3).
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME)
    billing_email: EmailStr
    country: str = Field(min_length=MAX_COUNTRY, max_length=MAX_COUNTRY)
    timezone: str = Field(max_length=MAX_TIMEZONE)
    default_language: Literal["es", "en"] = "es"


# `TenantResponse` and `TenantConfigResponse` are imported lazily here rather than redeclared:
# the platform mapper needs the same response shape the tenants router returns for the GET path,
# and the configuration row travels nested (PRD §23, `app.tenants.api.schemas`). Re-declaring
# would fork the type, which is the trap `_AuditWriter` was created to close for audit rows.
from app.tenants.api.schemas import TenantConfigResponse, TenantResponse  # noqa: E402


def _reject_super_admin(value: UserRole) -> UserRole:
    """The platform endpoint never issues `SUPER_ADMIN` (R3.5).

    Two layers on purpose: the entity's `GRANTABLE_ROLES` is the invariant, and this turns
    it into a `422` that names the field instead of an error the client has to interpret.
    Same shape `_reject_super_admin` in `app/auth/api/user_schemas.py` follows for the
    tenants-scoped surface.
    """
    if value is UserRole.SUPER_ADMIN:
        raise ValueError(
            "SUPER_ADMIN cannot be assigned through the API: its powers in PRD §6 are global, "
            "not the operation of one tenant"
        )
    return value


class CreatePlatformUserRequest(BaseModel):
    """What `POST /api/v1/platform/tenants/{tenant_id}/users` accepts (R3.1, R3.5, R3.6).

    The body is the same shape the tenants-scoped `CreateUserRequest` uses, minus the fields
    the platform operator never sees: no `tenant_id` (it comes from the path), no
    `preferred_language` (the tenant's `default_language` decides — `CreateUserInTenantUseCase`
    threads it through). `phone` is kept optional so the optional-`null` semantics the user
    module enforces are reused verbatim.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    email: EmailStr
    # `min_length=1` for the same reason `CreateTenantRequest.name` carries it: an empty
    # string has to be a 422 naming the field, not a row created from a blank value
    # (R1.3/R3.6). `phone` is bounded by the very constant the route this body mirrors
    # uses (`CreateUserRequest`, `app.auth.api.user_schemas`) — R4.3 asks for the same
    # validation, and an unbounded string was not it.
    full_name: str = Field(min_length=1, max_length=MAX_NAME)
    phone: str | None = Field(default=None, max_length=MAX_PHONE)
    role: UserRole

    _check_role = field_validator("role")(_reject_super_admin)


class PlatformUserResponse(BaseModel):
    """The user shape the platform endpoint returns (R3.1).

    A separate type from `auth.UserResponse` for one reason: this one carries `tenant_id`.
    The tenants-scoped endpoints derive `tenant_id` from the token, so it would always equal
    the caller's own — printing it would be a no-op — and `UserResponse` deliberately omits
    it. The platform operator names the tenant in the path, so the response has to echo it
    back; this type is the visible diff that declares that.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    tenant_id: uuid.UUID | None
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
    def from_domain(cls, user: User) -> "PlatformUserResponse":
        return cls(
            id=user.id,
            tenant_id=user.tenant_id,
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


class CreatedPlatformUserResponse(BaseModel):
    """The user plus the one-time secret (`platform-admin-api` R3.1, design D10).

    Two-shape separation, the same rule `CreatedUserResponse` follows: the temporary password
    lives on this type and not on `PlatformUserResponse`, so it cannot leak into a listing or
    a detail by somebody adding an optional attribute "just in case".
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    user: PlatformUserResponse
    temporary_password: str

    @classmethod
    def build(cls, user: User, temporary_password: str) -> "CreatedPlatformUserResponse":
        return cls(
            user=PlatformUserResponse.from_domain(user),
            temporary_password=temporary_password,
        )


__all__ = [
    "CreateTenantRequest",
    "CreatePlatformUserRequest",
    "CreatedPlatformUserResponse",
    "PlatformUserResponse",
    "TenantConfigResponse",
    "TenantResponse",
]
