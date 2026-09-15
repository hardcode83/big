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

# A caller who sends many distinct unknown keys in one request gets one `extra_forbidden`
# error per key, and each entry costs a fixed response overhead (`loc`, `type`, the fixed
# `msg`, JSON punctuation) regardless of how short the key is — so this axis (error COUNT,
# not `loc` length) can still scale the response well past the request that produced it.
# 20 is generously above any real accidental-typo scenario (a caller fat-fingering a
# request sends a handful of wrong keys, never twenty).
_MAX_EXTRA_FORBIDDEN_ERRORS = 20


def _bound_extra_forbidden_segment(segment: str) -> tuple[str, bool]:
    """Returns the bounded segment and whether it was actually truncated.

    The boolean is the unforgeable truncation signal: a caller-supplied key that merely
    *ends with* the truncation marker (but is itself <=100 chars) is never touched, so it
    comes back with `truncated=False` even though its text happens to match the marker.
    """
    if len(segment) <= _EXTRA_FORBIDDEN_LOC_MAX_LENGTH:
        return segment, False
    cutoff = _EXTRA_FORBIDDEN_LOC_MAX_LENGTH - len(_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER)
    return segment[:cutoff] + _EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER, True


def _serialisable_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    serialisable: list[dict[str, Any]] = []
    extra_forbidden_seen = 0
    extra_forbidden_dropped = 0
    for error in exc.errors():
        loc = [str(part) for part in error.get("loc", ())]
        error_type = str(error.get("type", ""))
        # Only `extra_forbidden` echoes raw caller input. For every schema in this
        # codebase today (all `extra="forbid"` models with typed, non-dict fields), every
        # other error type's `loc` is entirely schema-derived (real field names) and must
        # never be touched. The one caveat: a hypothetical `dict[str, <model>]` request
        # field would let a caller's dict key surface unbounded under a different error
        # type (e.g. `string_type`) — this fix does not cover that, because no such field
        # exists in this codebase today.
        truncated = False
        if error_type == "extra_forbidden":
            if extra_forbidden_seen >= _MAX_EXTRA_FORBIDDEN_ERRORS:
                extra_forbidden_dropped += 1
                continue
            extra_forbidden_seen += 1
            if loc:
                loc[-1], truncated = _bound_extra_forbidden_segment(loc[-1])
        entry: dict[str, Any] = {
            "loc": loc,
            "type": error_type,
            "msg": str(error.get("msg", "")),
        }
        if truncated:
            entry["loc_truncated"] = True
        serialisable.append(entry)
    if extra_forbidden_dropped:
        serialisable.append(
            {
                "loc": [],
                "type": "extra_forbidden_omitted",
                "msg": (
                    f"{extra_forbidden_dropped} more unknown field error(s) omitted "
                    f"(cap: {_MAX_EXTRA_FORBIDDEN_ERRORS})"
                ),
            }
        )
    return serialisable
