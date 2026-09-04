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
    NoInboundMessageError,
    PMSChannelUnavailableError,
    WhatsAppPhoneNumberAlreadyAssociatedError,
    WhatsAppPhoneNumberNotFoundError,
    WhatsAppWebhookAuthenticationError,
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
    # The second net, not the plan: `whatsapp-cloud-adapter` section 7 catches this one and
    # answers `202`, because Meta redelivers on any non-2xx and a delivery receipt is not a
    # failure. The row is here so an escape is a named 422 instead of an unmapped 500 — see
    # the error's own docstring.
    (NoInboundMessageError, 422, ErrorCode.VALIDATION_ERROR),
    # Section 6 (R6.2, R6.3): the two outcomes of provisioning a tenant's WhatsApp number.
    (WhatsAppPhoneNumberAlreadyAssociatedError, 409, ErrorCode.CONFLICT),
    (WhatsAppPhoneNumberNotFoundError, 404, ErrorCode.NOT_FOUND),
    # Section 7 (R3.2, R3.3): the inbound webhook's one refusal. The router answers it
    # itself with a constant `403` and an empty body, so this row is the net behind an
    # escape — and it answers the same status, because a mapped 500 here would tell an
    # unauthenticated caller that it reached something.
    (WhatsAppWebhookAuthenticationError, 403, ErrorCode.FORBIDDEN),
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
