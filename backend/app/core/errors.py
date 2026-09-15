"""HTTP error contract shared by every module (PRD §23, design D11).

The wire format is `{"error": {"code", "message", "details"}}`. It is not
cosmetic: `frontend/lib/api/errors.ts` only recognises that shape, and anything
else reaches the client as a generic `UNKNOWN_ERROR` with the real message lost.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import ErrorCode


class AppError(Exception):
    """Base for errors that map onto the PRD §23 envelope."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationFailedError(AppError):
    code = ErrorCode.VALIDATION_ERROR
    http_status = 422


class InvalidCredentialsError(AppError):
    code = ErrorCode.INVALID_CREDENTIALS
    http_status = 401


class InvalidTokenError(AppError):
    code = ErrorCode.INVALID_TOKEN
    http_status = 401


class ForbiddenError(AppError):
    code = ErrorCode.FORBIDDEN
    http_status = 403


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    http_status = 404


class RateLimitedError(AppError):
    code = ErrorCode.RATE_LIMITED
    http_status = 429


def error_envelope(
    code: ErrorCode, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


_HTTP_STATUS_CODES: dict[int, ErrorCode] = {
    401: ErrorCode.INVALID_TOKEN,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    429: ErrorCode.RATE_LIMITED,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=error_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body is `{"detail": [...]}`, which is not the PRD §23
        # envelope; without this the frontend degrades it to UNKNOWN_ERROR.
        return JSONResponse(
            status_code=422,
            content=error_envelope(
                ErrorCode.VALIDATION_ERROR,
                "Request validation failed",
                {"errors": _serialisable_validation_errors(exc)},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, ErrorCode.HTTP_ERROR)
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(code, message, {}),
            headers=getattr(exc, "headers", None),
        )


# Every module in this codebase declares `extra="forbid"` on its request schemas, and
# Pydantic's `extra_forbidden` error puts the literal unknown key the caller sent as the
# last `loc` segment — the one caller-controlled value in an otherwise schema-derived
# list. 100 is an arbitrary but generous bound: no real field name is anywhere close to
# it, so it never clips a legitimate `loc`.
_EXTRA_FORBIDDEN_LOC_MAX_LENGTH = 100
_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER = "...(truncated)"


def _bound_extra_forbidden_segment(segment: str) -> str:
    if len(segment) <= _EXTRA_FORBIDDEN_LOC_MAX_LENGTH:
        return segment
    cutoff = _EXTRA_FORBIDDEN_LOC_MAX_LENGTH - len(_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER)
    return segment[:cutoff] + _EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER


def _serialisable_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    serialisable: list[dict[str, Any]] = []
    for error in exc.errors():
        loc = [str(part) for part in error.get("loc", ())]
        # Only `extra_forbidden` echoes raw caller input; every other error type's `loc`
        # is entirely schema-derived (real field names) and must never be touched.
        if error.get("type") == "extra_forbidden" and loc:
            loc[-1] = _bound_extra_forbidden_segment(loc[-1])
        serialisable.append(
            {
                "loc": loc,
                "type": str(error.get("type", "")),
                "msg": str(error.get("msg", "")),
            }
        )
    return serialisable
