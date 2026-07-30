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


class AppError(Exception):
    """Base for errors that map onto the PRD §23 envelope."""

    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationFailedError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 422


class InvalidCredentialsError(AppError):
    code = "INVALID_CREDENTIALS"
    http_status = 401


class InvalidTokenError(AppError):
    code = "INVALID_TOKEN"
    http_status = 401


class ForbiddenError(AppError):
    code = "FORBIDDEN"
    http_status = 403


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    http_status = 429


def error_envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


_HTTP_STATUS_CODES = {
    401: "INVALID_TOKEN",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    429: "RATE_LIMITED",
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
                "VALIDATION_ERROR",
                "Request validation failed",
                {"errors": _serialisable_validation_errors(exc)},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(code, message, {}),
            headers=getattr(exc, "headers", None),
        )


def _serialisable_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    serialisable: list[dict[str, Any]] = []
    for error in exc.errors():
        serialisable.append(
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "type": str(error.get("type", "")),
                "msg": str(error.get("msg", "")),
            }
        )
    return serialisable
