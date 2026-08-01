"""Maps reservation domain errors onto the PRD §23 envelope.

Same shape as `app/auth/api/errors.py`, and for the same reason: the domain stays free of
FastAPI and of `app.core.errors` (which imports it), so the translation happens in exactly
one declared place instead of being repeated — or forgotten — per router.

`404` for a cross-tenant reference is requirement R5.1, not a convention: see design D6.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import error_envelope
from app.reservations.domain.exceptions import (
    DuplicateExternalReservationError,
    GuestNotFoundError,
    PropertyNotFoundError,
    ReservationDomainError,
    ReservationNotFoundError,
    ReservationValidationError,
)

# Order matters: the first matching entry wins, so subclasses come before their base.
_MAPPING: tuple[tuple[type[ReservationDomainError], int, str], ...] = (
    (ReservationNotFoundError, 404, "NOT_FOUND"),
    (PropertyNotFoundError, 404, "NOT_FOUND"),
    (GuestNotFoundError, 404, "NOT_FOUND"),
    (DuplicateExternalReservationError, 409, "CONFLICT"),
    (ReservationValidationError, 422, "VALIDATION_ERROR"),
)


def http_error_for(exc: ReservationDomainError) -> tuple[int, str]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # A reservation error nobody mapped is a bug, not a client problem.
    return 500, "INTERNAL_ERROR"


def register_reservation_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ReservationDomainError)
    async def _reservation_error(_: Request, exc: ReservationDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected reservation error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
