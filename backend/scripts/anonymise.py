"""Fail-closed anonymiser for captured provider payloads, shared by the probe scripts.

Extracted from `channex_probe.py` when `pms-beds24-spike` needed the same policy for a
second provider (design D2 of that change). Duplicating it was the alternative and it is
exactly how two copies of a security function drift: every finding encoded in the comments
below was paid for once, by a reviewer or by a leak into a committed fixture, and a second
copy would inherit them on the day it was written and lose them on the first fix applied to
only one side.

**Only the business-key allowlist is per provider.** It arrives as `business_keys`, because
the field names of one provider say nothing about another's. Everything else here —
the PII needles, the two shape-based judgements, the identifying-number floor, the
preserved suffixes — is a judgement about the domain, not about a vendor, and stays shared.

**The order of the checks is the contract.** In `_Anonymiser.leaf` it runs:

    business_keys (exact) -> date-shaped key -> PII needles -> preserved suffixes -> scrub

The needles running *before* the suffixes is the only thing stopping `expiration_date` from
surviving on the strength of `_date` — card data that leaked into a committed fixture once
already. Reordering these is not a refactor.

Note the corollary for `business_keys`: it is checked *first*, so a provider allowlisting a
card-shaped field name would defeat the needles. Allowlist business data, never a field
whose value you would not publish.
"""

import re
from dataclasses import dataclass
from typing import Any

SCRUBBED = "***scrubbed***"
SCRUBBED_KEY = "***scrubbed-key***"

# Shape-based preservation, deliberately narrow.
#
# `_at` and `_id` were here and came out. `_at` was meant for timestamps but matched
# `contact_at: "ana@hotmail.es"`; `_id` was meant for `room_type_id` but matched
# `national_id: "12345678Z"` and `tax_id` — an identity document waved through by a suffix
# that looks structural. Every identifier a mapping needs should be in `business_keys` by
# exact name, so the suffix bought nothing and cost that.
#
# No `_code` either: it would wave `postal_code` through, and an address is personal data.
PRESERVED_SUFFIXES = ("_date", "_count", "_price", "_amount")

# A dict KEY is structure, not data — except when a provider keys a map BY a personal datum
# (`{"guests_by_mail": {"john.smith@gmail.com": {...}}}`), which the recursion used to copy
# verbatim. This is one of two places that judge by shape rather than by a name we recognise,
# because there is no name to recognise.
#
# Identifier-ish keys pass, which has to include UUID keys — they start with a digit half the
# time, so requiring a leading letter (as the first attempt did) scrubbed them. What does not
# pass: an `@`, a space, or a long run of digits that could be a document number.
_IDENTIFIER_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")

# Channex keys nightly rates BY DATE: `rooms[].days = {"2026-09-15": "120.00", ...}`. The key
# is data-shaped, so no name-based allowlist can ever cover the value under it — the first
# capture with real bookings came back with every nightly rate scrubbed. A date is not
# personal data and the price under it is exactly what the mapping reads, so a date-shaped key
# preserves its leaf. Kept shared rather than made per-provider: keying by date is a common
# PMS idiom, and the branch is inert on a payload that does not use it.
_DATE_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The second shape-based judgement, for numbers under a key no allowlist predicted. Zeroing
# every one of them destroys the fixture (`adults: 2`, `nights: 3` are exactly the business
# data the mapping needs), and keeping every one of them publishes `guest_number:
# 34611223344`. The discriminator is magnitude: identifying numbers in this domain are long
# — phone numbers run 9-12 digits, a DNI is 8 — while occupancy counts and money in euros
# for a two-flat portfolio do not reach seven figures.
IDENTIFYING_NUMBER_FLOOR = 1_000_000

CARD_NEEDLES: tuple[str, ...] = (
    "card",
    "cvv",
    "cvc",
    "expiration",
    "expiry",
    "token",
    "guarantee",
)
"""The card family, as a NAMED export rather than a position in the tuple below.

Three consumers read it — this module, the runtime scrubber
(`app/integrations/infrastructure/card_data.py`) and the committed-fixture guard in
`test_channex_probe.py` — and before this constant they used **two different selectors**: one
searched for the tuple containing `cvv`, the other took `PII_PLACEHOLDERS[0][0]` positionally.
Nothing asserted the two resolved to the same thing, so a new payment family appended below
(`iban`, `pan`, `sepa` — plausible the day a provider carries direct payments) would teach the
anonymiser and leave the other two blind, with the whole suite green. Found by the security
panel of `pms-beds24-adapter` section 2.

The comment below still says card data comes first, and that ordering still matters for the
needles-before-suffixes contract — but nothing now *depends* on the position.
"""

