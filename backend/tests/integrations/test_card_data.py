"""The rule 13 scrubber (`app/integrations/infrastructure/card_data.py`).

Rule 13 of `steering/security.md` requires cardholder data to be **discarded** at the provider
boundary rather than encrypted, because PCI DSS forbids retaining the CVV. These tests run the
real captured payloads of both providers through it, not invented ones — the leak this closes
was found in a committed fixture, not in a hypothetical.
"""

import json
from pathlib import Path

import pytest

from app.integrations.infrastructure.card_data import (
    CARD_DATA_REMOVED,
    CARD_NEEDLES,
    MAX_DEPTH,
    OPAQUE_BRANCHES,
    TOO_DEEP_TO_SCRUB,
    scrub_card_data,
)
from tests.integrations.conftest import load_script

FIXTURES = Path(__file__).parent / "fixtures"


def test_the_needles_match_the_anonymiser_exactly():
    """Two copies of a security function drift on the first one-sided fix.

    `scripts/` is standalone and excluded from the image, so the runtime cannot import the
    anonymiser's list. What keeps them honest is this test failing.

    Pinned against the anonymiser's **named export**, not against a position or a search for
    the tuple containing `cvv`. The security panel of this section showed why: with two
    different selectors in play, a new payment family appended to `PII_PLACEHOLDERS`
    (`iban`, `pan`, `sepa`) would teach the anonymiser and leave this list and the on-disk
    fixture guard blind, with the whole suite green.
    """
    anonymise = load_script("anonymise")

    assert set(CARD_NEEDLES) == set(anonymise.CARD_NEEDLES)


def test_the_anonymiser_still_uses_that_named_list_for_its_card_family():
    """Guards the pin above from being satisfied by a constant nobody applies."""
    anonymise = load_script("anonymise")

    families = [needles for needles, _ in anonymise.PII_PLACEHOLDERS]

    assert anonymise.CARD_NEEDLES in families


@pytest.mark.parametrize(
    "key",
    [
        "card_number",
        "cardholder_name",
        "cvv",
        "cvc",
        "expiration_date",
        "expiry",
        "guarantee",
        "stripeToken",
        "pcibookingToken",
        "CARD_NUMBER",
    ],
)
def test_every_measured_card_shaped_key_is_removed(key):
    assert scrub_card_data({key: "4111111111111111"})[key] == CARD_DATA_REMOVED


def test_a_card_branch_cannot_survive_by_nesting():
    """`guarantee` loses its whole subtree, not just the leaves somebody remembered."""
    scrubbed = scrub_card_data(
        {"guarantee": {"nested": {"deeper": {"cvv": "737", "note": "keep me?"}}}}
    )

    assert scrubbed["guarantee"] == CARD_DATA_REMOVED
    assert "737" not in json.dumps(scrubbed)


def test_business_data_survives_untouched():
    """The point of `raw_payload` is showing the unexpected field, so it must stay legible."""
    payload = {"id": 90923575, "arrival": "2026-09-03", "numAdult": 1, "price": 0}

    assert scrub_card_data(payload) == payload


def test_lists_of_objects_are_scrubbed_member_by_member():
    scrubbed = scrub_card_data([{"id": 1, "cvv": "737"}, {"id": 2, "cvv": "738"}])

    assert [member["id"] for member in scrubbed] == [1, 2]
    assert all(member["cvv"] == CARD_DATA_REMOVED for member in scrubbed)


def test_the_input_is_not_mutated():
    """Adapters pass the provider's parsed body straight in and still hold it afterwards."""
    original = {"guarantee": {"cvv": "737"}}

    scrub_card_data(original)

    assert original == {"guarantee": {"cvv": "737"}}


