"""Maps reviews domain errors onto the PRD §23 envelope (design D17).

Same shape as `app/messaging/api/errors.py` and `app/maintenance/api/errors.py`, and
for the same reason: `domain/` stays free of FastAPI and of `app.core.errors` (which
imports it), so the translation happens in exactly one declared place instead of
being repeated — or forgotten — per route.

The table is **exhaustive over `app/reviews/domain/exceptions.py`**. An unmapped error
falls to 500, which is right for a bug of ours and never for an outcome we foresaw, so
adding an exception without adding its row here is a defect `tests/reviews/test_errors.py`
catches by walking the module.

`404` for a cross-tenant reference is R1.3 and not a convention: a distinguishable
answer would confirm that the review exists and belongs to somebody else.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.reviews.domain.exceptions import (
    DraftLanguageUnsupportedError,
    InvalidReviewTransitionError,
    ReviewLanguageInferenceError,
    ReviewNotFoundError,
    ReviewValidationError,
    ReviewsDomainError,
)

# Order matters: the first matching entry wins. The hierarchy is flat by design
# (see `domain/exceptions.py`), so no row depends on sitting above another — which is
# exactly what that flatness buys.
_MAPPING: tuple[tuple[type[ReviewsDomainError], int, ErrorCode], ...] = (
    (ReviewNotFoundError, 404, ErrorCode.NOT_FOUND),
    (InvalidReviewTransitionError, 409, ErrorCode.CONFLICT),
    (ReviewValidationError, 422, ErrorCode.VALIDATION_ERROR),
    (DraftLanguageUnsupportedError, 422, ErrorCode.VALIDATION_ERROR),
    (ReviewLanguageInferenceError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: ReviewsDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # A reviews error nobody mapped is a bug, not a client problem.
    return 500, ErrorCode.INTERNAL_ERROR


def register_reviews_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ReviewsDomainError)
    async def _reviews_error(_: Request, exc: ReviewsDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected reviews error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))
