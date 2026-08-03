"""One-off probe against Channex staging: capture real payloads as anonymised fixtures.

Lives outside `app/` on purpose (design D9): a throwaway capture tool must not travel in
the deployed package. Run it from `backend/`:

    CHANNEX_API_KEY=... uv run python scripts/channex_probe.py bookings revisions

Credentials come from the environment ONLY (R4.4). A key passed as an argument would
survive in the shell history, so this refuses to read one from `argv` — see
`_reject_credential_arguments`.

Anonymisation happens at capture time (R4.2, design D8), not in a later manual pass: a
fixture that has to be scrubbed by hand is a fixture that gets committed with real data the
day somebody is in a hurry. The **policy** moved to `anonymise.py` when `pms-beds24-spike`
needed the same one for a second provider (its design D2); what stays here is the only part
that is genuinely per provider, `PRESERVED_KEYS`.

What it does NOT capture: the webhook payload. That one arrives at an external capturer
configured in the Channex panel (task 2.4) — nothing in this repo receives webhooks, and
building a route to do so is the scope of `reservations-webhooks`.
"""

import json
import os
import sys
from pathlib import Path

import httpx

# `scripts/` is not a package (design D9), so this resolves via sys.path[0] when the script is
# run directly, and via the loader in `tests/integrations/conftest.py` under pytest.
# SCRUBBED/SCRUBBED_KEY are re-exported rather than used here: they are the placeholders the
# fixture assertions check for, and they stay reachable as `channex_probe.SCRUBBED`.
from anonymise import SCRUBBED as SCRUBBED  # noqa: PLC0414
from anonymise import SCRUBBED_KEY as SCRUBBED_KEY  # noqa: PLC0414
from anonymise import anonymise as _anonymise_payload

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

def anonymise(value):
    """Channex payload -> fixture-safe payload.

    The policy itself lives in `anonymise.py`, shared with the Beds24 probe (design D2 of
    `pms-beds24-spike`). All this adds is the one thing that is genuinely per provider: the
    business-key allowlist above. Kept as a module-level function with the original
    one-argument signature so callers and tests do not need to know about the split.
    """
    return _anonymise_payload(value, business_keys=PRESERVED_KEYS)


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
