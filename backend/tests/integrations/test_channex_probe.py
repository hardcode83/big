"""The anonymiser of the capture script (R4.2, task 2.2).

Loaded by path rather than imported: `backend/scripts/` is deliberately NOT a package
(design D9 keeps the throwaway probe out of the deployed distribution), so there is no
`scripts.channex_probe` to import. One `importlib` helper is the price of that decision.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from tests.integrations.conftest import FIXTURE_DIR  # noqa: E402

_PROBE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "channex_probe.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("channex_probe", _PROBE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


REAL_PAYLOAD = {
    "meta": {"total": 1, "page": 1, "limit": 10},
    "data": [
        {
            "type": "booking",
            "id": "8ab4b6ac-1f0d-4e1a-9d1e-0f7a2b3c4d5e",
            "attributes": {
                "unique_id": "BDC-4592817364",
                "guest_name": "John Smith",
                "customer": {
                    "name": "John Smith",
                    "surname": "Smith",
                    "mail": "john.smith@gmail.com",
                    "phone": "+34612345678",
                    "document_number": "12345678Z",
                },
                "occupancy": {"adults": 2, "children": 0},
                "arrival_date": "2026-08-10",
                "currency": "EUR",
                "ota_commission": "52.50",
                "special_request": None,
                "rooms": [
                    {"guest_name": "María García", "email": "maria@hotmail.es"},
                ],
            },
        }
    ],
}


def test_replaces_every_personal_data_leaf():
    cleaned = probe.anonymise(REAL_PAYLOAD)
    serialised = json.dumps(cleaned, ensure_ascii=False)

    # The assertion that matters: no original value survives ANYWHERE, at any depth.
    for leaked in (
        "John Smith",
        "Smith",
        "john.smith@gmail.com",
        "+34612345678",
        "12345678Z",
        "María García",
        "maria@hotmail.es",
    ):
        assert leaked not in serialised


def test_preserves_shape_and_types():
    cleaned = probe.anonymise(REAL_PAYLOAD)
    attributes = cleaned["data"][0]["attributes"]

    assert cleaned["meta"] == {"total": 1, "page": 1, "limit": 10}
    assert attributes["occupancy"] == {"adults": 2, "children": 0}
    assert attributes["arrival_date"] == "2026-08-10"
    assert attributes["currency"] == "EUR"
    assert attributes["ota_commission"] == "52.50"
    assert isinstance(attributes["customer"], dict)
    assert isinstance(attributes["rooms"], list)
    assert isinstance(attributes["customer"]["name"], str)


def test_keeps_null_and_non_string_leaves_untouched():
    """A `None` must stay `None`, or the fixture stops exercising the optional branches.

    R2.4 requires the mapping to leave absent provider fields as `None`; a fixture where
    the anonymiser had helpfully filled every hole in would never reach those branches.
    """
    cleaned = probe.anonymise(REAL_PAYLOAD)
    attributes = cleaned["data"][0]["attributes"]

    assert attributes["special_request"] is None
    assert attributes["occupancy"]["children"] == 0
    assert cleaned["data"][0]["id"] == "8ab4b6ac-1f0d-4e1a-9d1e-0f7a2b3c4d5e"


def test_identifiers_are_not_treated_as_personal_data():
    """`unique_id` is the reservation identity (design D7), not a personal datum.

    Scrubbing it would break every mapping test that asserts idempotency by
    `(tenant_id, external_pms_id)`.
    """
    cleaned = probe.anonymise(REAL_PAYLOAD)
    assert cleaned["data"][0]["attributes"]["unique_id"] == "BDC-4592817364"


@pytest.mark.parametrize(
    "argument",
    [
        "--api-key=abc123",
        f"{probe.API_KEY_ENV}=abc123",
        # The two shapes the security panel showed slipping past a spelling-based guard:
        # a bare positional key, and a flag nobody thought to blocklist.
        "uU08XiMgk8a7CrY4xUjAReUIuTrn83R123adaVb8Tf",
        "--key=uU08XiMgk8a7CrY4xUjAReUIuTrn83R123adaVb8Tf",
        "definitely-not-an-endpoint",
    ],
)
def test_refuses_every_unrecognised_argument(argument):
    """R4.4: shape-based refusal, not a list of spellings somebody has to keep current."""
    with pytest.raises(SystemExit) as excinfo:
        probe.main([argument])
    assert "unrecognised argument" in str(excinfo.value)


def test_never_echoes_the_value_of_a_refused_argument():
    """R2.3 applies to this script's own output.

    The refused token may BE the credential, so the message names what is accepted and
    never what was passed — the previous version printed it verbatim to stderr, putting the
    key in a terminal transcript on top of the shell history.
    """
    secret = "uU08XiMgk8a7CrY4xUjAReUIuTrn83R123adaVb8Tf"
    with pytest.raises(SystemExit) as excinfo:
        probe.main([secret])
    assert secret not in str(excinfo.value)


def test_known_capture_names_are_accepted_by_the_guard():
    """The guard must not reject legitimate use — otherwise the script is unusable."""
    for name in probe.CAPTURES:
        probe._reject_credential_arguments([name])
    probe._reject_credential_arguments(["--capture=messages=/messages"])


# --- Fail-closed anonymisation (both PII findings of the section-3 panel) ---


def test_scrubs_free_text_and_address_fields_nobody_listed():
    """R4.2 — "todo dato personal", which a key denylist can never deliver.

    Guests type surnames, phones and emails into free-text fields, and an address is
    personal data. Under the old denylist all of this reached a versioned fixture verbatim.
    """
    payload = {
        "attributes": {
            "special_request": "Please call my wife Ana at +34611223344 before arrival",
            "notes": "guest is john.smith@gmail.com",
            "address": "Calle Redes 11, 3B",
            "city": "Madrid",
            "zip": "28039",
            "birth_date": "1974-03-02",
        }
    }
    cleaned = probe.anonymise(payload)
    serialised = json.dumps(cleaned, ensure_ascii=False)

    for leaked in (
        "Ana",
        "+34611223344",
        "john.smith@gmail.com",
        "Calle Redes 11",
        "Madrid",
        "28039",
        "1974-03-02",
    ):
        assert leaked not in serialised


def test_zeroes_personal_data_that_arrives_as_a_number():
    """R4.2 — a phone number delivered as a JSON integer is still a phone number.

    Preserving the type was the goal; passing the value through was the bug.
    """
    payload = {"customer": {"phone": 34612345678, "document_number": 12345678}}
    cleaned = probe.anonymise(payload)

    assert cleaned["customer"]["phone"] == 0
    assert cleaned["customer"]["document_number"] == 0
    assert isinstance(cleaned["customer"]["phone"], int)
    assert "34612345678" not in json.dumps(cleaned)


def test_business_fields_survive_even_when_their_key_contains_a_pii_needle():
    """`ota_name` holds "BookingCom", not a person.

    This is the regression guard for inverting the default: the `name` needle would
    otherwise rename every channel to the guest placeholder, and the mapping of R2 would
    map every reservation to `OTHER`.
    """
    payload = {
        "attributes": {
            "ota_name": "BookingCom",
            "status": "new",
            "currency": "EUR",
            "arrival_date": "2026-08-10",
            "inserted_at": "2026-08-01T10:00:00Z",
            "ota_commission": "52.50",
            "unique_id": "BDC-4592817364",
        }
    }
    assert probe.anonymise(payload) == payload


def test_over_scrubbing_is_visible_rather_than_silent():
    """The point of fail-closed: a field we forgot shows up, it does not disappear.

    A mapping test reading `***scrubbed***` fails loudly and gets the key added to
    `PRESERVED_KEYS`; the old direction failed by writing personal data to git history,
    where nothing ever surfaces it.
    """
    cleaned = probe.anonymise({"attributes": {"some_unlisted_text": "whatever"}})
    assert cleaned["attributes"]["some_unlisted_text"] == probe.SCRUBBED


def test_empty_strings_and_booleans_are_left_alone():
    payload = {"attributes": {"blank": "", "is_manual": False, "missing": None}}
    assert probe.anonymise(payload) == payload


def test_card_data_is_scrubbed_including_the_expiry_date():
    """R4.2 and the worst near-miss of this change.

    An OTA booking carries a `guarantee` object with **real cardholder data** from Booking.com.
    The needles caught `card_number`, `card_type` and `cvv`, but `expiration_date` reached a
    committed fixture because it ends in `_date` and `_date` is a preserved suffix. Needles run
    before suffixes, so the card family now sits at the top of the list.
    """
    payload = {
        "guarantee": {
            "card_number": "4111111111111111",
            "card_type": "Visa",
            # Deliberately not resembling the real cardholder name that arrived from
            # Booking.com — a synthetic value that looks like a person invites confusion.
            "cardholder_name": "CARDHOLDER PLACEHOLDER",
            "cvv": "123",
            "expiration_date": "12/2027",
            "token": "tok_abc123",
            "is_virtual": False,
        }
    }
    cleaned = probe.anonymise(payload)
    serialised = json.dumps(cleaned)

    for leaked in ("4111111111111111", "Visa", "CARDHOLDER PLACEHOLDER", "12/2027", "tok_abc123"):
        assert leaked not in serialised, leaked
    # The shape survives: `is_virtual` is a flag, not card data.
    assert cleaned["guarantee"]["is_virtual"] is False


def test_the_captured_fixture_carries_no_card_data():
    """Guards the committed artefact itself, not just the function.

    A future capture that reintroduces a card field would fail here even if somebody weakened
    the anonymiser, because this reads what is actually on disk.
    """
    import re

    raw = (FIXTURE_DIR / "bookings.json").read_text(encoding="utf-8")
    assert not re.search(r"\b\d{13,19}\b", raw), "a PAN-shaped number is in the fixture"
    assert "12/2027" not in raw
    for row in json.loads(raw)["data"]:
        guarantee = (row.get("attributes") or {}).get("guarantee") or {}
        for field in ("card_number", "card_type", "cvv", "cardholder_name", "expiration_date"):
            value = guarantee.get(field)
            assert value in (None, probe.SCRUBBED, "***card-data***"), (field, value)


def test_scrubs_a_dict_key_that_is_itself_personal_data():
    """R4.2 — a provider that keys a map BY guest email hides data where the recursion
    treats it as structure. The key position was copied verbatim until the panel probed it.
    """
    payload = {"guests_by_mail": {"john.smith@gmail.com": {"nights": 3}}}
    cleaned = probe.anonymise(payload)

    assert "john.smith@gmail.com" not in json.dumps(cleaned)
    assert cleaned["guests_by_mail"] == {probe.SCRUBBED_KEY: {"nights": 3}}


def test_identifier_shaped_keys_including_uuids_survive():
    payload = {"rooms_by_id": {"8ab4b6ac-1f0d-4e1a-9d1e-0f7a2b3c4d5e": {"adults": 2}}}
    assert probe.anonymise(payload) == payload


def test_zeroes_an_unrecognised_numeric_leaf():
    """`guest_number: 34611223344` is a phone number under a name no allowlist predicted.

    The previous version argued personal numbers always arrive under a PII key. They do not.
    """
    cleaned = probe.anonymise({"attributes": {"guest_number": 34611223344, "nid": 12345678}})

    assert cleaned["attributes"]["guest_number"] == 0
    assert cleaned["attributes"]["nid"] == 0


@pytest.mark.parametrize("key", ["national_id", "tax_id", "contact_at", "source"])
def test_names_that_a_shape_based_allowlist_used_to_wave_through(key):
    """`_id`/`_at` suffix preservation and `source` are gone from the allowlist.

    `_id` was meant for `room_type_id` and matched `national_id`; `_at` was meant for
    timestamps and matched `contact_at: "ana@hotmail.es"`; `source` is free text, not the
    enum `ota_name` is. Every identifier the mapping needs is listed by exact name instead.
    """
    cleaned = probe.anonymise({"attributes": {key: "12345678Z-or-an-email"}})
    assert cleaned["attributes"][key] != "12345678Z-or-an-email"


def test_the_timestamps_the_mapping_needs_are_still_preserved():
    """Dropping the `_at` suffix must not take `inserted_at` with it — design D1 filters on it."""
    payload = {
        "attributes": {
            "inserted_at": "2026-08-01T10:00:00Z",
            "updated_at": "2026-08-02T11:00:00Z",
            "arrival_date": "2026-08-10",
            "departure_date": "2026-08-14",
        }
    }
    assert probe.anonymise(payload) == payload
