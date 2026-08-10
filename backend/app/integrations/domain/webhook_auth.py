"""The three primitives rule 12(a)/(b) of `steering/security.md` needs (design D1, D3).

In `domain/` because they are pure stdlib and because the rule they implement is a business
rule, not transport: `hmac`, `hashlib` and `secrets` bring no framework with them, so the
dependency rule of `steering/backend-architecture.md` is satisfied without ceremony. That
placement is also what lets the receiving use case be tested without FastAPI in the way
(design D5).

**Two different secrets, two different treatments, and the asymmetry is the design** (D3):

- The **token** lives in the URL path. It is stored as an unsalted SHA-256 so the lookup can be
  a `UNIQUE` index hit. Unsalted is deliberate and not an oversight: what makes a fast hash
  dangerous is low entropy in the secret, and this one is 256 bits from a CSPRNG, so there is no
  dictionary to attack. A salted bcrypt would additionally be *impossible to index*, which is
  the property the whole receiving path depends on.
- The **header secret** is stored as Fernet ciphertext (rule 3 names this exact secret), so it
  arrives here already decrypted by `app.core.crypto.decrypt` and is compared in constant time.

Why they are not the same mechanism: rule 12 notes that (a) and (b) "se sostienen mutuamente —
si el secreto se filtra queda la ruta, y si la ruta se adivina queda el secreto". Two defences
that failed the same way would collapse into one.
"""

import hashlib
import hmac
import secrets

TOKEN_ENTROPY_BYTES = 32
"""256 bits, against a floor of 128 in R1.5.

`secrets.token_urlsafe` base64url-encodes this many random bytes, so the resulting string is
longer than 32 characters — the entropy is in the bytes, not in the length of the text.
"""


def generate_webhook_token() -> str:
    """A fresh, opaque, URL-safe route token (R1.5).

    URL-safe matters concretely: this value becomes a **path segment**, so a `/` in it would
    change the shape of the route and a `+` or `=` would need escaping. `token_urlsafe` is the
    stdlib helper that already guarantees the alphabet.

    Never derived from the tenant — not from its id, its name, or a counter. A derived token is
    enumerable, and rule 12(b) asks for a route that cannot be guessed.
    """
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def generate_header_secret() -> str:
    """The value an operator pastes into the provider's panel (rule 12(a), R2.1).

    Same generator as the route token, and that is a decision rather than laziness: rule 12(a)
    requires the header value to be **distinct per tenant and never a global constant**, which is
    exactly the property `secrets.token_urlsafe` gives. URL-safe is not needed here — this one
    travels in a header — but an alphabet that survives being pasted into a web form, a `.env`
    file and a shell is worth more than the two characters it gives up.

    A separate function from `generate_webhook_token` even though the bodies match, because the
    two secrets are separate defences (see the module docstring) and one name for both is how a
    later change would end up deriving one from the other.
    """
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_webhook_token(token: str) -> str:
    """The value stored in `webhook_endpoints.token_hash`: SHA-256 hex, 64 characters.

    Deterministic on purpose — that is what makes the receiving lookup one indexed equality
    test instead of a scan over every row. See the module docstring for why unsalted is right
    here and would not be for a password.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def secrets_match(expected: str, presented: str | None) -> bool:
    """Whether the header the caller sent is the tenant's secret (R1.3, R1.4).

    Constant time via `hmac.compare_digest`, which rule 12(a) requires in those words. Never
    `==`: a short-circuiting comparison leaks the length of the matching prefix, and that leak
    *is* exploitable byte by byte, which is the difference between this comparison and the token
    lookup discussed in design D4.

    `None` — a header nobody sent — and `""` are ordinary failures rather than exceptions,
    because that is the shape the caller needs: rule 12(a) makes a missing header exactly as
    unauthenticated as a wrong one, and design D4 makes both indistinguishable to the client.

    Both sides are encoded before comparing: `compare_digest` rejects `str` arguments that are
    not ASCII-only, so a non-ASCII secret would raise instead of returning `False` — a crash
    where the answer should be "no".
    """
    if not presented:
        return False
    return hmac.compare_digest(expected.encode(), presented.encode())
