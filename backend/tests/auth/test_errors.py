"""The auth domain-error → HTTP envelope mapping (`auth-account-recovery` R1.5, R3.3, R5.4).

Same shape as `tests/cleaning/test_errors.py`: presence, status, ordering and the fallback,
each checked separately, because a test that only asserts "every error has a row" stays green
when a row's status is changed to the wrong one.
"""

import pytest

from app.auth.api.errors import _MAPPING, http_error_for
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
    TokenTypeMismatchError,
    TooManyAttemptsError,
    UnassignableRoleError,
    UserNotFoundError,
)


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (InvalidCredentialsError("x"), 401, "INVALID_CREDENTIALS"),
        (SessionReuseDetectedError("x"), 401, "INVALID_TOKEN"),
        (InvalidTokenError("x"), 401, "INVALID_TOKEN"),
        (TokenTypeMismatchError("x"), 401, "INVALID_TOKEN"),
        (TooManyAttemptsError("x"), 429, "RATE_LIMITED"),
        (PasswordTooLongError("x"), 422, "VALIDATION_ERROR"),
        (UserNotFoundError("x"), 404, "NOT_FOUND"),
        (EmailAlreadyExistsError("x"), 409, "CONFLICT"),
        (SelfRoleChangeError("x"), 422, "VALIDATION_ERROR"),
        (LastOwnerError("x"), 422, "VALIDATION_ERROR"),
        (UnassignableRoleError("x"), 422, "VALIDATION_ERROR"),
        # `auth-account-recovery`.
        (PasswordPolicyError("x"), 422, "VALIDATION_ERROR"),
        (PasswordUnchangedError("x"), 422, "VALIDATION_ERROR"),
        (InvalidRecoveryTokenError(), 401, "INVALID_TOKEN"),
        (PasswordChangeRequiredError("x"), 403, "PASSWORD_CHANGE_REQUIRED"),
    ],
)
def test_each_error_maps_to_its_status_and_code(error, expected_status, expected_code) -> None:
    status, code = http_error_for(error)

    assert (status, code.value) == (expected_status, expected_code)


def test_a_broken_policy_answers_422_and_not_500() -> None:
    """R1.5 requires a `422` naming the rule; an unmapped error would be a `500` whose
    message the handler replaces with "Unexpected authentication error"."""
    status, code = http_error_for(PasswordPolicyError("Password must be at least 12"))

    assert (status, code.value) == (422, "VALIDATION_ERROR")


def test_every_reason_a_recovery_link_can_fail_answers_the_same() -> None:
    """R3.3 — unknown, used, expired, revoked, inactive user and inactive tenant are all
    raised as one undifferentiated `InvalidRecoveryTokenError`, so there is a single row and
    the response cannot be used to tell the six apart."""
    rows = [row for row in _MAPPING if row[0] is InvalidRecoveryTokenError]

    assert len(rows) == 1
    assert (rows[0][1], rows[0][2].value) == (401, "INVALID_TOKEN")


def test_the_password_change_gate_is_403_and_carries_its_own_code() -> None:
    """R5.4 asks for a code that is "propio y accionable".

    Not `FORBIDDEN`: the frontend has to tell "you may not do this" from "change your
    password first", and only the second one has somewhere to send the user.
    """
    status, code = http_error_for(PasswordChangeRequiredError("x"))

    assert status == 403
    assert code.value == "PASSWORD_CHANGE_REQUIRED"


def test_a_recovery_token_failure_is_not_reported_as_bad_credentials() -> None:
    """`401 INVALID_TOKEN`, not `401 INVALID_CREDENTIALS`: no password was presented."""
    _, code = http_error_for(InvalidRecoveryTokenError())

    assert code.value != "INVALID_CREDENTIALS"


