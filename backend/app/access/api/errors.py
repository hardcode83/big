"""Maps access domain errors onto the PRD §23 envelope.

Same shape as `app/cleaning/api/errors.py`. The table is exhaustive over
`app/access/domain/exceptions.py`; an unmapped error falls to 500, which is right for a bug
of ours and never for an outcome we foresaw.

`404` for a cross-tenant reference is R3.3, not a convention: the body must be identical to
the one for an id that does not exist, or the endpoint becomes an existence oracle.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.access.domain.exceptions import (
    AccessCodeInNotesError,
    AccessCodeRequiredError,
    AccessDomainError,
    AccessRecordNotFoundError,
    InvalidAccessTransitionError,
)
from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope

# Order matters: the first matching entry wins, so subclasses come before their base.
_MAPPING: tuple[tuple[type[AccessDomainError], int, ErrorCode], ...] = (
    (AccessRecordNotFoundError, 404, ErrorCode.NOT_FOUND),
    (InvalidAccessTransitionError, 409, ErrorCode.CONFLICT),
    (AccessCodeRequiredError, 422, ErrorCode.VALIDATION_ERROR),
    (AccessCodeInNotesError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: AccessDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    return 500, ErrorCode.INTERNAL_ERROR


def register_access_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AccessDomainError)
    async def _access_error(_: Request, exc: AccessDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected access error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
