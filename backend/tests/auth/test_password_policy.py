"""The password policy every self-chosen credential must satisfy (R1.5, R1.6, design D4).

Two rules and no character-class requirement, so the tests are about the two bounds and
about the one coupling that would silently break the product: the policy must accept every
password `app/auth/domain/passwords.py` emits.
"""

import pytest

from app.auth.domain.exceptions import (
    PasswordPolicyError,
    PasswordTooLongError,
    PasswordUnchangedError,
)
from app.auth.domain.password_policy import (
    PASSWORD_MAX_BYTES,
    PASSWORD_MIN_LENGTH,
    assert_password_acceptable,
    assert_password_changed,
)
from app.auth.domain.passwords import TEMPORARY_PASSWORD_LENGTH, generate_temporary_password


def test_a_password_of_the_minimum_length_is_accepted() -> None:
    assert_password_acceptable("a" * PASSWORD_MIN_LENGTH)


def test_one_character_under_the_minimum_is_refused() -> None:
    with pytest.raises(PasswordPolicyError):
        assert_password_acceptable("a" * (PASSWORD_MIN_LENGTH - 1))


def test_the_empty_password_is_refused() -> None:
    with pytest.raises(PasswordPolicyError):
        assert_password_acceptable("")


def test_exactly_seventy_two_bytes_is_accepted() -> None:
    """The bound is inclusive: bcrypt takes 72 bytes, so 72 must work."""
    assert_password_acceptable("a" * PASSWORD_MAX_BYTES)


def test_seventy_three_bytes_of_multibyte_text_is_refused() -> None:
    """The limit is BYTES, not characters: 25 three-byte glyphs are 75 bytes.

    Without this, an over-long password would reach the hasher, which `auth-tenancy`
    refuses rather than truncates — surfacing as an unmapped `500` instead of a `422`.
    """
    password = "€" * 25
    assert len(password) < PASSWORD_MAX_BYTES
    assert len(password.encode("utf-8")) > PASSWORD_MAX_BYTES
    with pytest.raises(PasswordTooLongError):
        assert_password_acceptable(password)


def test_a_lone_surrogate_is_refused_as_a_policy_violation() -> None:
    """R1.5 — it must answer with a named rule, not an unmapped `UnicodeEncodeError`.

    A lone UTF-16 surrogate survives `json.loads` and pydantic's `str`, so this string can
    genuinely arrive in a request body. Before the guard it reached `.encode("utf-8")` and
    blew up as a `500`, which is the very failure the byte cap exists to prevent.
    """
    password = "\ud800" + "abcdefghijk"
    assert len(password) >= PASSWORD_MIN_LENGTH
    with pytest.raises(PasswordPolicyError) as caught:
        assert_password_acceptable(password)
    assert "UTF-8" in str(caught.value)


def test_the_surrogate_refusal_never_echoes_the_password() -> None:
    password = "\ud800" + "secret-passphrase"
    with pytest.raises(PasswordPolicyError) as caught:
        assert_password_acceptable(password)
    assert "secret-passphrase" not in str(caught.value)


def test_a_long_passphrase_within_the_byte_limit_is_accepted() -> None:
    """No composition rules (design D4): a lowercase passphrase is a fine password."""
    assert_password_acceptable("correct horse battery staple")


@pytest.mark.parametrize(
    "password",
    ["short", "€" * 25],
    ids=["too-short", "too-long"],
)
def test_the_message_names_the_rule_and_never_echoes_the_password(password: str) -> None:
    """R1.5: say which rule was broken, without returning or logging the credential."""
    with pytest.raises((PasswordPolicyError, PasswordTooLongError)) as caught:
        assert_password_acceptable(password)
    message = str(caught.value)
    assert password not in message
    assert str(PASSWORD_MIN_LENGTH) in message or str(PASSWORD_MAX_BYTES) in message


# --- the replacement must differ from the current one (R1.7) -----------------------


def test_a_different_password_is_accepted() -> None:
    assert_password_changed("a-brand-new-passphrase", "the-old-passphrase")


def test_an_identical_password_is_refused() -> None:
    """R1.7: accepting it would revoke every session of the user without rotating anything."""
    with pytest.raises(PasswordUnchangedError):
        assert_password_changed("same-passphrase-here", "same-passphrase-here")


def test_a_password_differing_only_by_trailing_whitespace_is_a_change() -> None:
    """Exact comparison, not normalised: `verify` and `hash` treat the two as distinct
    everywhere else, so trimming here would reject a legitimate change."""
    assert_password_changed("passphrase-here ", "passphrase-here")


def test_the_comparison_is_case_sensitive() -> None:
    assert_password_changed("Passphrase-Here", "passphrase-here")


def test_the_refusal_never_echoes_the_password() -> None:
    """R4.3: the message reaches the API response and the application log."""
    secret = "the-shared-passphrase"
    with pytest.raises(PasswordUnchangedError) as caught:
        assert_password_changed(secret, secret)

    assert secret not in str(caught.value)


def test_the_rule_lives_in_the_domain_beside_its_sibling() -> None:
    """Design of section 4's fix: both password rules are named predicates in `domain/`.

    Pinned structurally because the failure mode is silent — one rule drifting back into a
    use case as a bare `if`, where the next reader cannot find it next to the other.
    """
    import app.auth.domain.password_policy as module

    assert callable(module.assert_password_changed)
    assert callable(module.assert_password_acceptable)


# --- the coupling with the generator (R1.6, design D4) -----------------------------


def test_the_generator_cannot_emit_a_password_this_policy_rejects() -> None:
    """R1.6 verbatim: the system must never reject what it itself hands out.

    This is the test design D4 asks for. Moving `TEMPORARY_PASSWORD_LENGTH` or
    `PASSWORD_MIN_LENGTH` in isolation breaks the suite here rather than in production,
    on the day an administrator creates a user.
    """
    assert TEMPORARY_PASSWORD_LENGTH >= PASSWORD_MIN_LENGTH


def test_a_batch_of_generated_passwords_all_pass_the_policy() -> None:
    """The property, not just the arithmetic behind it."""
    for _ in range(200):
        assert_password_acceptable(generate_temporary_password())


def test_the_byte_cap_is_the_hashers_own_limit() -> None:
    """R1.6: the cap exists so the hasher's refusal becomes a `422` at the boundary.

    Two independent literals say 72 — this one and `BCRYPT_MAX_PASSWORD_BYTES` in
    `app/auth/infrastructure/password_hasher.py`. If they ever drift apart the boundary
    would admit a password the hasher then refuses (an unmapped `500`) or silently
    shortens. The import lives in the test, not in the module: `domain/` must not depend
    on `infrastructure/` (`steering/backend-architecture.md`).
    """
    from app.auth.infrastructure.password_hasher import BCRYPT_MAX_PASSWORD_BYTES

    assert PASSWORD_MAX_BYTES == BCRYPT_MAX_PASSWORD_BYTES


def test_the_minimum_is_a_domain_constant_and_not_a_setting() -> None:
    """Design D4: a deployment that raised it would reject its own temporary passwords.

    Guards the constant against being turned into a `Settings` field later.
    """
    from app.core.config import Settings

    assert not any("PASSWORD_MIN" in name for name in Settings.model_fields)