def test_a_recovery_failure_cannot_carry_a_per_cause_message() -> None:
    """R3.3 made structural rather than conventional.

    The handler renders `str(exc)` into the response body, so a message chosen per raise
    site would be a per-cause channel in the one response R3.3 requires to be identical —
    and this error has about six raise sites. A constructor that accepts nothing cannot be
    handed `f"token {token} not found"`, which also closes the R4.3 route by which a live
    token could reach a `401` body.
    """
    with pytest.raises(TypeError):
        InvalidRecoveryTokenError("token abc123 expired at 12:00")  # type: ignore[call-arg]


def test_every_recovery_failure_renders_the_same_body() -> None:
    """Two independently constructed instances are indistinguishable to the caller."""
    first, second = InvalidRecoveryTokenError(), InvalidRecoveryTokenError()

    assert str(first) == str(second) == InvalidRecoveryTokenError.MESSAGE
    assert http_error_for(first) == http_error_for(second)


def test_the_recovery_failure_message_names_no_cause() -> None:
    """It must not say which of the six things went wrong."""
    message = InvalidRecoveryTokenError.MESSAGE.lower()

    for leak in ("used", "revoked", "unknown", "inactive", "suspended", "not found"):
        assert leak not in message


def test_subclasses_come_before_their_base() -> None:
    """`_MAPPING` is ordered and first match wins, so a base before its subclass would
    swallow it. Checked structurally rather than by eyeballing the literal.

    The direction matters and is easy to get backwards: the bug is a **later** entry that
    is a subclass of an **earlier** one, because `http_error_for` would never reach it. So
    the check is `issubclass(later, earlier)`, not the reverse — asserting the reverse
    flags correct orderings and passes the broken one, which is what an earlier version of
    this test did (caught by the architect panel of section 3).
    """
    for index, (earlier_class, _, _) in enumerate(_MAPPING):
        for later_class, _, _ in _MAPPING[index + 1 :]:
            assert not issubclass(later_class, earlier_class), (
                f"{later_class.__name__} is a subclass of {earlier_class.__name__}, which "
                f"comes first in _MAPPING, so {later_class.__name__}'s row is unreachable"
            )


def test_the_ordering_guard_catches_a_base_placed_before_its_subclass() -> None:
    """The guard's own guard: it must fail on the arrangement it exists to forbid.

    Without this, the check above can be silently inverted and stay green — today no two
    rows of `_MAPPING` are in a subclass relationship, so a broken assertion has nothing
    to trip over and looks healthy for as long as that holds.
    """
    broken = ((InvalidTokenError, 401, None), (TokenTypeMismatchError, 401, None))

    with pytest.raises(AssertionError):
        for index, (earlier_class, _, _) in enumerate(broken):
            for later_class, _, _ in broken[index + 1 :]:
                assert not issubclass(later_class, earlier_class)


def test_the_ordering_guard_accepts_a_subclass_placed_before_its_base() -> None:
    """The other half: the correct arrangement must pass, or the guard forbids everything."""
    correct = ((TokenTypeMismatchError, 401, None), (InvalidTokenError, 401, None))

    for index, (earlier_class, _, _) in enumerate(correct):
        for later_class, _, _ in correct[index + 1 :]:
            assert not issubclass(later_class, earlier_class)


def test_an_unmapped_auth_error_falls_to_500() -> None:
    class SurpriseError(AuthDomainError):
        pass

    status, code = http_error_for(SurpriseError("x"))

    assert status == 500
    assert code.value == "INTERNAL_ERROR"


def test_every_new_error_of_this_change_has_a_row() -> None:
    """Presence, separately from status: the four exceptions section 1 added must all be
    mapped, or they surface as `500`s the caller cannot act on."""
    mapped = {row[0] for row in _MAPPING}

    for error_class in (
        PasswordPolicyError,
        PasswordUnchangedError,
        InvalidRecoveryTokenError,
        PasswordChangeRequiredError,
    ):
        assert error_class in mapped, f"{error_class.__name__} has no row in _MAPPING"
