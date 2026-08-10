"""The recovery token generator and its stored form (R3.4, R4.1, design D1).

Asserts properties, never a fixed value — a test pinning an output would be testing a mock
of the thing whose whole point is being unpredictable (same stance as `test_passwords.py`).
"""

import re

from app.auth.domain.recovery_tokens import (
    RECOVERY_TOKEN_HASH_LENGTH,
    generate_recovery_token,
    hash_recovery_token,
)


def test_the_hash_is_a_sha256_digest_in_hexadecimal() -> None:
    _, token_hash = generate_recovery_token()
    assert len(token_hash) == RECOVERY_TOKEN_HASH_LENGTH
    assert re.fullmatch(r"[0-9a-f]{64}", token_hash)


def test_the_hash_fits_the_column() -> None:
    """`password_reset_tokens.token_hash` is `String(64)`; a longer digest would be truncated."""
    assert RECOVERY_TOKEN_HASH_LENGTH == 64


def test_two_calls_produce_different_tokens() -> None:
    tokens = {generate_recovery_token()[0] for _ in range(200)}
    assert len(tokens) == 200


def test_two_calls_produce_different_hashes() -> None:
    hashes = {generate_recovery_token()[1] for _ in range(200)}
    assert len(hashes) == 200


def test_hashing_is_deterministic() -> None:
    """This is what makes the single conditional UPDATE of R3.2 possible (design D1).

    With a salted hash the row could not be found by the presented value, and consuming a
    token would degrade into read-then-write — the race R3.2 exists to forbid.
    """
    token, token_hash = generate_recovery_token()
    assert hash_recovery_token(token) == token_hash
    assert hash_recovery_token(token) == hash_recovery_token(token)


def test_the_hash_returned_matches_hashing_the_cleartext() -> None:
    for _ in range(50):
        token, token_hash = generate_recovery_token()
        assert hash_recovery_token(token) == token_hash


def test_the_hash_does_not_contain_the_token() -> None:
    """R4.1: the stored row must not let anyone reconstruct the credential."""
    token, token_hash = generate_recovery_token()
    assert token not in token_hash
    # Nor any meaningful slice of it: a hex digest shares no substring with url-safe base64
    # of this length by anything but coincidence, so 8 characters is a real assertion.
    assert not any(token[i : i + 8] in token_hash for i in range(len(token) - 7))


def test_the_token_is_url_safe() -> None:
    """It travels inside `{FRONTEND_BASE_URL}/reset-password?token=…` unescaped."""
    for _ in range(50):
        token, _ = generate_recovery_token()
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token)


def test_the_token_carries_at_least_256_bits() -> None:
    token, _ = generate_recovery_token()
    assert len(token) >= 43  # ceil(256 / 6) base64 characters


def test_it_does_not_use_the_random_module() -> None:
    """`random` is a predictable PRNG; a credential needs `secrets` (design D1)."""
    import inspect

    import app.auth.domain.recovery_tokens as module

    source = inspect.getsource(module)
    assert "import secrets" in source
    assert not re.search(r"^import random|^from random", source, re.MULTILINE)
