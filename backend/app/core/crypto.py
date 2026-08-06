"""Fernet encryption for secrets that live in the database rather than the environment.

This is the primitive rule 3 of `sdd/steering/security.md` has always required and that no
code implemented: before this change `git grep -i fernet` over `backend/` returned nothing,
while three columns already carried an `_encrypted` suffix with plain text behind it. Those
three are deliberately NOT converted here (see the change's proposal, "Out of scope"): what
this module exists for is the credential columns of `pms_credentials`, which ADR 0006
decision 7 requires encrypted *from the migration that creates them*.

Why the plaintext never becomes a type of its own: `decrypt` returns `str` and the caller is
expected to use it and drop it. The asymmetry is the point — `encrypt` takes cleartext and
gives back a value object you cannot read, `decrypt` is an explicit call at a single
chokepoint. Rule 3(a) forbids serialising a decrypted credential anywhere, and obligation 4
of ADR 0006 requires auditing every read; both need one place to enforce, which a column type
that decrypted itself on every SELECT would not have.

Not a `TypeDecorator` (design D3), even though that is the obvious SQLAlchemy shape: it would
decrypt on load, which is exactly how a credential reaches a response body, and it would
leave no call to audit.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.encrypted_secret import EncryptedSecret


class SecretDecryptionError(RuntimeError):
    """A stored ciphertext could not be decrypted with the configured key.

    Translated from `cryptography`'s `InvalidToken` so callers never import the crypto library
    to handle a failure — the same reason `PmsUnavailableError` exists for the PMS port.

    Reaching this means the row was written with a different key, or was corrupted, or was
    tampered with. All three are operational faults that must surface loudly: there is no
    sensible fallback, and "treat it as absent" would silently turn a rotated key into
    "this property has no credentials" and then into a sync that reports zero reservations.

    The message never includes the ciphertext, the key, or the plaintext.
    """


def _cipher() -> Fernet:
    # Built per call rather than cached at import: `Settings` is a module-level singleton
    # validated at import time, but tests monkeypatch `settings.encryption_key`, and a cipher
    # captured at import would ignore them and silently test the wrong key.
    return Fernet(settings.encryption_key.strip().encode())


def encrypt(plaintext: str) -> EncryptedSecret:
    """Encrypt a secret for storage.

    Two calls with the same input produce different ciphertext (Fernet embeds a random IV),
    which is why an encrypted column cannot be searched by value — callers look credentials
    up by their scope key, never by the secret.
    """
    return EncryptedSecret(ciphertext=_cipher().encrypt(plaintext.encode()).decode())


def decrypt(secret: EncryptedSecret) -> str:
    """Return the cleartext of a stored secret. The only function in the system that does.

    Every call site is a place where obligation 4 of ADR 0006 applies, so keep them few and
    keep them where an audit row can be written.
    """
    try:
        return _cipher().decrypt(secret.ciphertext.encode()).decode()
    except InvalidToken as error:
        raise SecretDecryptionError(
            "stored secret could not be decrypted: wrong ENCRYPTION_KEY, or the value was "
            "corrupted or tampered with"
        ) from error
