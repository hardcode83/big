"""The shared fail-closed anonymiser (`scripts/anonymise.py`).

`test_channex_probe.py` already exercises this policy end-to-end through the Channex probe,
including the assertion that every committed fixture is clean. What this file adds is the
part that only became testable once the policy was extracted (design D2 of
`pms-beds24-spike`): the behaviour that is **shared**, driven with a `business_keys` set that
is not any real provider's, so a regression cannot hide behind a Channex-specific allowlist.

The ordering test is the one that matters. It is not a style check — the order it pins is
what stopped card data from surviving in a committed fixture once already.
"""

import pytest

from tests.integrations.conftest import load_script

anonymise_module = load_script("anonymise")
anonymise = anonymise_module.anonymise
SCRUBBED = anonymise_module.SCRUBBED
SCRUBBED_KEY = anonymise_module.SCRUBBED_KEY

# Deliberately not any real provider's allowlist: these tests are about the shared policy.
BUSINESS_KEYS = frozenset({"status", "adults", "booking_ref"})


def test_pii_needles_beat_preserved_suffixes():
    """`expiration_date` must NOT survive on the strength of `_date`.

    This is the regression that `steering/security.md` rule 13 exists for and that the
    comment in `anonymise.py` records as having leaked into a committed fixture: `_date` is a
    preserved suffix, `expiration_date` ends in it, and the card needle only wins because the
    needle loop runs *before* the suffix check. Reordering those two re-opens the leak, and
    this test is what fails when someone does.
    """
    result = anonymise(
        {"expiration_date": "12/2027", "check_in_date": "2026-09-15"},
        business_keys=BUSINESS_KEYS,
    )

    assert result["expiration_date"] == "***card-data***"
    # The suffix still does its job for a field that no needle claims.
    assert result["check_in_date"] == "2026-09-15"


@pytest.mark.parametrize(
    "key",
    ["card_number", "cvv", "cardholder_name", "guarantee", "card_type", "expiry"],
)
def test_no_card_shaped_value_survives(key):
    """Rule 13 is not satisfied by encryption, so nothing card-shaped may reach disk."""
    result = anonymise({key: "4111111111111111"}, business_keys=BUSINESS_KEYS)

    assert "4111111111111111" not in str(result)


def test_business_keys_are_the_only_per_provider_knob():
    """A key in `business_keys` survives; the identical key without it does not."""
    payload = {"status": "confirmed", "internal_note": "confirmed"}

    with_allowlist = anonymise(payload, business_keys=BUSINESS_KEYS)
    without_allowlist = anonymise(payload, business_keys=frozenset())

    assert with_allowlist == {"status": "confirmed", "internal_note": SCRUBBED}
    assert without_allowlist == {"status": SCRUBBED, "internal_note": SCRUBBED}


def test_none_and_booleans_survive():
    """Absence and flags are not personal data, and the fixture must keep its optionality."""
    result = anonymise(
        {"cancelled_at": None, "is_closed": True, "unknown_flag": False},
        business_keys=frozenset(),
    )

    assert result == {"cancelled_at": None, "is_closed": True, "unknown_flag": False}


def test_scalars_in_a_list_are_judged_unnamed():
    """A list member must not inherit its list's key — that hole published a card number."""
    result = anonymise(
        {"charge_amount": ["4111111111111111"]},
        business_keys=frozenset({"charge_amount"}),
    )

    assert result["charge_amount"] == [SCRUBBED]


def test_a_key_that_is_itself_personal_data_is_replaced():
    """A provider that keys a map by guest email hides data where the recursion sees structure."""
    result = anonymise(
        {"guests_by_mail": {"john.smith@gmail.com": {"adults": 2}}},
        business_keys=BUSINESS_KEYS,
    )

    assert SCRUBBED_KEY in result["guests_by_mail"]
    assert "john.smith@gmail.com" not in str(result)


def test_date_shaped_keys_preserve_only_numeric_leaves():
    """Nightly rates keyed by date survive; free text under the same shape does not."""
    result = anonymise(
        {"days": {"2026-09-15": "120.00", "2026-09-16": "call Ana at +34611223344"}},
        business_keys=frozenset(),
    )

    assert result["days"]["2026-09-15"] == "120.00"
    assert "611223344" not in str(result)


def test_large_unrecognised_numbers_are_zeroed_and_small_ones_are_not():
    """The floor is what lets `adults: 2` survive while `guest_number` does not."""
    result = anonymise({"adults": 2, "guest_number": 34611223344}, business_keys=frozenset())

    assert result["adults"] == 2
    assert result["guest_number"] == 0


def test_anonymising_twice_changes_nothing_more():
    """Idempotence: re-running the capture must not degrade an already-clean payload."""
    payload = {"status": "confirmed", "guest_name": "John Smith", "adults": 2}

    once = anonymise(payload, business_keys=BUSINESS_KEYS)
    twice = anonymise(once, business_keys=BUSINESS_KEYS)

    assert once == twice
