"""Domain error families for auth (R1.4, R2.2, R2.5).

Same shape as app/timeline/domain/exceptions.py: a single base so the application
layer can map the whole family onto HTTP without importing anything from api/.

Every class here has a real caller. An `AccountLockedError` was removed during review
for lacking one: the locked-account path raises `InvalidCredentialsError` instead,
because R1.4 requires the answer to be indistinguishable from a wrong password, and the
real reason already reaches the log.
"""

import pytest

from app.auth.domain.exceptions import (
    AuthDomainError,
    InvalidCredentialsError,
    InvalidTokenError,
    PasswordTooLongError,
    SessionReuseDetectedError,
    TokenTypeMismatchError,
    TooManyAttemptsError,
)


@pytest.mark.parametrize(
    "error_class",
    [
        InvalidCredentialsError,
        InvalidTokenError,
        TokenTypeMismatchError,
        SessionReuseDetectedError,
        PasswordTooLongError,
        TooManyAttemptsError,
    ],
)
def test_every_auth_error_belongs_to_the_family(error_class: type[Exception]) -> None:
    assert issubclass(error_class, AuthDomainError)
    assert issubclass(error_class, Exception)


def test_token_type_mismatch_is_a_kind_of_invalid_token() -> None:
    # A refresh presented as an access token is one specific way of being invalid;
    # callers that only care about "not a usable token" should catch the parent.
    assert issubclass(TokenTypeMismatchError, InvalidTokenError)


def test_errors_carry_their_message() -> None:
    assert str(InvalidCredentialsError("Invalid email or password")) == "Invalid email or password"
