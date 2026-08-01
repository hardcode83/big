"""Maps tenant domain errors onto the PRD §23 envelope.

Same shape and same reason as `app/auth/api/errors.py` and
`app/reservations/api/errors.py`: the domain stays free of FastAPI, so the translation happens
in exactly one declared place per module instead of being repeated — or forgotten — per router.

`404` for a tenant that is not the token's own is requirement R7.9, not a convention: see
design D12.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import error_envelope
from app.tenants.domain.exceptions import (
    TenantDomainError,
    TenantNotFoundError,
    TenantValidationError,
)

_MAPPING: tuple[tuple[type[TenantDomainError], int, str], ...] = (
    (TenantNotFoundError, 404, "NOT_FOUND"),
    (TenantValidationError, 422, "VALIDATION_ERROR"),
)


def http_error_for(exc: TenantDomainError) -> tuple[int, str]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # A tenant error nobody mapped is a bug, not a client problem.
    return 500, "INTERNAL_ERROR"


def register_tenant_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TenantDomainError)
    async def _tenant_error(_: Request, exc: TenantDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected tenant error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
