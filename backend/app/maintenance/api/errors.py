"""Maps maintenance domain errors onto the PRD §23 envelope (design D14).

Same shape as `app/cleaning/api/errors.py`, and for the same reason: the domain stays free
of FastAPI and of `app.core.errors` (which imports it), so the translation happens in
exactly one declared place instead of being repeated — or forgotten — per router.

The table is exhaustive over `app/maintenance/domain/exceptions.py`. An unmapped error falls
to 500, which is right for a bug of ours and never for an outcome we foresaw, so adding an
exception without adding its row here is a defect `tests/maintenance/test_errors.py` catches.

`404` for a cross-tenant reference — and for an incident assigned to a different technician —
is R5.4 and R5.3, not a convention: a distinguishable answer would confirm that the incident
exists and belongs to somebody else.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.maintenance.domain.exceptions import (
    IncidentAlreadyClosedError,
    IncidentBlockedByPendingApprovalError,
    IncidentNotFoundError,
    IncidentPhotoStorageUnavailableError,
    IncidentPhotoTooLargeError,
    InvalidIncidentTransitionError,
    InvalidTechnicianError,
    MaintenanceDomainError,
    MaintenanceValidationError,
    OwnerApprovalAlreadyAnsweredError,
    OwnerApprovalNotFoundError,
    UnsupportedIncidentPhotoFormatError,
)

# Order matters: the first matching entry wins. The hierarchy is flat by design (see the
# module docstring of `domain/exceptions.py`), so no row depends on sitting above another —
# which is exactly what that flatness buys.
_MAPPING: tuple[tuple[type[MaintenanceDomainError], int, ErrorCode], ...] = (
    (IncidentNotFoundError, 404, ErrorCode.NOT_FOUND),
    (OwnerApprovalNotFoundError, 404, ErrorCode.NOT_FOUND),
    (InvalidIncidentTransitionError, 409, ErrorCode.CONFLICT),
    (IncidentAlreadyClosedError, 409, ErrorCode.CONFLICT),
    (IncidentBlockedByPendingApprovalError, 409, ErrorCode.CONFLICT),
    (OwnerApprovalAlreadyAnsweredError, 409, ErrorCode.CONFLICT),
    (InvalidTechnicianError, 422, ErrorCode.VALIDATION_ERROR),
    # The photo upload's three (`incident-photos` R2.8, R2.9, R5.1). Siblings of
    # `MaintenanceValidationError`, so their position relative to it does not matter — which is
    # the whole point of the flat hierarchy this module's header describes.
    (IncidentPhotoTooLargeError, 413, ErrorCode.PAYLOAD_TOO_LARGE),
    (UnsupportedIncidentPhotoFormatError, 422, ErrorCode.VALIDATION_ERROR),
    (IncidentPhotoStorageUnavailableError, 502, ErrorCode.BAD_GATEWAY),
    (MaintenanceValidationError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: MaintenanceDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # A maintenance error nobody mapped is a bug, not a client problem.
    return 500, ErrorCode.INTERNAL_ERROR


def register_maintenance_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MaintenanceDomainError)
    async def _maintenance_error(_: Request, exc: MaintenanceDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected maintenance error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
