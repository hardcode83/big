"""Maps platform domain errors onto the PRD §23 envelope (`platform-admin-api` R1.4, R3.3).

Two entries — neither one of them catches the `PlatformDomainError` base. The base exists
so a future handler can match the family with one clause; today the table is explicit and
stays explicit, because a match-the-base fallback would silently absorb whatever new
subclass a future change adds without a matching row. Adding a new error means a new entry
here, a diff a reviewer sees.

`TenantAlreadyExistsError` is imported from `app.platform.domain.exceptions`, the module
section 4 set up so the rest of `platform/` has one canonical location for the exception
type the section wires up.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.platform.domain.exceptions import TenantAlreadyExistsError, TenantNotActiveError

# Order matters: the first matching entry wins. `TenantNotActiveError` is a subclass of
# `PlatformDomainError`, not of `TenantAlreadyExistsError`, so order between the two
# concrete classes is irrelevant here — the explicit table means nothing else falls
# through anyway.
_MAPPING: tuple[tuple[type[Exception], int, ErrorCode, str], ...] = (
    (
        TenantAlreadyExistsError,
        409,
        ErrorCode.CONFLICT,
        "A tenant with this name already exists",
    ),
    (
        TenantNotActiveError,
        404,
        ErrorCode.NOT_FOUND,
        "Tenant does not exist",
    ),
)


def register_platform_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TenantAlreadyExistsError)
    async def _already_exists(_: Request, exc: TenantAlreadyExistsError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=error_envelope(ErrorCode.CONFLICT, str(exc)),
        )

    @app.exception_handler(TenantNotActiveError)
    async def _not_active(_: Request, exc: TenantNotActiveError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=error_envelope(ErrorCode.NOT_FOUND, str(exc)),
        )


__all__ = ["register_platform_error_handlers"]
