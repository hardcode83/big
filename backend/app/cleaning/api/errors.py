"""Maps cleaning domain errors onto the PRD §23 envelope (design D11).

Same shape as `app/reservations/api/errors.py`, and for the same reason: the domain stays
free of FastAPI and of `app.core.errors` (which imports it), so the translation happens in
exactly one declared place instead of being repeated — or forgotten — per router.

The table is exhaustive over `app/cleaning/domain/exceptions.py`. An unmapped error falls
to 500, which is right for a bug of ours and never for an outcome we foresaw, so adding an
exception without adding its row here is a defect the `test_errors.py` completeness test
catches.

`404` for a cross-tenant reference — and for another cleaner's task — is R7.3 and R7.2, not
a convention: see design D7.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.cleaning.domain.exceptions import (
    AmbiguousChecklistTemplateError,
    BlockingIncidentError,
    ChecklistIncompleteError,
    ChecklistItemNotFoundError,
    ChecklistTemplateNotFoundError,
    CleaningDomainError,
    CleaningTaskNotFoundError,
    CleaningValidationError,
    DuplicateLiveCleaningTaskError,
    InvalidCleaningTransitionError,
    PropertyNotFoundError,
    PropertyStateBlocksCleaningError,
    ReservationNotFoundError,
)
from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope

# Order matters: the first matching entry wins, so subclasses come before their base.
_MAPPING: tuple[tuple[type[CleaningDomainError], int, ErrorCode], ...] = (
    (CleaningTaskNotFoundError, 404, ErrorCode.NOT_FOUND),
    (ChecklistTemplateNotFoundError, 404, ErrorCode.NOT_FOUND),
    (ChecklistItemNotFoundError, 404, ErrorCode.NOT_FOUND),
    (PropertyNotFoundError, 404, ErrorCode.NOT_FOUND),
    (ReservationNotFoundError, 404, ErrorCode.NOT_FOUND),
    (InvalidCleaningTransitionError, 409, ErrorCode.CONFLICT),
    (PropertyStateBlocksCleaningError, 409, ErrorCode.CONFLICT),
    (ChecklistIncompleteError, 409, ErrorCode.CONFLICT),
    (BlockingIncidentError, 409, ErrorCode.CONFLICT),
    (AmbiguousChecklistTemplateError, 409, ErrorCode.CONFLICT),
    (DuplicateLiveCleaningTaskError, 409, ErrorCode.CONFLICT),
    (CleaningValidationError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: CleaningDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # A cleaning error nobody mapped is a bug, not a client problem.
    return 500, ErrorCode.INTERNAL_ERROR


def register_cleaning_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CleaningDomainError)
    async def _cleaning_error(_: Request, exc: CleaningDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected cleaning error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
