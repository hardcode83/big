"""Maps auth domain errors onto the PRD §23 envelope.

Lives in `auth/api/` rather than `core/errors.py` on purpose: `core` must stay free
of business rules (design D1), and `app.auth.domain.exceptions.InvalidTokenError`
shares its name with `app.core.errors.InvalidTokenError`. Doing the translation in
one declared place means a router never has to pick between them — an accidental
import of the wrong one would answer 500 where 401 is required.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.domain.exceptions import (
    AuthDomainError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
    LastOwnerError,
    PasswordTooLongError,
    SelfRoleChangeError,
    SessionReuseDetectedError,
    TooManyAttemptsError,
    UnassignableRoleError,
    UserNotFoundError,
)
from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope

# Order matters: the first matching entry wins, so subclasses come before their base
# (TokenTypeMismatchError is an InvalidTokenError).
_MAPPING: tuple[tuple[type[AuthDomainError], int, ErrorCode], ...] = (
    (InvalidCredentialsError, 401, ErrorCode.INVALID_CREDENTIALS),
    (SessionReuseDetectedError, 401, ErrorCode.INVALID_TOKEN),
    (InvalidTokenError, 401, ErrorCode.INVALID_TOKEN),
    (TooManyAttemptsError, 429, ErrorCode.RATE_LIMITED),
    (PasswordTooLongError, 422, ErrorCode.VALIDATION_ERROR),
    # Added by `user-management`. `404` for a user of another tenant is requirement R7.1,
    # not a convention: the answer must not reveal that the resource exists.
    (UserNotFoundError, 404, ErrorCode.NOT_FOUND),
    (EmailAlreadyExistsError, 409, ErrorCode.CONFLICT),
    # The three refusals of an operation that is well-formed but not allowed to happen.
    # `422` and not `403`: the caller HAS the permission, the request is the problem.
    (SelfRoleChangeError, 422, ErrorCode.VALIDATION_ERROR),
    (LastOwnerError, 422, ErrorCode.VALIDATION_ERROR),
    (UnassignableRoleError, 422, ErrorCode.VALIDATION_ERROR),
)


def http_error_for(exc: AuthDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    # An auth error nobody mapped is a bug, not a client problem.
    return 500, ErrorCode.INTERNAL_ERROR


def register_auth_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthDomainError)
    async def _auth_error(_: Request, exc: AuthDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected authentication error"
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse(
            status_code=status, content=error_envelope(code, message), headers=headers
        )
