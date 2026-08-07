"""Maps property domain errors onto the PRD §23 envelope.

Same shape and same reason as `app/tenants/api/errors.py` and `app/reservations/api/errors.py`:
the domain stays free of FastAPI, so the translation happens in exactly one declared place per
module instead of being repeated — or forgotten — per router.

**Order matters here**: subclasses before their bases, because `http_error_for` returns on the
first match. All four mapped errors are siblings today, but the file is the place that rule is
written down.

`CrossTenantWriteError` is deliberately absent. It is not an `AppError` and not a domain error;
reaching it means a use case passed an entity from another tenant, which is a programming error
that must surface as a `500` rather than be translated into something a client could act on.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.properties.domain.exceptions import (
    AmbiguousPropertyExternalIdError,
    DuplicateInternalCodeError,
    DuplicatePmsExternalIdError,
    PropertyDomainError,
    PropertyNotFoundError,
    PropertyValidationError,
)

_MAPPING: tuple[tuple[type[PropertyDomainError], int, ErrorCode], ...] = (
    (PropertyNotFoundError, 404, ErrorCode.NOT_FOUND),
    # Both duplicates are `409 CONFLICT` and not `422`: the body is well formed, it just
    # collides with a row the caller may not be able to see. Translated from the named
    # constraint in the adapter, never from a prior read, which is what makes them race-free.
    (DuplicateInternalCodeError, 409, ErrorCode.CONFLICT),
    (DuplicatePmsExternalIdError, 409, ErrorCode.CONFLICT),
    (PropertyValidationError, 422, ErrorCode.VALIDATION_ERROR),
    # A tenant holding two properties with one external id is a data problem the caller cannot
    # fix from this endpoint, and `find_by_pms_external_id` raises it defensively. `409` says
    # "the stored state conflicts", which is the truth, without pretending the request was wrong.
    (AmbiguousPropertyExternalIdError, 409, ErrorCode.CONFLICT),
)


def http_error_for(exc: PropertyDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # A property error nobody mapped is a bug, not a client problem. In particular the state
    # machine's own errors (`InvalidStateTransitionError` and friends) land here on purpose:
    # no endpoint of this capability can trigger a transition, so one arriving means something
    # reached a route it should not have.
    return 500, ErrorCode.INTERNAL_ERROR


def register_property_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PropertyDomainError)
    async def _property_error(_: Request, exc: PropertyDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected property error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