def test_a_payload_too_deep_to_inspect_is_discarded_not_passed_through():
    """Found by the QA panel: unbounded recursion made D9's "a cualquier profundidad" false.

    Past Python's stack limit the function raised instead of scrubbing, and a `RecursionError`
    does not fail safe — `ChannexAdapter.get_reservation` has no per-element guard, so it
    propagated. Discarding what cannot be inspected is the only answer consistent with rule
    13(a).
    """
    deep = {"cvv": "737"}
    for _ in range(MAX_DEPTH + 5):
        deep = {"nested": deep}

    scrubbed = scrub_card_data(deep)

    rendered = json.dumps(scrubbed)
    assert TOO_DEEP_TO_SCRUB in rendered
    assert "737" not in rendered


def test_a_payload_nested_far_beyond_the_stack_limit_does_not_raise():
    """5000 levels: the depth the panel reproduced a `RecursionError` at."""
    deep = {"cvv": "737"}
    for _ in range(5000):
        deep = {"nested": deep}

    assert "737" not in json.dumps(scrub_card_data(deep))


def test_realistic_provider_nesting_is_untouched_by_the_bound():
    """Both providers' measured payloads nest 3-5 levels; the bound must not reach them."""
    payload = {"a": {"b": {"c": {"d": {"e": {"keep": "me"}}}}}}

    assert scrub_card_data(payload) == payload


def test_a_scalar_inside_a_list_is_left_alone():
    """A known limit of a denylist, pinned so nobody reads its absence as coverage.

    There is no key to judge these by. The fixtures — the things actually committed — go
    through the fail-closed anonymiser instead, which treats a list scalar as unnamed.

    The key here is deliberately NOT one of `OPAQUE_BRANCHES`: this test used `notes`, and when
    the security panel's fix added that to the opaque list the assertion flipped — which is the
    fix working. The limit being pinned is about *unnamed* scalars, so the key has to be one the
    scrubber has no opinion about.
    """
    assert scrub_card_data({"someList": ["4111111111111111"]})["someList"] == [
        "4111111111111111"
    ]


# The committed-fixture guard is NOT here. It lives in `test_channex_probe.py`, parametrised
# over `FIXTURE_ROOT.rglob("*.json")`, and it reads the files rather than the function — which
# is what rule 13(c) asks for. A version of it lived here and the security panel showed it was
# vacuous: running the scrubber over a fixture and then asserting the output has no unscrubbed
# card key cannot fail for any content, so it only re-tested the scrubber while wearing the name
# of the guard. Deleted rather than fixed, so nobody deletes the real one believing this covers
# it.


@pytest.mark.parametrize("key", OPAQUE_BRANCHES)
def test_opaque_provider_text_is_dropped_wholesale(key):
    """The bypass the security panel demonstrated, and it was not a hypothetical.

    Channex parses `guarantee.card_number` **out of** `raw_message`, the OTA's original message,
    which the element carries in the same breath. A key-only denylist cannot see inside a
    string, so the PAN travelled in XML one key over from its own redaction.
    """
    payload = {"attributes": {key: "<CreditCard><CardNumber>4111111111111111</CardNumber>"}}

    assert "4111111111111111" not in json.dumps(scrub_card_data(payload))


def test_opaque_keys_are_matched_exactly_not_as_substrings():
    """A substring match would empty `raw_payload` of the structure it exists to show.

    `message` as a substring takes every `messageId` and `errorMessage` a provider defines.
    """
    payload = {"messageId": 7, "errorMessage": "boom", "promotion_notes_url": "https://x/y"}

    assert scrub_card_data(payload) == payload


def test_the_real_channex_fixture_still_carries_the_raw_message_field():
    """Guards the drop above from going green because the field left the payload.

    Its committed VALUE is `***scrubbed***` — the capture-time anonymiser blanks it, which is
    precisely why the "real payloads through the real function" test could not catch this. The
    key surviving is what makes the assertion meaningful.
    """
    booking = json.loads(
        (FIXTURES / "channex" / "bookings.json").read_text(encoding="utf-8")
    )

    assert "raw_message" in json.dumps(booking)
