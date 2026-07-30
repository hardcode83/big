"""bcrypt hashing, with the 72-byte limit refused rather than truncated (R1.3, D4)."""

import pytest

from app.auth.domain.exceptions import PasswordTooLongError
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher

# Cheap rounds: the real default is 12, which would make this module crawl.
TEST_ROUNDS = 4
hasher = BcryptPasswordHasher(rounds=TEST_ROUNDS)


def _counting(original, calls: list[str], label: str):
    def wrapper(*args, **kwargs):
        calls.append(label)
        return original(*args, **kwargs)

    return wrapper


def test_a_password_verifies_against_its_own_hash() -> None:
    assert hasher.verify("correct horse", hasher.hash("correct horse")) is True


def test_a_wrong_password_does_not_verify() -> None:
    assert hasher.verify("wrong horse", hasher.hash("correct horse")) is False


def test_hashing_the_same_password_twice_gives_different_hashes() -> None:
    # Distinct salts: identical hashes would leak that two users share a password.
    assert hasher.hash("same") != hasher.hash("same")


def test_the_hash_does_not_contain_the_password() -> None:
    assert "correct horse" not in hasher.hash("correct horse")


def test_a_password_over_72_bytes_is_refused_not_truncated() -> None:
    # bcrypt silently ignores everything past 72 bytes, so accepting this would
    # mean "abc...(72)...X" and "abc...(72)...Y" are the same password (D4).
    with pytest.raises(PasswordTooLongError):
        hasher.hash("a" * 73)


def test_the_limit_counts_utf8_bytes_not_characters() -> None:
    # "é" is two bytes in UTF-8: 40 characters, 80 bytes.
    with pytest.raises(PasswordTooLongError):
        hasher.hash("é" * 40)


def test_a_72_byte_password_is_accepted() -> None:
    assert hasher.verify("a" * 72, hasher.hash("a" * 72)) is True


def test_the_too_long_error_does_not_quote_the_password() -> None:
    secret = "z" * 100

    with pytest.raises(PasswordTooLongError) as excinfo:
        hasher.hash(secret)

    assert secret not in str(excinfo.value)


def test_verifying_an_over_long_password_is_false_not_an_error() -> None:
    # At login an over-long password must be indistinguishable from a wrong one
    # (R1.4), so verification returns False instead of raising a different error.
    assert hasher.verify("a" * 200, hasher.hash("correct horse")) is False


def test_verifying_against_a_malformed_hash_is_false() -> None:
    assert hasher.verify("anything", "not-a-bcrypt-hash") is False


def test_burn_costs_one_verification_and_never_more(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cold-cache trap: `burn` must not also pay for building the dummy hash.

    Before `prewarm`, the first burn of each process did `gensalt` + `hashpw` + a
    verification — about double a real wrong-password login, which is a one-bit
    "this address does not exist" signal per process lifetime (R1.4).
    """
    from app.auth.infrastructure import password_hasher as module

    # Warm first, then start counting: that is the state every request sees, because
    # the configured cost is prewarmed at import.
    module.prewarm(TEST_ROUNDS)
    calls: list[str] = []
    monkeypatch.setattr(
        module.bcrypt, "hashpw", _counting(module.bcrypt.hashpw, calls, "hashpw")
    )
    monkeypatch.setattr(
        module.bcrypt, "checkpw", _counting(module.bcrypt.checkpw, calls, "checkpw")
    )

    hasher.burn("whatever the caller sent")

    assert calls == ["checkpw"], f"burn did {calls}, expected exactly one verification"


def test_a_cold_cost_pays_for_its_dummy_hash_once_and_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the boundary of the guarantee.

    A cost that was never prewarmed does pay for its dummy hash on first use. That
    never happens for the configured cost in production (prewarmed at import), and it
    happens at most once per cost anyway — but it is worth pinning so nobody assumes
    `burn` is free for an arbitrary cost.
    """
    from app.auth.infrastructure.password_hasher import _DUMMY_HASHES
    from app.auth.infrastructure import password_hasher as module

    cold_rounds = 5
    monkeypatch.delitem(_DUMMY_HASHES, cold_rounds, raising=False)
    cold = BcryptPasswordHasher(rounds=cold_rounds)
    calls: list[str] = []
    monkeypatch.setattr(
        module.bcrypt, "hashpw", _counting(module.bcrypt.hashpw, calls, "hashpw")
    )
    monkeypatch.setattr(
        module.bcrypt, "checkpw", _counting(module.bcrypt.checkpw, calls, "checkpw")
    )

    cold.burn("first")
    cold.burn("second")

    assert calls == ["hashpw", "checkpw", "checkpw"]


def test_the_dummy_hash_is_built_at_import_for_the_configured_cost() -> None:
    from app.auth.infrastructure import password_hasher as module
    from app.core.config import settings

    assert settings.bcrypt_rounds in module._DUMMY_HASHES


def test_hashes_are_created_with_the_configured_cost() -> None:
    """`burn` assumes the population is homogeneous — this is what makes it true.

    `hash()` is the only writer of stored hashes and always uses the configured cost,
    so the dummy hash and a real verification cost the same. Changing BCRYPT_ROUNDS on
    a populated database breaks that assumption until the hashes are rebuilt.
    """
    from app.core.config import settings

    real = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)

    assert real.hash("x").startswith(f"$2b${settings.bcrypt_rounds:02d}$")
