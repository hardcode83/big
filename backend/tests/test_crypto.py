"""Fernet encryption at rest (R3, design D3).

The primitive rule 3 of `steering/security.md` required from the start and that nothing
implemented until this change. What is worth asserting is not that Fernet works — it is that
the shape around it holds: ciphertext is not searchable, a wrong key is loud rather than
silently empty, and the value object does not print what it carries.
"""

import base64

import pytest

from app.core.config import FERNET_KEY_BYTES
from app.core.crypto import SecretDecryptionError, decrypt, encrypt
from app.core.encrypted_secret import EncryptedSecret

_PLAINTEXT = "beds24-refresh-token-value"
_OTHER_KEY = base64.urlsafe_b64encode(b"\x11" * FERNET_KEY_BYTES).decode()


def test_a_secret_survives_a_round_trip() -> None:
    assert decrypt(encrypt(_PLAINTEXT)) == _PLAINTEXT


def test_a_secret_with_non_ascii_survives_a_round_trip() -> None:
    # Credentials are provider-generated and usually ASCII, but nothing guarantees it and a
    # `.encode()`/`.decode()` pair that assumed so would corrupt the value silently.
    secret = "clé-de-cuenta-ñ-🔑"

    assert decrypt(encrypt(secret)) == secret


def test_encrypting_the_same_value_twice_gives_different_ciphertext() -> None:
    # Fernet embeds a random IV, which is why the column cannot be queried by value. This is
    # the property that forces callers to look a credential up by its scope key, and a change
    # to a deterministic scheme would break that assumption silently — hence the test.
    first = encrypt(_PLAINTEXT)
    second = encrypt(_PLAINTEXT)

    assert first.ciphertext != second.ciphertext
    assert decrypt(first) == decrypt(second) == _PLAINTEXT


def test_the_ciphertext_does_not_contain_the_plaintext() -> None:
    assert _PLAINTEXT not in encrypt(_PLAINTEXT).ciphertext


def test_a_tampered_ciphertext_raises_instead_of_returning_garbage() -> None:
    # Fernet is authenticated, so this is really asserting that the failure is translated
    # rather than escaping as `cryptography`'s own InvalidToken — callers must not have to
    # import the crypto library to handle a corrupt row.
    secret = encrypt(_PLAINTEXT)
    tampered = EncryptedSecret(ciphertext=secret.ciphertext[:-4] + "AAAA")

    with pytest.raises(SecretDecryptionError):
        decrypt(tampered)


@pytest.mark.parametrize(
    "not_ciphertext",
    [
        "definitely not a fernet token",
        "",
        # Valid base64url, wrong version byte — the shape a plaintext credential that happened
        # to decode would take.
        base64.urlsafe_b64encode(b"\x01plaintext-looking-secret").decode(),
        # A realistic accident: the operator's raw token, handed straight to the type.
        "beds24-refresh-token-abc123",
    ],
)
def test_a_value_that_is_not_ciphertext_cannot_even_be_CONSTRUCTED(not_ciphertext) -> None:
    """This used to test `decrypt`; now it tests the constructor, which is a stronger place.

    The security panel of sections 4-5 found that `EncryptedSecret` validated nothing, so
    `EncryptedSecret(ciphertext=token)` was a legal way to put a PLAINTEXT account credential
    into a column called `secret_encrypted` — and nothing objected: not the type, not the
    repository, not the schema, and not the "is it ciphertext?" test, which only exercises the
    path that did call `encrypt`.

    With the constructor validating, the bad value never exists, so there is nothing left for
    `decrypt` to reject. That is the difference between a contract closed by construction and one
    closed by convention — the distinction design D3 claimed and did not yet have.
    """
    with pytest.raises(ValueError):
        EncryptedSecret(ciphertext=not_ciphertext)


def test_decrypting_with_another_key_raises_rather_than_reporting_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The failure mode this guards is operational, not theoretical: after a key rotation every
    # stored credential decrypts to nothing. If that surfaced as "no credentials" the sync
    # would report zero reservations, which is indistinguishable from an empty PMS — the exact
    # confusion `specs/reservations.md` refuses elsewhere.
    secret = encrypt(_PLAINTEXT)

    from app.core import config

    monkeypatch.setattr(config.settings, "encryption_key", _OTHER_KEY)

    with pytest.raises(SecretDecryptionError):
        decrypt(secret)


def test_the_decryption_error_does_not_carry_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = encrypt(_PLAINTEXT)

    from app.core import config

    monkeypatch.setattr(config.settings, "encryption_key", _OTHER_KEY)

    with pytest.raises(SecretDecryptionError) as excinfo:
        decrypt(secret)

    message = str(excinfo.value)
    assert _PLAINTEXT not in message
    assert secret.ciphertext not in message
    assert _OTHER_KEY not in message


@pytest.mark.parametrize("render", [repr, str, lambda value: f"{value}", "{}".format])
def test_the_value_object_never_renders_its_ciphertext(render) -> None:
    # One parametrisation per way a value reaches a log line. `str` and f-strings matter
    # separately from `repr` because a dataclass defines only `__repr__`: without an explicit
    # `__str__` the fallback happens to be safe today and would stop being safe the moment
    # someone added one.
    secret = encrypt(_PLAINTEXT)

    rendered = render(secret)

    assert secret.ciphertext not in rendered
    assert _PLAINTEXT not in rendered


def test_the_value_object_is_immutable() -> None:
    secret = encrypt(_PLAINTEXT)

    with pytest.raises(Exception):
        secret.ciphertext = "replaced"  # type: ignore[misc]
