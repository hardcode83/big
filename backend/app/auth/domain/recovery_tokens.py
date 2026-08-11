"""The recovery token and the only form of it that is allowed to be stored (R3.4, R4.1).

Pure domain: `secrets` and `hashlib` are the standard library, so `domain/` keeps the purity
`tests/test_layering.py` enforces. Same reasoning as `passwords.py` for having no port —
there is no external system and no second implementation to substitute.

**Why SHA-256 and not bcrypt** (design D1): the stored form has to be *deterministic*, or the
single conditional `UPDATE` that R3.2 requires becomes impossible — a salted hash cannot be
looked up by the presented value, so consuming a token would mean reading every candidate row
and verifying them one by one, which is exactly the read-then-write race R3.2 forbids. A slow
KDF earns its cost against low-entropy secrets; 256 bits out of `secrets` are not guessable,
so bcrypt here would only add ~250 ms of CPU to an *anonymous* endpoint — a denial-of-service
lever where there was none.
"""

import hashlib
import secrets

# 32 bytes = 256 bits, url-safe base64 encoded. Long enough that brute force is not a threat
# model, short enough to survive a mail client wrapping the link.
RECOVERY_TOKEN_BYTES = 32

# Length of a SHA-256 digest in hexadecimal. The column is `String(64)`.
RECOVERY_TOKEN_HASH_LENGTH = 64


def hash_recovery_token(token: str) -> str:
    """The stored form of a token: SHA-256, hexadecimal, lowercase.

    Deterministic on purpose — see the module docstring. The token cannot be reconstructed
    from it, which is what R4.1 asks for.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_recovery_token() -> tuple[str, str]:
    """A fresh token as `(cleartext, hash)`.

    The cleartext is returned so the caller can put it in the link it sends, and it must
    never be persisted, logged or returned by the API: the hash is the only form that
    outlives the request (R4.1, R4.3).
    """
    token = secrets.token_urlsafe(RECOVERY_TOKEN_BYTES)
    return token, hash_recovery_token(token)