PII_PLACEHOLDERS: tuple[tuple[tuple[str, ...], str], ...] = (
    # **Card data, first in the list and it has to be.** Channex returns a `guarantee` object on
    # OTA bookings with `card_number`, `card_type`, `cvv`, `cardholder_name` and
    # `expiration_date` — real cardholder data, from Booking.com. The needles below caught the
    # first four, and `expiration_date` **leaked into a committed fixture** because it ends in
    # `_date` and `_date` is a preserved suffix. Needles run before suffixes, so putting the card
    # family here is what closes it. Nothing card-shaped is ever worth keeping in a fixture.
    #
    # `steering/security.md` rule 13 makes this non-negotiable for every provider, not just the
    # one it was measured on: PCI DSS forbids retaining the CVV, so scrubbing is not a courtesy.
    (CARD_NEEDLES, "***card-data***"),
    # `mail`, not `email`: Channex names the guest address `mail` inside `customer`, and a
    # needle of "email" misses it. The substring also covers `email`, so this is strictly the
    # wider of the two. Caught by the "no original value survives" assertion in
    # `test_channex_probe.py` — which is exactly why that assertion is written over the whole
    # serialised document instead of field by field.
    (("mail",), "guest@example.invalid"),
    (("phone", "mobile", "telephone"), "+34600000000"),
    (("document", "passport", "dni", "nif", "id_card"), "X0000000X"),
    (("birth", "dob"), "1990-01-01"),
    (("address", "street", "city", "zip", "postal", "region", "country"), "Redacted"),
    (("name",), "Test Guest"),
)


def anonymise(payload: Any, *, business_keys: frozenset[str]) -> Any:
    """Strip every personal datum from a captured payload, preserving shape and types.

    **Fail-closed.** The first version was a key denylist: match a needle, replace it; pass
    everything else through. Two ways that leaks, both demonstrated by reviewers rather than
    imagined:

    1. A key nobody thought of — `special_request`, `notes`, `address`, `birth_date` — goes
       to a versioned fixture verbatim, and guests routinely type a surname or a phone
       number into free text. A denylist can only ever know the fields somebody remembered.
    2. A capture can be pointed at an endpoint whose keys were never considered at all,
       including credential- or card-shaped ones.

    So the default is inverted: a string leaf survives only if its key is recognised
    business data (`business_keys` / `PRESERVED_SUFFIXES`). Everything else becomes
    `SCRUBBED`, and the PII needles remain as an explicit layer so the intent stays readable
    and the placeholders keep a realistic shape.

    The failure mode is **visible instead of silent**: over-scrubbing a field the mapping
    actually needs shows up as `***scrubbed***` in a failing mapping test, whereas
    under-scrubbing used to show up as personal data in git history forever. That is what
    makes it safe to start a new provider with an incomplete `business_keys` and widen it
    after reading the first real capture.

    Fail-closed applies to **all three** places a value can hide, which the first attempt at
    this got wrong and a security panel measured:

    - string leaves -> `SCRUBBED`;
    - **numeric leaves** -> zeroed, keeping the type. The earlier version argued "anything
      personal that arrives as a number does so under a PII key" and that was simply untrue:
      `guest_number: 34611223344` under an unfamiliar key sailed through;
    - **dict keys** -> a non-identifier-shaped key is replaced, because a provider that keys
      a map by guest email hides data in a position the recursion treats as structure.

    `None` and booleans stay as they are: absence and flags are not personal data, and the
    fixture has to keep exercising the same optionality the real payload has.
    """
    return _Anonymiser(business_keys).value(None, payload)


