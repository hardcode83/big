"""Maps timeline domain errors onto the PRD §23 envelope.

Same shape and same reason as `app/properties/api/errors.py`: the domain stays free of
FastAPI, so the translation happens in exactly one declared place per module.

**Order matters**: subclasses before their bases, because `http_error_for` returns on the
first match.

`CrossTenantWriteError` is deliberately absent, as it is there: it is not a domain error,
and reaching it means a use case passed an entity from another tenant — a programming
error that must surface as a `500` rather than something a client could act on.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.timeline.domain.exceptions import (
    PropertyNotFoundError,
    TimelineDomainError,
    TimelineFilterValidationError,
)

_MAPPING: tuple[tuple[type[TimelineDomainError], int, ErrorCode], ...] = (
    # Indistinguishable between "does not exist" and "belongs to another tenant" (R4.5) —
    # the use case cannot tell them apart either, which is what makes that true rather
    # than merely intended.
    (PropertyNotFoundError, 404, ErrorCode.NOT_FOUND),
    (TimelineFilterValidationError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: TimelineDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # An unmapped timeline error is a bug, not a client problem. `TimelineEventValidationError`
    # and `TimelineMetadataNotSerialisableError` land here on purpose: they belong to the
    # write path, and no endpoint of this capability writes, so one arriving means something
    # reached a route it should not have.
    return 500, ErrorCode.INTERNAL_ERROR


def register_timeline_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TimelineDomainError)
    async def _timeline_error(_: Request, exc: TimelineDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected timeline error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
