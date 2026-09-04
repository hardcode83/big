"""The webhook-auth primitive the WhatsApp receiving path uses (R3.1, R3.2; design D9, D3a).

**One re-export and not one line of new cryptography.** `secrets_match` already exists, once,
in `app/integrations/domain/webhook_auth.py`, where `reservations-webhooks` put it and where
its reasoning is written down: a constant-time comparison because rule 12(a) of
`sdd/steering/security.md` requires `hmac.compare_digest` in those words.

Restating it here would be the mistake `InboundMessageActor` is documented for avoiding: "a
fourth **application** of one rule, not a fourth statement of it". A second copy of a
comparison is how one of them ends up as `==`.

**`generate_webhook_token` and `hash_webhook_token` used to be re-exported here too, and were
dropped 2026-09-02 (design D3, task 4.6).** The webhook topology changed from one route token
and one signing secret per tenant to one shared Meta App with a single fixed webhook route for
the whole platform, tenant resolved by a `phone_number_id`-to-tenant lookup (section 6)
instead of a per-tenant route token. Under that model nothing mints or hashes a route token
for this path, so the two re-exports had no consumer. `secrets_match` is unaffected — it still
backs `MetaInboundAdapter.verify_signature`'s constant-time check of Meta's real
`X-Hub-Signature-256` (design D3a).

Why this module exists at all, then, rather than the WhatsApp receiving path importing
`app.integrations.domain.webhook_auth` directly:

* It is the **one** place that records which of the four primitives of `webhook_auth` the
  WhatsApp path is entitled to, and `generate_header_secret` is deliberately not among them.
  The WhatsApp webhook does not authenticate with a header secret — it authenticates with
  Meta's real `X-Hub-Signature-256` (design D3a: "the receiving use case verifies the real
  signature in constant time … instead of comparing a system-generated header value"), so a
  per-tenant header secret here would be a second, weaker door onto the same route. A section
  that genuinely needs it can import it from `webhook_auth` itself; it does not get in by
  being re-exported next to the one that is used.
* It keeps the cross-module import to a single line in a single file, so `git grep
  integrations.domain.webhook_auth` over `app/messaging/` answers "here, and nowhere else".

The `domain/` → `domain/` direction is the one the dependency rule allows, and
`tests/test_layering.py` enforces exactly that: only `api/`, `application/` and
`infrastructure/` of another module are out of bounds from here. `webhook_auth` imports
`hashlib`, `hmac` and `secrets` and nothing else, so nothing framework-shaped travels with it.
"""

from app.integrations.domain.webhook_auth import secrets_match

__all__ = [
    "secrets_match",
]
