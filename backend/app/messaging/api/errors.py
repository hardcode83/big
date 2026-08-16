"""Maps messaging domain errors onto the PRD §23 envelope (design D17).

Same shape as `app/maintenance/api/errors.py`, and for the same reason: `domain/` stays free
of FastAPI and of `app.core.errors` (which imports it), so the translation happens in exactly
one declared place instead of being repeated — or forgotten — per route.

The table is **exhaustive over `app/messaging/domain/exceptions.py`**. An unmapped error falls
to 500, which is right for a bug of ours and never for an outcome we foresaw, so adding an
exception without adding its row here is a defect `tests/messaging/test_errors.py` catches by
walking the module.

`404` for a cross-tenant reference is R1.5 and not a convention: a distinguishable answer
would confirm that the conversation exists and belongs to somebody else.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.messaging.domain.exceptions import (
    ConversationClosedError,
    ConversationNotFoundError,
    InvalidConversationTransitionError,
    MessagingDomainError,
    MessagingValidationError,
    PMSChannelUnavailableError,
)

# Order matters: the first matching entry wins. The hierarchy is flat by design (see the
# module docstring of `domain/exceptions.py`), so no row depends on sitting above another —
# which is exactly what that flatness buys.
_MAPPING: tuple[tuple[type[MessagingDomainError], int, ErrorCode], ...] = (
    (ConversationNotFoundError, 404, ErrorCode.NOT_FOUND),
    (InvalidConversationTransitionError, 409, ErrorCode.CONFLICT),
    (ConversationClosedError, 409, ErrorCode.CONFLICT),
    (PMSChannelUnavailableError, 422, ErrorCode.VALIDATION_ERROR),
    (MessagingValidationError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: MessagingDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # A messaging error nobody mapped is a bug, not a client problem.
    return 500, ErrorCode.INTERNAL_ERROR


def register_messaging_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MessagingDomainError)
    async def _messaging_error(_: Request, exc: MessagingDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected messaging error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
