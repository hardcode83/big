"""One-off probe against Channex staging: capture real payloads as anonymised fixtures.

Lives outside `app/` on purpose (design D9): a throwaway capture tool must not travel in
the deployed package. Run it from `backend/`:

    CHANNEX_API_KEY=... uv run python scripts/channex_probe.py bookings revisions

Credentials come from the environment ONLY (R4.4). A key passed as an argument would
survive in the shell history, so this refuses to read one from `argv` — see
`_reject_credential_arguments`.

Anonymisation happens HERE, at capture time (R4.2, design D8), not in a later manual
pass: a fixture that has to be scrubbed by hand is a fixture that gets committed with
real data the day somebody is in a hurry.

What it does NOT capture: the webhook payload. That one arrives at an external capturer
configured in the Channex panel (task 2.4) — nothing in this repo receives webhooks, and
building a route to do so is the scope of `reservations-webhooks`.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "integrations" / "fixtures" / "channex"

DEFAULT_BASE_URL = "https://staging.channex.io/api/v1"
API_KEY_ENV = "CHANNEX_API_KEY"
BASE_URL_ENV = "CHANNEX_BASE_URL"

# The endpoints whose shape this change needs. `revisions` is captured but deliberately
# NOT consumed by any adapter code: reading the feed without acknowledging it is a plain
# GET, and the fixture is the design input `reservations-webhooks` will need (design D9,
# resolution of OQ3). Acknowledging is what would mutate provider state, and this never does.
CAPTURES: dict[str, str] = {
    "bookings": "/bookings",
    "revisions": "/booking_revisions/feed",
    # Discovered by probing, not from the docs: `/messages` and `/conversations` are 404, the
    # collection is `/message_threads`. Needs the `channex_messages` app installed.
    #
    # EXTERNAL_DEPENDENCY: this comes back EMPTY until a real OTA booking with a guest
    # conversation exists. A booking created through the CRS API has no thread, so capturing a
    # real message payload waits on the Booking.com test environment (R5).
    "message_threads": "/message_threads",
}

# EXTERNAL_DEPENDENCY: the message endpoint depends on the `channex_messages` app, which
# ADR 0006 records as paid and per-property. If it is not enabled on the staging account
# the capture returns an error, and that outcome is itself a finding for R6 — pass the
# path explicitly with `--capture messages=/path` once the real one is confirmed.

SCRUBBED = "***scrubbed***"

# Business fields the fixtures must keep verbatim. Checked FIRST, before the PII needles,
# because some of these legitimately contain a needle: `ota_name` holds "BookingCom", not a
# person, and letting the `name` needle win would rename every channel to "Test Guest".
PRESERVED_KEYS = frozenset(
    {
        "type",
        "id",
        "status",
        "currency",
        "ota_name",
        "ota",
        "channel",
        # `source` was here and came out: unlike `ota_name` it is not a bounded vocabulary in
        # a booking payload, so whatever the provider writes there gets published — a
        # captured `"source": "referred by john.smith@gmail.com"` survived verbatim. The
        # mapping needs `ota_name`/`channel`, never `source`. Add it back only if a real
        # capture proves it is an enum.
        "unique_id",
        "system_id",
        "revision_id",
        "booking_id",
        "property_id",
        "room_type_id",
        "rate_plan_id",
        "group_id",
        "ota_reservation_code",
        "payment_collect",
        "payment_type",
        "amount",
        "total_price",
        "ota_commission",
        "page",
        "total",
        "limit",
        # Added after the first real capture: `meta` carries these two and the fail-closed
        # default scrubbed them. They are pagination metadata, not personal data. This is the
        # designed failure mode doing its job — an over-scrub shows up as `***scrubbed***` in
        # the fixture instead of vanishing, so it gets fixed by adding the key here.
        "order_by",
        "order_direction",
        # Added after the first capture WITH bookings in it. All enums or identifiers, none
        # of them personal. `raw_message` is deliberately NOT here: it is the original OTA
        # message, free text, and the likeliest place in the whole payload for a guest name
        # or phone to hide — the fail-closed default is right to scrub it.
        "acknowledge_status",
        "booking_room_id",
        # `ages`, `taxes` and `attachments` were here and came OUT. All three are lists, and
        # since list members inherit their list's key, allowlisting the key waved through every
        # **scalar** member untouched — `{"attachments": ["dni_12345678Z.pdf"]}` survived
        # verbatim. It is the same hole the section-4 panel closed for `guests`, reopened by the
        # edit that added the message-thread keys. None of the three has ever been observed
        # non-empty and the mapping reads none of them, so preserving them bought nothing.
        # Numbers inside them still survive on their own merit (below the identifying floor).
        "is_crs_revision",
        "has_unacked_revisions",
        # `guarantee` was here as "an enum or identifier". It is neither: it is the **card**
        # object. Being in this list never protected its children (they are judged individually)
        # but listing it was wrong and misleading. Removed.
        "agent",
        # Not personal data: an ISO language tag like "es". Was being scrubbed by the fail-closed
        # default, which is the harmless direction but noise in the fixture.
        "language",
        "channel_id",
        "secondary_ota",
        # Estructura de los hilos de mensajes (`/message_threads`). El **contenido** (`message`)
        # y el `title` —que es el nombre del huésped— siguen cayendo al scrub por defecto: un
        # mensaje de huésped es el sitio más probable de todo el payload para encontrar un
        # teléfono o un apellido. Lo que se preserva es la forma, que es lo que un test necesita.
        "provider",
        "ota_message_thread_id",
        "message_count",
        "is_closed",
        "sender",
        "last_message_received_at",
        # Occupancy — small counts the mapping puts straight into `ReservationDTO`.
        "adults",
        "children",
        "infants",
        "nights",
        # `guests` was here, grouped with the occupancy counts, and that was wrong: in the
        # Channex payload `rooms[].guests` is the room's **guest list**, not a number. It reads
        # as `null` in the fixture only because a CRS booking has no per-room guests, and
        # `mapping.py` never touches it (it uses `occupancy.adults`/`children`), so preserving
        # it bought the fixtures nothing and would have published real names off the first OTA
        # booking. Removed after the section-4 security panel.
        # Timestamps, listed by exact name rather than by an `_at` suffix — see below.
        "inserted_at",
        "updated_at",
        "created_at",
        "cancelled_at",
    }
)

# Shape-based preservation, deliberately narrow.
#
# `_at` and `_id` were here and came out. `_at` was meant for timestamps but matched
# `contact_at: "ana@hotmail.es"`; `_id` was meant for `room_type_id` but matched
# `national_id: "12345678Z"` and `tax_id` — an identity document waved through by a suffix
# that looks structural. Every identifier the mapping needs is in `PRESERVED_KEYS` by exact
# name, so the suffix bought nothing and cost that.
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
SCRUBBED_KEY = "***scrubbed-key***"

# Channex keys nightly rates BY DATE: `rooms[].days = {"2026-09-15": "120.00", ...}`. The key
# is data-shaped, so no name-based allowlist can ever cover the value under it — the first
# capture with real bookings came back with every nightly rate scrubbed. A date is not
# personal data and the price under it is exactly what the mapping reads, so a date-shaped key
# preserves its leaf.
_DATE_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The second shape-based judgement, for numbers under a key no allowlist predicted. Zeroing
# every one of them destroys the fixture (`adults: 2`, `nights: 3` are exactly the business
# data the mapping needs), and keeping every one of them publishes `guest_number:
# 34611223344`. The discriminator is magnitude: identifying numbers in this domain are long
# — phone numbers run 9-12 digits, a DNI is 8 — while occupancy counts and money in euros
# for a two-flat portfolio do not reach seven figures.
IDENTIFYING_NUMBER_FLOOR = 1_000_000

PII_PLACEHOLDERS: tuple[tuple[tuple[str, ...], str], ...] = (
    # **Card data, first in the list and it has to be.** Channex returns a `guarantee` object on
    # OTA bookings with `card_number`, `card_type`, `cvv`, `cardholder_name` and
    # `expiration_date` — real cardholder data, from Booking.com. The needles below caught the
    # first four, and `expiration_date` **leaked into a committed fixture** because it ends in
    # `_date` and `_date` is a preserved suffix. Needles run before suffixes, so putting the card
    # family here is what closes it. Nothing card-shaped is ever worth keeping in a fixture.
    (("card", "cvv", "cvc", "expiration", "expiry", "token", "guarantee"), "***card-data***"),
    # `mail`, not `email`: Channex names the guest address `mail` inside `customer`, and a
    # needle of "email" misses it. Caught by the "no original value survives" assertion in
    # `test_channex_probe.py` — which is exactly why that assertion is written over the whole
    # serialised document instead of field by field.
    (("mail",), "guest@example.invalid"),
    (("phone", "mobile", "telephone"), "+34600000000"),
    (("document", "passport", "dni", "nif", "id_card"), "X0000000X"),
    (("birth", "dob"), "1990-01-01"),
    (("address", "street", "city", "zip", "postal", "region", "country"), "Redacted"),
    (("name",), "Test Guest"),
)


def anonymise(value: Any) -> Any:
    """Strip every personal datum from a captured payload, preserving shape and types.

    **Fail-closed** (R4.2, and the fix for both PII findings of the section-3 panel). The
    first version was a key denylist: match a needle, replace it; pass everything else
    through. Two ways that leaks, both demonstrated by the reviewers rather than imagined:

    1. A key nobody thought of — `special_request`, `notes`, `address`, `birth_date` — goes
       to a versioned fixture verbatim, and guests routinely type a surname or a phone
       number into free text. A denylist can only ever know the fields somebody remembered.
    2. `--capture=x=/some/other/endpoint` can point this at a payload whose keys were never
       considered at all, including credential- or card-shaped ones.

    So the default is inverted: a string leaf survives only if its key is recognised
    business data (`PRESERVED_KEYS` / `PRESERVED_SUFFIXES`). Everything else becomes
    `SCRUBBED`, and the PII needles remain as an explicit layer so the intent stays readable
    and the placeholders keep a realistic shape.

    The failure mode is now **visible instead of silent**: over-scrubbing a field the
    mapping actually needs shows up as `***scrubbed***` in a failing mapping test, whereas
    under-scrubbing used to show up as personal data in git history forever.

    Fail-closed applies to **all three** places a value can hide, which the first attempt at
    this got wrong and the security panel measured:

    - string leaves -> `SCRUBBED`;
    - **numeric leaves** -> zeroed, keeping the type. The earlier version argued "anything
      personal that arrives as a number does so under a PII key" and that was simply untrue:
      `guest_number: 34611223344` under an unfamiliar key sailed through;
    - **dict keys** -> a non-identifier-shaped key is replaced, because a provider that keys
      a map by guest email hides data in a position the recursion treats as structure.

    `None` and booleans stay as they are: absence and flags are not personal data, and the
    fixture has to keep exercising the same optionality the real payload has, or the `None`
    branches R2.4 requires would never be reached.
    """
    return _anonymise_value(None, value)


def _anonymise_value(key: str | None, value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _anonymise_key(member_key): _anonymise_value(member_key, member)
            for member_key, member in value.items()
        }
    if isinstance(value, list):
        # **List members inherit the list's key.** A bare string inside a list has no name of
        # its own, and the first version simply returned it untouched — so
        # `special_requests: ["John Smith", "+34611223344"]` sailed through every layer of the
        # fail-closed logic while the function's docstring claimed otherwise. Measured by the
        # section-4 security panel; the section-3 test could not catch it because its only list
        # (`rooms`) contains dicts, never scalars.
        #
        # It is not hypothetical: the captured bookings carry four array fields (`services`,
        # `deposits`, `taxes`, `ages`) that are empty ONLY because these bookings came from the
        # CRS, and the captures still ahead — a real message thread, a webhook body, a
        # Booking.com booking off a test hotel **shared with other integrators** — run this same
        # anonymiser over payloads that can hold third parties' guest data.
        return [_anonymise_value(key, member) for member in value]
    return _anonymise_leaf(key, value)


def _anonymise_key(key: str) -> str:
    if not isinstance(key, str) or not _IDENTIFIER_KEY.match(key):
        return SCRUBBED_KEY
    if key.isdigit() and len(key) >= 7:
        # A long run of digits used as a key: could be a document or phone number.
        return SCRUBBED_KEY
    lowered = key.lower()
    if lowered in PRESERVED_KEYS or lowered.endswith(PRESERVED_SUFFIXES):
        return key
    for needles, _ in PII_PLACEHOLDERS:
        if any(needle in lowered for needle in needles):
            # The key names a personal datum but IS a field name, not a value — keep it, the
            # value under it is what gets replaced.
            return key
    return key


def _anonymise_leaf(key: str | None, value: Any) -> Any:
    """Judge one scalar by the key it sits under — a dict entry's key, or its list's key."""
    if value is None or isinstance(value, bool):
        return value

    lowered = key.lower() if isinstance(key, str) else ""
    if lowered in PRESERVED_KEYS or _DATE_KEY.match(lowered):
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


def _is_known_argument(argument: str) -> bool:
    return argument in CAPTURES or argument.startswith("--capture=")


def _reject_credential_arguments(argv: list[str]) -> None:
    """Refuse anything that is not a recognised argument (R4.4).

    Shape-based, not spelling-based. The first version rejected only a token containing
    `CHANNEX_API_KEY` or starting with `--api-key`, which the security panel showed misses
    the two ways an operator actually fumbles it — a bare positional
    (`channex_probe.py bookings <key>`) or `--key=<key>`. Both sailed through and, worse,
    got echoed verbatim to stderr by the unknown-capture branch, putting the credential in
    a terminal transcript on top of the shell history.

    So: an unrecognised token is refused, and **its value is never printed** — only the list
    of what is accepted (R2.3 applies to this script's output too).
    """
    for argument in argv:
        if not _is_known_argument(argument):
            raise SystemExit(
                "channex-probe: unrecognised argument (value not echoed on purpose — it "
                f"may be a credential). Accepted: {', '.join(CAPTURES)}, or "
                f"--capture=name=/path. The API key is read from the {API_KEY_ENV} "
                "environment variable and must never be passed on the command line, where "
                "it would stay in your shell history."
            )


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise SystemExit(f"channex-probe: {API_KEY_ENV} is not set in the environment")
    return key


def capture(name: str, path: str, *, client: httpx.Client) -> Path:
    response = client.get(path)
    response.raise_for_status()
    target = FIXTURE_DIR / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(anonymise(response.json()), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _reject_credential_arguments(args)

    # Everything reaching here is already known-shaped: `_reject_credential_arguments`
    # refuses anything else without printing it.
    requested = {}
    for argument in args:
        if argument.startswith("--capture="):
            name, _, path = argument.removeprefix("--capture=").partition("=")
            requested[name] = path
        else:
            requested[argument] = CAPTURES[argument]
    if not requested:
        requested = dict(CAPTURES)

    base_url = os.environ.get(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL
    with httpx.Client(
        base_url=base_url,
        headers={"user-api-key": _api_key()},
        timeout=30.0,
    ) as client:
        for name, path in requested.items():
            written = capture(name, path, client=client)
            print(f"channex-probe: {path} -> {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
