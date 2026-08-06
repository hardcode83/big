"""Cardholder data dies here, at the provider boundary (`steering/security.md` rule 13).

PMS/Channel Managers hand over card data nobody asked for. MEASURED against two real APIs:
**every** Channex OTA booking carries a `guarantee` object with `card_number`, `card_type`,
`cvv`, `cardholder_name` and `expiration_date` (`specs/pms-channex-staging.md`), and a Beds24
booking carries `stripeToken` and `pcibookingToken` — `null` on the measurement account, which
has no channels and therefore no payments, but present in the schema (`docs/beds24-spike.md`).

Rule 13(a) is the part that makes this module exist instead of a column type: **these are not
encrypted, they are discarded.** PCI DSS forbids retaining the CVV after authorisation, so
"Fernet at rest" — rule 3's answer to everything else — is the wrong answer here. An adapter
that brings them into memory and lets them die there complies; one that stores them
"encrypted" does not.

**What this replaces is an omission, not a defence.** Before this module, rule 13 held because
`raw_payload` (`domain/dtos.py`) lives only in memory, no consumer reads it and no column
stores it — while `channex/mapping.py` put the provider's element into it whole, `guarantee`
and all, with a test pinning that behaviour. Rule 13(b) names that field as *the* trap: the
day a change persists it, card data reaches the database and no other rule stops it. An
omission is not a guarantee.

**Denylist, and that is a deliberate exception to this repo's fail-closed habit**
(`pms-beds24-adapter` design D9, confirmed by Jose at the design gate as the one place this
change departs from it). The fail-closed alternative — an allowlist, the policy
`scripts/anonymise.py` applies to fixtures — would leave `raw_payload` blind to exactly the
unexpected field it exists to show, which is its only purpose. The cost is that an unforeseen
needle passes; what covers that is the fixture guard reading the files on disk, plus the tests
that run the real captured payloads through this function.

The needle list is duplicated from `scripts/anonymise.py` on purpose and pinned by a test
(`test_card_data.py`) that fails if the two drift. `scripts/` is standalone and excluded from
the image, so importing across is not available; a shared list nobody checks is how two copies
of a security function diverge on the first one-sided fix.
"""

from typing import Any

CARD_DATA_REMOVED = "***card-data-removed***"
"""What replaces a card-shaped value.

A constant, never anything derived from the value it replaced. Keeping the key with a marker
rather than deleting it outright is what lets a reader of `raw_payload` tell "the provider did
not send this" from "we removed it" — the distinction that whole field exists for.
"""

TOO_DEEP_TO_SCRUB = "***too-deep-to-scrub***"
"""What replaces a subtree nested deeper than `MAX_DEPTH`.

**Fail-closed at exactly the point the denylist stops being able to look.** Found by the QA
panel of section 2: this function recursed without a bound, so D9's "a cualquier profundidad"
was true only until Python's stack ran out — around depth 1000 standalone, and lower inside an
async server whose frames are already on the stack. A `RecursionError` there does not fail
safe: in `ChannexAdapter.get_reservation`, which has no per-element guard, it propagates
instead of returning a DTO, and in any future caller it could surface after the payload had
already been handed on.

Discarding what cannot be inspected is the only answer consistent with rule 13(a). A payload
nesting 50 levels is not a booking; both providers' measured payloads nest 3-5.
"""

MAX_DEPTH = 50

CARD_NEEDLES: tuple[str, ...] = (
    "card",
    "cvv",
    "cvc",
    "expiration",
    "expiry",
    "token",
    "guarantee",
)
"""Substrings that make a key card- or payment-credential-shaped, matched case-insensitively.

Identical to the card family in `scripts/anonymise.py`'s `PII_PLACEHOLDERS`, and pinned to it
by test. `token` covers Beds24's `stripeToken`/`pcibookingToken`; `guarantee` covers Channex's
whole object in one move, which matters because its members (`card_number`, `cvv`) would each
be caught anyway but its *shape* may change.
"""

OPAQUE_BRANCHES: tuple[str, ...] = (
    # Channex: the OTA's ORIGINAL message, which is what the provider parses `guarantee` out of.
    "raw_message",
    # Beds24: free text an OTA, a guest or an operator can put anything into.
    "notes",
    "comments",
    "message",
    "groupnote",
    "custom1",
    "custom2",
    "custom3",
    "custom4",
    "custom5",
    "custom6",
    "custom7",
    "custom8",
    "custom9",
    "custom10",
)
"""Keys whose VALUE is opaque provider text, dropped from `raw_payload` wholesale.

**This is the second category, and it exists because a key-only denylist cannot see inside a
string.** Found by the security panel of section 2, with evidence rather than by argument:
`docs/channex-staging.md` records that a Channex booking carries `attributes.raw_message` — *the
original message from the OTA* — and `guarantee.card_number` is what Channex parses **out of
it**. So the element that has its `guarantee` neatly redacted carries the same PAN, in XML, one
key over. `raw_message` matches no card needle and travelled whole.

That is **not** the risk D9 accepted. D9 accepts that "una aguja no prevista pasa" — an
*unforeseen key*. This one is foreseen, measured and documented, and the design's own stated
mitigation could not see it: the capture-time anonymiser blanks `raw_message`, so the test that
runs "real captured payloads through the real function" was green by construction on the single
field that defeated it.

Dropped wholesale rather than pattern-matched for card numbers: detecting a PAN inside free text
needs a Luhn check with real false positives (a 16-digit booking reference), and `raw_payload`
is a diagnostic field — losing an opaque blob from it costs far less than a wrong guess in
either direction.

**Scope note**: this governs `raw_payload` only. Where a mapping deliberately promotes provider
free text into a DTO field that gets persisted — `special_requests` — the question is different
and open; see the third security finding in `BLOCKED.md`.
"""


def scrub_card_data(payload: Any, _depth: int = 0) -> Any:
    """A copy of `payload` with every card-shaped branch replaced by `CARD_DATA_REMOVED`.

    Recurses through dicts and lists. A key matching a needle loses **its whole subtree**, so a
    `guarantee` object does not survive by nesting its `cvv` one level deeper.

    Below `MAX_DEPTH` the subtree is replaced wholesale with `TOO_DEEP_TO_SCRUB` rather than
    inspected — see that constant for why a bound is required rather than nice to have.

    A scalar inside a list is left alone: it has no key to judge it by, and blanking unnamed
    scalars would gut the payload this function exists to preserve. That is a real limit of a
    denylist and it is why the fixtures — which are what actually get committed — go through
    the fail-closed anonymiser instead.

    Returns a new structure; the input is never mutated. Adapters hand the provider's parsed
    body straight in, and mutating it would change what the caller still holds.
    """
    if _depth >= MAX_DEPTH:
        return TOO_DEEP_TO_SCRUB
    if isinstance(payload, dict):
        return {
            key: CARD_DATA_REMOVED
            if _is_card_shaped(key) or _is_opaque(key)
            else scrub_card_data(value, _depth + 1)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [scrub_card_data(member, _depth + 1) for member in payload]
    return payload


def _is_card_shaped(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(needle in lowered for needle in CARD_NEEDLES)


def _is_opaque(key: Any) -> bool:
    """Matched EXACTLY, unlike the card needles, which are substrings.

    A substring match would take `notes` into `promotion_notes_url` and, worse, `message` into
    every `messageId` and `errorMessage` a provider defines — emptying `raw_payload` of the
    structure it exists to show. The card needles earn substring matching because a key
    *containing* `card` is card-shaped whatever surrounds it; these are specific measured
    fields.
    """
    return isinstance(key, str) and key.strip().lower() in OPAQUE_BRANCHES