@dataclass(frozen=True)
class _Anonymiser:
    """Carries the per-provider allowlist through the recursion.

    A class rather than a threaded argument only because the three methods are mutually
    recursive and `business_keys` is invariant across the whole walk.
    """

    business_keys: frozenset[str]

    def value(self, key: str | None, value: Any) -> Any:
        if isinstance(value, dict):
            # Scrubbed keys are disambiguated, because two different personal-datum keys under
            # the same parent both collapse to `SCRUBBED_KEY` and the second would overwrite
            # the first — silently deleting a whole entry from the fixture, with nothing left
            # to show it existed. A provider that keys bookings by guest email
            # (`{"a@x.com": {...}, "b@x.com": {...}}`) would publish one booking and lose the
            # other, and the capture's own substituted-keys report would still list both.
            # Losing data is a safe direction for privacy and a terrible one for a fixture.
            cleaned: dict[Any, Any] = {}
            for member_key, member in value.items():
                new_key = self.key(member_key)
                if new_key in cleaned and new_key in (SCRUBBED_KEY, SCRUBBED):
                    suffix = 2
                    while f"{new_key}#{suffix}" in cleaned:
                        suffix += 1
                    new_key = f"{new_key}#{suffix}"
                cleaned[new_key] = self.value(member_key, member)
            return cleaned
        if isinstance(value, list):
            # **A scalar inside a list is treated as UNNAMED** — `key=None` — so it falls straight
            # to the fail-closed default. Dicts and nested lists keep recursing and are judged by
            # their own keys as usual.
            #
            # This is the third version of this branch and the first that closes the class rather
            # than instances. The first returned scalars untouched. The second made them inherit
            # the list's key, which fixed `special_requests` but left the same hole open for every
            # key the allowlist happened to accept: it still let
            # `{"charge_amount": ["4111111111111111"]}` publish a card number verbatim, because
            # `_amount` is a preserved *suffix* — and `{"2026-09-05": ["John Smith"]}` through the
            # date-key branch, in a provider that keys data by date. A test that pins five key
            # names cannot catch the sixth; removing the name from the decision can.
            #
            # Numbers inside a list still survive on their own merit, below the identifying floor.
            return [
                self.value(key, member) if isinstance(member, (dict, list))
                else self.leaf(None, member)
                for member in value
            ]
        return self.leaf(key, value)

    def key(self, key: str) -> str:
        if not isinstance(key, str) or not _IDENTIFIER_KEY.match(key):
            return SCRUBBED_KEY
        # A date key is structure, and it has to be checked BEFORE the digit heuristic below —
        # `2026-09-05` stripped of separators is `20260905`, eight digits, so the phone/document
        # check ate every nightly-rate key. Caught by its own test and by the fixture idempotency
        # check, which is what that check is for.
        if _DATE_KEY.match(key):
            return key
        # A long run of digits used as a key: could be a document or phone number. Separators are
        # stripped first, so `34-611-223-344` is caught as well as `34611223344`.
        bare = re.sub(r"[-. ]", "", key)
        if bare.isdigit() and len(bare) >= 7:
            return SCRUBBED_KEY
        # The pre-extraction version continued with three more branches here — allowlist hit,
        # preserved suffix, PII-needle hit — and every one of them returned `key`, as did the
        # fallthrough. They were no-ops that read like decisions. Dropped rather than moved:
        # behaviour is identical (a key surviving the two checks above is always kept), and
        # leaving them would suggest the key allowlist does something it does not. What judges a
        # key is shape only; what judges the value under it is `leaf`.
        return key

    def leaf(self, key: str | None, value: Any) -> Any:
        """Judge one scalar by the key it sits under — a dict entry's key, or its list's key."""
        if value is None or isinstance(value, bool):
            return value

        lowered = key.lower() if isinstance(key, str) else ""
        if lowered in self.business_keys:
            return value
        # A date-shaped key preserves its value **only if that value is a number**. The branch
        # exists for nightly rates, whose values are decimal price strings, and it used to
        # preserve *any* scalar — so `{"2026-09-05": "call Ana at +34611223344"}` survived
        # verbatim. Same move as the list fix: take the position out of the decision for value
        # types it was never meant to cover.
        if _DATE_KEY.match(lowered) and _looks_numeric(value):
            return value

        for needles, placeholder in PII_PLACEHOLDERS:
            if any(needle in lowered for needle in needles):
                if isinstance(value, str):
                    return placeholder
                return type(value)(0)

        if lowered.endswith(PRESERVED_SUFFIXES):
            return value
        if isinstance(value, str):
            return SCRUBBED if value else value
        # An unrecognised numeric leaf: zeroed only if it is large enough to be identifying (see
        # `IDENTIFYING_NUMBER_FLOOR`). Blanket zeroing was tried and reverted — it emptied
        # `adults` and `nights`, which is the fixture's whole point.
        if isinstance(value, (int, float)) and abs(value) >= IDENTIFYING_NUMBER_FLOOR:
            return type(value)(0)
        return value


def _looks_numeric(value: Any) -> bool:
    """A number, or a string that is only one — `"120.00"`, not `"call Ana at 611223344"`."""
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    return re.fullmatch(r"-?\d+(\.\d+)?", value.strip()) is not None
