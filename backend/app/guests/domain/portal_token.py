"""The opaque credential behind the guest portal (R1.1, R1.2, design D2).

In `domain/` for the reason `app/integrations/domain/webhook_auth.py` is: `hashlib` and
`secrets` bring no framework with them, so the dependency rule of
`steering/backend-architecture.md` is satisfied without ceremony, and the authorising use
case stays testable with nothing booted.

**A deliberate near-copy of `webhook_auth.py`, and the copy is the design** (D2). Both
modules solve the same problem — an anonymous surface authenticated by an opaque token that
travels in the URL path — and D2 chose to reuse that shape rather than invent a second one.
What is *not* copied is `secrets_match`: a webhook endpoint has a second, separate defence
in its header secret, whereas here the token in the path is the whole credential. That
asymmetry is why these are two modules and not one shared helper: the guest token would
otherwise inherit a header comparison that no route calls, and the next reader would have
to work out which half applies.

Stored unsalted, and that is deliberate rather than an oversight. What makes a fast hash
dangerous is low entropy in the secret, and this one is 256 bits from a CSPRNG, so there is
no dictionary to attack. A salted bcrypt would additionally be *impossible to index*, and
an index is exactly the property the authorising path depends on: it resolves the tenant
**from the hash**, before any tenant is known, so "exactly one row" has to be a `UNIQUE`
index hit.
"""

import hashlib
import secrets

TOKEN_ENTROPY_BYTES = 32
"""256 bits.

`secrets.token_urlsafe` base64url-encodes this many random bytes, so the resulting string
is longer than 32 characters — the entropy is in the bytes, not in the length of the text.
"""


def generate_guest_token() -> str:
    """A fresh, opaque, URL-safe token for one stay (R1.1).

    URL-safe matters concretely: this value becomes a **path segment** of
    `/api/v1/guest/{action}/{token}` (D1), so a `/` in it would change the shape of the
    route and a `+` or `=` would need escaping — in the route, and again in whatever link
    eventually carries it to the guest.

    Never derived from the stay — not from the reservation id, the guest, the dates, or a
    counter. A derived token is enumerable, and this surface has no second factor behind
    which an enumeration could stall: R2.1 makes the token the sole source of identity.
    """
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_guest_token(token: str) -> str:
    """The value stored in `guest_access_tokens.token_hash`: SHA-256 hex, 64 characters.

    Deterministic on purpose — that is what turns the authorising lookup into one indexed
    equality test instead of a scan over every live stay. See the module docstring for why
    unsalted is right here and would not be for a password.

    This digest is also the *only* form of the token that circulates past the authoriser:
    it is what `GuestSession` carries, what `audit_logs.actor_guest_token_hash` records
    (D11) and what lands in `incidents.reported_by_guest_token` (D15). R1.2 forbids the
    cleartext value in all three.
    """
    return hashlib.sha256(token.encode()).hexdigest()
