"""What a self-chosen password must satisfy (R1.5, R1.6, design D4).

Pure domain — no imports outside `app.auth.domain`, so `tests/test_layering.py` stays
satisfied and the rule can be asserted anywhere without a database.

Two rules, and no character-class requirement. Composition rules do not measure strength,
they have to be described to the user, and they reject long passphrases that are better
than anything they would allow. The temporary-password generator guarantees its three
classes on its own account (`passwords.py`); that guarantee exists so this policy cannot
reject what the system emits, not to be copied here.
"""

from app.auth.domain.exceptions import (
    PasswordPolicyError,
    PasswordTooLongError,
    PasswordUnchangedError,
)

# A domain constant and NOT a setting (design D4). R1.6 obliges this policy to accept every
# password `generate_temporary_password()` produces, so a deployment that raised the minimum
# above `TEMPORARY_PASSWORD_LENGTH` would make the system reject its own credentials.
# `test_password_policy.py` pins the two together.
PASSWORD_MIN_LENGTH = 12

# bcrypt hashes at most 72 BYTES of input, and `auth-tenancy` refuses a longer password
# rather than truncating it silently (its R1.3). Validating the same bound here is what turns
# that refusal into a `422` at the boundary instead of an unmapped `500` from the hasher.
PASSWORD_MAX_BYTES = 72


def assert_password_acceptable(password: str) -> None:
    """Raise if `password` breaks the policy; return None if it is acceptable.

    Names the rule that was broken and never includes the password in the message: the
    message reaches the API response and the application log (R1.5, R4.3).
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters long"
        )
    try:
        encoded_length = len(password.encode("utf-8"))
    except UnicodeEncodeError as exc:
        # A lone UTF-16 surrogate is a `str` Python holds happily but cannot encode, and it
        # reaches here: `json.loads` and pydantic both accept an unpaired `\uD800` escape
        # from a request body without complaint. Left to propagate it would be an unmapped
        # `500` — exactly the failure mode the byte check below exists to prevent, so it
        # answers the same way the rest of the policy does (R1.5).
        raise PasswordPolicyError("Password must be valid UTF-8 text") from exc
    if encoded_length > PASSWORD_MAX_BYTES:
        raise PasswordTooLongError(
            f"Password must not exceed {PASSWORD_MAX_BYTES} bytes encoded as UTF-8"
        )


def assert_password_changed(new_password: str, current_password: str) -> None:
    """Raise if the replacement is the password already in place (R1.7).

    A named predicate in `domain/` rather than an `if` in the use case, for the same reason
    `assert_password_acceptable` is one: both are rules about what a password may be, and
    splitting siblings across layers is how one of them later gets changed alone. The
    architecture panel of section 4 caught the asymmetry.

    **Only R1 can call this**, and that is a property of the caller rather than of the rule:
    it needs the current password in cleartext, which exists only where the holder presented
    it. `reset-password` has no such value and design D11 declines to spend a bcrypt
    `verify` on an anonymous endpoint to obtain one — the asymmetry is deliberate, because
    what R1.7 prevents is revoking every session without rotating anything, and somebody
    completing a recovery wants those sessions gone regardless.

    The comparison is exact rather than normalised: a password differing only in trailing
    whitespace IS a different password, and trimming here would silently reject a legitimate
    change while `verify` and `hash` treat the two as distinct everywhere else.
    """
    if new_password == current_password:
        raise PasswordUnchangedError(
            "The new password must be different from the current one"
        )
