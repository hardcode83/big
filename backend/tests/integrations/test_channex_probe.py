"""The anonymiser of the capture script (R4.2, task 2.2).

Loaded by path rather than imported: `backend/scripts/` is deliberately NOT a package
(design D9 keeps the throwaway probe out of the deployed distribution), so there is no
`scripts.channex_probe` to import. The `importlib` helper that was the price of that
decision now lives in `conftest.load_script`, shared with the Beds24 probe.

What this file asserts is unchanged by that move, and by the extraction of the policy into
`scripts/anonymise.py`: `channex_probe.anonymise` still takes one argument and still applies
the Channex business-key allowlist.
"""

import json

import httpx

import pytest

from tests.integrations.conftest import FIXTURE_DIR, load_script  # noqa: E402

probe = load_script("channex_probe")


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


@pytest.mark.parametrize(
    "key",
    [
        "attachments",
        "taxes",
        "ages",
        "special_requests",
        "notes",
        # The class, not just the instances. These are the ones that survived the SECOND fix:
        # `_amount`/`_price`/`_count`/`_date` are preserved *suffixes*, and a date-shaped key gets
        # its own branch — in a provider that keys nightly rates by date. A scalar list member is
        # now judged as unnamed, so its list's key cannot grant it anything.
        "charge_amount",
        "extra_price",
        "guest_count",
        "blocked_date",
        "2026-09-05",
        "some_key_nobody_predicted",
    ],
)
def test_a_scalar_inside_a_list_is_scrubbed_whatever_the_lists_key(key):
    """R4.2, and the hole the feature-scale security panel found.

    List members inherit their list's key, so allowlisting a list's key waved through every
    **scalar** member untouched: `{"attachments": ["dni_12345678Z.pdf"]}` survived verbatim.
    Same class as the `guests` hole an earlier panel closed, reopened by the edit that added
    the message-thread keys — and there was no test for the list-inheritance fix at all, only
    a comment claiming it had been measured.
    """
    payload = {key: ["dni_12345678Z.pdf", "ana.perez@gmail.com", "+34611223344"]}
    serialised = json.dumps(probe.anonymise(payload))

    for leaked in ("dni_12345678Z.pdf", "ana.perez@gmail.com", "+34611223344"):
        assert leaked not in serialised, f"{key} -> {leaked}"


def test_numbers_inside_a_list_still_survive_on_their_own_merit():
    """Dropping those keys from the allowlist must not empty legitimate numeric lists."""
    assert probe.anonymise({"ages": [12, 8, 0]}) == {"ages": [12, 8, 0]}


def test_dicts_inside_a_list_are_still_recursed_into():
    cleaned = probe.anonymise({"rooms": [{"guest_name": "Ana Perez", "adults": 2}]})
    assert cleaned["rooms"][0]["adults"] == 2
    assert "Ana Perez" not in json.dumps(cleaned)


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


def test_a_date_shaped_key_preserves_a_price_but_not_free_text():
    """The handover item the security panel said was worth closing properly.

    The branch exists for `rooms[].days`, whose values are decimal price strings. It used to
    preserve **any** scalar, so a provider (or a `--capture=` against a new endpoint) that keyed
    free text by date published it verbatim.
    """
    assert probe.anonymise({"days": {"2026-09-05": "120.00"}}) == {"days": {"2026-09-05": "120.00"}}
    assert probe.anonymise({"2026-09-05": 120}) == {"2026-09-05": 120}

    leaked = probe.anonymise({"2026-09-05": "call Ana at +34611223344"})
    assert leaked["2026-09-05"] == probe.SCRUBBED


@pytest.mark.parametrize("key", ["34-611-223-344", "34611223344", "12345678", "34.611.223.344"])
def test_a_digit_shaped_key_is_scrubbed_even_with_separators(key):
    """A phone or document number used as a dict key. Separators are stripped before the check —
    the earlier version only caught an unbroken run of digits."""
    cleaned = probe.anonymise({key: {"nights": 3}})
    assert probe.SCRUBBED_KEY in cleaned
    # The value underneath is still judged on its own merits, not destroyed.
    assert cleaned[probe.SCRUBBED_KEY] == {"nights": 3}


def test_capture_writes_the_anonymised_body_not_the_raw_one(tmp_path, monkeypatch):
    """R4.1 + R4.2 — the **write path**, which had no test at all.

    Only `anonymise()` was covered, so a regression that wrote `response.json()` straight to disk
    would have shipped a fixture full of real guest and card data with the whole suite green.
    That is the one failure this module exists to prevent, so it gets an assertion.
    """
    payload = {
        "data": [
            {
                "attributes": {
                    "unique_id": "BDC-1",
                    "customer": {"name": "Ana Perez", "mail": "ana.perez@gmail.com"},
                    "guarantee": {"card_number": "4111111111111111", "cvv": "123"},
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(probe, "FIXTURE_DIR", tmp_path)
    with httpx.Client(
        base_url="https://staging.channex.io/api/v1",
        headers={"user-api-key": "k"},
        transport=httpx.MockTransport(handler),
    ) as client:
        written = probe.capture("probe_out", "/bookings", client=client)

    raw = written.read_text(encoding="utf-8")
    for leaked in ("Ana Perez", "ana.perez@gmail.com", "4111111111111111", "123"):
        assert leaked not in raw, leaked
    # The business identifier still survives, or the fixture would be useless.
    assert "BDC-1" in raw


@pytest.mark.parametrize("fixture_path", sorted(FIXTURE_DIR.glob("*.json")), ids=lambda p: p.name)
def test_no_committed_fixture_carries_card_data(fixture_path):
    """Guards the committed artefacts themselves, not just the function.

    **Parametrised over every fixture on disk**, not one filename. The first version read only
    `bookings.json` while `revisions.json` carries the identical `guarantee` object — so the
    guard covered one of three files, which is exactly how `expiration_date` got committed the
    first time. Globbing means a fixture added later is covered without anyone remembering to.
    """
    import re

    raw = fixture_path.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{13,19}\b", raw), f"PAN-shaped number in {fixture_path.name}"
    assert "12/2027" not in raw

    # Whatever the TYPE. The first version exempted non-strings, so `{"cvv": 123}` passed both
    # gates — the PAN regex needs 13+ digits and the per-key assertion only looked at strings.
    # The anonymiser does zero it today, but a guard narrower than its own promise is how
    # `expiration_date` got committed in the first place.
    allowed = (None, probe.SCRUBBED, "***card-data***", 0, 0.0, False)

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = key.lower()
                if any(n in lowered for n in ("card", "cvv", "cvc", "expiration", "expiry")):
                    assert isinstance(value, (dict, list)) or value in allowed, (
                        fixture_path.name,
                        key,
                        value,
                    )
                walk(value)
        elif isinstance(node, list):
            for member in node:
                walk(member)

    walk(json.loads(raw))


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
