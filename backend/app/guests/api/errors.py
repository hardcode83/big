"""Maps guests domain errors onto the PRD §23 envelope.

Same shape as `app/access/api/errors.py`. The table is exhaustive over
`app/guests/domain/exceptions.py`.

`404` for a cross-tenant guest is not a convention here, it is the point: the alternative
turns the endpoint into an oracle telling a caller whether an id exists somewhere — about a
person's identity document.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.guests.domain.exceptions import (
    GuestDocumentMissingError,
    GuestDomainError,
    GuestNotFoundError,
    LegalRegistrationNotReadyError,
    ReservationNotFoundError,
)

_MAPPING: tuple[tuple[type[GuestDomainError], int, ErrorCode], ...] = (
    (GuestNotFoundError, 404, ErrorCode.NOT_FOUND),
    (ReservationNotFoundError, 404, ErrorCode.NOT_FOUND),
    (GuestDocumentMissingError, 404, ErrorCode.NOT_FOUND),
    (LegalRegistrationNotReadyError, 409, ErrorCode.CONFLICT),
)


def http_error_for(exc: GuestDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    return 500, ErrorCode.INTERNAL_ERROR


def register_guest_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GuestDomainError)
    async def _guest_error(_: Request, exc: GuestDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected guest error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
