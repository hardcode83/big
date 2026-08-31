"""Maps notifications domain errors onto the PRD §23 envelope.

Same shape as `app/timeline/api/errors.py` and `app/access/api/errors.py`: the domain stays
free of FastAPI, so the translation happens in exactly one declared place per module. This
module did not exist before `notifications-inbox-web` because the module's only route could
not fail in a way a client could act on.

**Order matters**: subclasses before their bases, because `http_error_for` returns on the
first match.

`NotificationLogNotFoundError` is deliberately absent, and the omission is the point. It is
raised by `mark_breached` and `record_attempt` — writes of the SLA job and the dispatcher,
neither of which is behind a route — and reaching it from an HTTP request would mean a
broken invariant, not an outcome a caller foresaw. It falls to the `500` below, with its
message replaced, because it names the id it could not reach and no client is owed that.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.notifications.domain.exceptions import (
    NotificationDomainError,
    NotificationNotFoundError,
)

_MAPPING: tuple[tuple[type[NotificationDomainError], int, ErrorCode], ...] = (
    # R1.4: indistinguishable between "does not exist", "another user's" and "another
    # tenant's". The use case cannot tell them apart either — design D3's single UPDATE
    # collapses them into one `rowcount == 0` — which is what makes that true rather than
    # merely intended. And the error carries a constant message, so two different ids do not
    # even produce two different bodies.
    (NotificationNotFoundError, 404, ErrorCode.NOT_FOUND),
)


def http_error_for(exc: NotificationDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    return 500, ErrorCode.INTERNAL_ERROR


def register_notification_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotificationDomainError)
    async def _notification_error(
        _: Request, exc: NotificationDomainError
    ) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected notification error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
