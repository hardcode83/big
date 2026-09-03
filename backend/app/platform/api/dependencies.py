"""Authorisation dependency for the platform endpoints (`platform-admin-api` R5, R6.1, D6).

One declaration, one permission: every route under `/api/v1/platform/` hangs off
`require(Permission.MANAGE_PLATFORM)`, and `MANAGE_PLATFORM` is held by `SUPER_ADMIN` and
nobody else (see `app/auth/domain/policy.py`). A single named alias keeps the route signature
visibly aligned with the permission it enforces — a future second permission would either
get its own alias here or be a deliberate second declaration in this module, both of which
are diffs a reviewer sees.
"""

from typing import Annotated

from fastapi import Depends

from app.auth.api.dependencies import AuthenticatedRequest, require
from app.auth.domain.policy import Permission

PlatformDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_PLATFORM))
]


__all__ = ["PlatformDep"]
