"""The pure authentication primitives of rule 12(a)/(b) (`reservations-webhooks` R1, D1, D3).

Written before the implementation, as `steering/testing.md` requires for `domain/` with a real
invariant: these are three functions of pure Python and the invariants — non-guessability,
indexability, constant-time comparison — are exactly what rule 12 spells out.
"""

import hashlib
import inspect
import uuid
from datetime import UTC, datetime

import pytest
from app.core.crypto import encrypt
from app.integrations.domain.entities import WebhookEndpoint
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.webhook_auth import (
    TOKEN_ENTROPY_BYTES,
    generate_webhook_token,
    hash_webhook_token,
    secrets_match,
)


def test_a_generated_token_carries_at_least_128_bits_of_entropy() -> None:
    """R1.5. The requirement names 128 bits as the floor; the constant is well above it."""
    assert TOKEN_ENTROPY_BYTES * 8 >= 128


def test_two_generated_tokens_are_never_equal() -> None:
    """R1.5, the cheap smoke test for "not derived from anything enumerable".

    A thousand draws is not a randomness test — it cannot be, in a unit suite — but it does
    catch the realistic regression, which is someone replacing the CSPRNG with something
    seeded, counted or derived from a tenant id.
    """
    assert len({generate_webhook_token() for _ in range(1000)}) == 1000


def test_the_token_is_url_safe() -> None:
    """It travels as a path segment, so a `/` or a `+` in it would change the route."""
    for _ in range(100):
        token = generate_webhook_token()
        assert "/" not in token
        assert "+" not in token
        assert "=" not in token


def test_hashing_is_deterministic_so_the_lookup_can_be_an_index() -> None:
    """D3: the unsalted hash is what makes an O(1) UNIQUE index lookup possible."""
    token = generate_webhook_token()
    assert hash_webhook_token(token) == hash_webhook_token(token)


def test_the_hash_is_sha256_hex_and_fits_the_column() -> None:
    token = generate_webhook_token()
    digest = hash_webhook_token(token)
    assert digest == hashlib.sha256(token.encode()).hexdigest()
    assert len(digest) == 64


def test_different_tokens_hash_differently() -> None:
    assert hash_webhook_token("a") != hash_webhook_token("b")


def test_the_hash_does_not_contain_the_token() -> None:
    """The whole point of storing the hash: a table dump must not hand over the route."""
    token = generate_webhook_token()
    assert token not in hash_webhook_token(token)


def test_secrets_match_accepts_the_right_value() -> None:
    assert secrets_match("s3cret", "s3cret") is True


def test_secrets_match_rejects_a_wrong_value() -> None:
    assert secrets_match("s3cret", "other") is False


def test_secrets_match_rejects_a_value_of_the_same_length() -> None:
    """The interesting negative: same length, so only the content differs."""
    assert secrets_match("aaaaaa", "aaaaab") is False


def test_secrets_match_rejects_a_missing_header() -> None:
    """R1.3: an absent header is a failure, not an exception and not a pass.

    `None` is what FastAPI hands over for a header nobody sent, so this is the realistic input
    and not a defensive extra.
    """
    assert secrets_match("s3cret", None) is False


def test_secrets_match_rejects_an_empty_header() -> None:
    assert secrets_match("s3cret", "") is False


def test_secrets_match_is_constant_time_by_construction() -> None:
    """R1.4, checked by reading the source rather than by timing.

    A timing assertion in a unit suite is flaky by nature — the measurement is dominated by
    scheduling noise — so what this pins is the thing that actually regresses: someone
    replacing `hmac.compare_digest` with `==`. The same tactic the repo already uses to pin
    `card_data.py`'s needle list against the anonymiser's.
    """
    source = inspect.getsource(secrets_match)
    assert "compare_digest" in source
    assert "==" not in source.split('"""')[-1]


def test_secrets_match_handles_non_ascii_without_raising() -> None:
    """`hmac.compare_digest` refuses `str` with non-ASCII, so the encode has to happen first."""
    assert secrets_match("contraseña", "contraseña") is True
    assert secrets_match("contraseña", "contrasena") is False


def _endpoint(**overrides: object) -> WebhookEndpoint:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "provider": PMSProvider.BEDS24,
        "token_hash": hash_webhook_token(generate_webhook_token()),
        "header_name": "X-Beds24-Secret",
        "header_secret": encrypt("s3cret"),
        "rotated_at": None,
    }
    defaults.update(overrides)
    return WebhookEndpoint(**defaults)  # type: ignore[arg-type]


def test_an_endpoint_holds_ciphertext_and_offers_no_way_back() -> None:
    """Rule 3(a): the entity must not be a route to cleartext.

    Same contract `PmsCredential` already has — decrypting is an explicit call to
    `app.core.crypto.decrypt`, which is the single chokepoint an audit row can attach to.
    """
    endpoint = _endpoint()
    assert not hasattr(endpoint, "reveal")
    assert not hasattr(endpoint, "plaintext")
    assert "s3cret" not in repr(endpoint)


def test_an_endpoint_rejects_an_empty_token_hash() -> None:
    with pytest.raises(ValueError, match="token_hash"):
        _endpoint(token_hash="")


def test_an_endpoint_rejects_a_token_hash_that_is_not_a_sha256_digest() -> None:
    """A `String(64)` column will take anything of the right length; the type will not.

    The realistic accident is storing the **token** here instead of its hash, which would
    defeat D3 entirely and which no column constraint would notice.
    """
    with pytest.raises(ValueError, match="token_hash"):
        _endpoint(token_hash=generate_webhook_token())


def test_an_endpoint_rejects_an_empty_header_name() -> None:
    """Rule 12(a) authenticates *by* that header; without a name there is nothing to read."""
    with pytest.raises(ValueError, match="header_name"):
        _endpoint(header_name="")


def test_an_endpoint_rejects_a_blank_header_name() -> None:
    with pytest.raises(ValueError, match="header_name"):
        _endpoint(header_name="   ")


def test_a_rotated_endpoint_keeps_its_rotation_instant() -> None:
    at = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    assert _endpoint(rotated_at=at).rotated_at == at
