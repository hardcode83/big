"""Request/response DTOs for the auth endpoints (PRD §23).

No request schema has a `tenant_id` field, deliberately: the effective tenant comes
only from the verified token, so one sent in a body is dropped by Pydantic and never
reaches a use case (R4.1, design D6).
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class CurrentUserResponse(BaseModel):
    """Fields are enumerated rather than serialised from the entity.

    `password_hash` lives on `User`, so a `from_attributes` dump would leak it. Also
    omitted: `status`, which is an internal detail the caller does not need (R2.6).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    email: str
    role: UserRole
    preferred_language: str

    @classmethod
    def from_domain(cls, user: User) -> "CurrentUserResponse":
        return cls(
            id=user.id,
            tenant_id=user.tenant_id,
            name=user.name,
            email=user.email,
            role=user.role,
            preferred_language=user.preferred_language,
        )
