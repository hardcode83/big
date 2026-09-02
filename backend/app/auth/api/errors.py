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
    InvalidRecoveryTokenError,
    InvalidTokenError,
    LastOwnerError,
    PasswordChangeRequiredError,
    PasswordPolicyError,
    PasswordTooLongError,
    PasswordUnchangedError,
    SelfRoleChangeError,
    SessionReuseDetectedError,
    SuperAdminSelfServiceUnsupportedError,
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
    # Added by `auth-account-recovery`. The two password refusals answer `422` for the same
    # reason as the three above: the request is what is wrong, not the caller's rights.
    (PasswordPolicyError, 422, ErrorCode.VALIDATION_ERROR),
    (PasswordUnchangedError, 422, ErrorCode.VALIDATION_ERROR),
    # `401 INVALID_TOKEN` for every reason a recovery link can fail (R3.3) — unknown, used,
    # expired, revoked, or an account that stopped being ACTIVE. One status and one code, so
    # the response cannot be used to tell those five apart. It shares the code with the JWT
    # errors above but not the class: see `InvalidRecoveryTokenError`'s docstring.
    (InvalidRecoveryTokenError, 401, ErrorCode.INVALID_TOKEN),
    # `403` and not `401`: the credential was accepted. What is refused is operating with a
    # password that still has to be changed (R5.4).
    (PasswordChangeRequiredError, 403, ErrorCode.PASSWORD_CHANGE_REQUIRED),
    # `super-admin-identity` D7: `403 FORBIDDEN` for the same reason as the three
    # `422`s above minus the retry — this account cannot reach a state a retry with
    # different input would fix, so `403` fits better than `422`.
    (SuperAdminSelfServiceUnsupportedError, 403, ErrorCode.FORBIDDEN),
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
