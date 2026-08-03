"""Provision the Channex staging sandbox: property + room type + rate plan (task 1.1).

A script rather than a list of clicks, for two reasons. The operator asked for the fewest
manual steps possible, and task 1.1 requires the account setup to be **reproducible** — a
runbook that says "now fill in seven fields in the panel" is not.

**Idempotent**: every step looks for what it would create before creating it, so running this
twice is harmless. That matters because the failure mode of a non-idempotent provisioning
script against a real account is a pile of duplicate properties nobody dares delete.

Lives outside `app/` for the same reason as `channex_probe.py` (design D9): setup tooling
does not belong in the deployed package. Uses `httpx` directly instead of `ChannexClient`,
which only reads — teaching the production client to POST for a one-off setup would push
write support into code that has no business having it.

Run it from `backend/`:

    docker compose exec backend uv run python scripts/channex_bootstrap.py

Credentials come from the environment only, and an argument that might be one is refused —
same posture as the probe (R4.4).

Three required-field sets, taken from the API docs rather than guessed:
- property:  `title`, `currency`
- room type: `property_id`, `title`, `count_of_rooms`, `occ_adults`, `occ_children`,
             `occ_infants`, `default_occupancy`
- rate plan: `title`, `property_id`, `room_type_id`, `options[{occupancy, is_primary}]`
"""

import json
import os
import sys
from typing import Any
from urllib.parse import urlparse

import httpx

API_KEY_ENV = "CHANNEX_API_KEY"
BASE_URL_ENV = "CHANNEX_BASE_URL"
DEFAULT_BASE_URL = "https://staging.channex.io/api/v1"

# Exact hostnames this script may write to. `secure-staging` is Channex's PCI-DSS staging host,
# included because it is the same environment under a different name.
ALLOWED_HOSTS = frozenset({"staging.channex.io", "secure-staging.channex.io"})

# Named so a human looking at the Channex panel knows instantly that this is not a real
# listing. The first version was "AutoHostAI STAGING TEST — REDES11" and it backfired: naming a
# real flat from PRD §27 made the operator ask whether the Booking.com test link pointed at
# their actual apartment. A sandbox should not borrow the name of something that is selling.
#
# The title is also the idempotency key (`_find` matches on it), so renaming the property in
# Channex without changing this constant would make the next run create a DUPLICATE rather than
# reuse. Both were changed together on 2026-08-03.
PROPERTY_TITLE = "AutoHostAI Channex Sandbox (test only)"
ROOM_TYPE_TITLE = "Apartamento completo (test)"
RATE_PLAN_TITLE = "Tarifa estándar (test)"

# One rate plan per currency, and the reason is operational rather than functional.
#
# Booking.com's test hotels are a **pool of eight shared between Channex integrators**, leased in
# time slots — all eight can read as "In use until HH:MM" at once. Mapping requires the rate
# plan's currency to match the test hotel's ("Make sure your rate plans are in the same currency
# or you will not be able to map"), so a single EUR rate plan makes exactly ONE of the eight
# usable and turns the end-to-end test into a wait for one specific slot.
#
# With one rate plan per currency you take whichever hotel frees first. Bonus: a booking in GBP
# or USD exercises the mapping's currency handling, which EUR-only fixtures never do.
#
#   EUR -> 4372137
#   GBP -> 5868189, 6519420, 10745030, 11140466
#   USD -> 10485037, 12152494 (the latter needs a real card)
#   JPY -> 10484818
EXTRA_CURRENCIES = ("GBP", "USD", "JPY")


def _reject_credential_arguments(argv: list[str]) -> None:
    if argv:
        raise SystemExit(
            "channex-bootstrap: takes no arguments (value not echoed on purpose — it may be "
            f"a credential). The API key is read from {API_KEY_ENV}."
        )


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise SystemExit(f"channex-bootstrap: {API_KEY_ENV} is not set in the environment")
    return key


def _rows(client: httpx.Client, path: str, **params: Any) -> list[dict[str, Any]]:
    response = client.get(path, params=params or None)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") or []
    return rows if isinstance(rows, list) else [rows]


def _find(rows: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    for row in rows:
        if (row.get("attributes") or {}).get("title") == title:
            return row
    return None


def _create(client: httpx.Client, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=body)
    if response.status_code >= 400:
        # The body is the only place Channex explains a validation failure, and this is a
        # setup script whose whole job is to surface exactly that.
        raise SystemExit(
            f"channex-bootstrap: POST {path} -> {response.status_code}\n{response.text}"
        )
    return response.json()["data"]


def ensure_property(client: httpx.Client) -> dict[str, Any]:
    existing = _find(_rows(client, "/properties"), PROPERTY_TITLE)
    if existing:
        print(f"property     reused  {existing['id']}")
        return existing
    created = _create(
        client,
        "/properties",
        {
            "property": {
                "title": PROPERTY_TITLE,
                "currency": "EUR",
                "country": "ES",
                "city": "Madrid",
                "timezone": "Europe/Madrid",
                "email": "staging@autohostai.invalid",
            }
        },
    )
    print(f"property     created {created['id']}")
    return created


def ensure_room_type(client: httpx.Client, property_id: str) -> dict[str, Any]:
    existing = _find(
        _rows(client, "/room_types", **{"filter[property_id]": property_id}), ROOM_TYPE_TITLE
    )
    if existing:
        print(f"room_type    reused  {existing['id']}")
        return existing
    created = _create(
        client,
        "/room_types",
        {
            "room_type": {
                "property_id": property_id,
                "title": ROOM_TYPE_TITLE,
                # A whole flat, not a hotel room: one unit, sleeps four, two by default —
                # the shape of REDES11 in PRD §27.
                "count_of_rooms": 1,
                "occ_adults": 4,
                "occ_children": 0,
                "occ_infants": 0,
                "default_occupancy": 2,
            }
        },
    )
    print(f"room_type    created {created['id']}")
    return created


def ensure_rate_plan(
    client: httpx.Client,
    property_id: str,
    room_type_id: str,
    *,
    currency: str | None = None,
) -> dict[str, Any]:
    """The property's default-currency rate plan, or one pinned to `currency`."""
    title = RATE_PLAN_TITLE if currency is None else f"{RATE_PLAN_TITLE} — {currency}"
    existing = _find(_rows(client, "/rate_plans", **{"filter[property_id]": property_id}), title)
    if existing:
        print(f"rate_plan    reused  {existing['id']}  {currency or 'EUR'}")
        return existing
    payload: dict[str, Any] = {
        "title": title,
        "property_id": property_id,
        "room_type_id": room_type_id,
        "options": [{"occupancy": 2, "is_primary": True, "rate": 12000}],
    }
    if currency is not None:
        # Optional on the API and defaults to the property's currency — pinning it is what makes
        # a non-EUR test hotel mappable against a EUR property.
        payload["currency"] = currency
    created = _create(client, "/rate_plans", {"rate_plan": payload})
    print(f"rate_plan    created {created['id']}  {currency or 'EUR'}")
    return created


# Fixed dates, not `today() + n`: a fixture regenerated next year would otherwise change and
# every mapping test asserting a concrete check-in would have to move with it.
ARRIVAL = "2026-09-15"
DEPARTURE = "2026-09-18"
NIGHTLY_RATE = "120.00"

# Two bookings on purpose, because they exercise the two branches the mapping has to get
# right (R2.4, tasks 4.2/4.3): Channex only reports `ota_commission` for Booking.com and
# Airbnb, so an OTA booking must carry one and an offline one must map to `None` — never to
# zero, which would assert in false that there was no commission.
BOOKINGS = (
    {
        "code": "AUTOHOST-TEST-BDC-001",
        "ota_name": "Booking.com",
        "ota_commission": "54.00",
    },
    {
        "code": "AUTOHOST-TEST-OFFLINE-001",
        "ota_name": "Offline",
        "ota_commission": None,
    },
)


BOOKING_CRS_CODE = "booking_crs"

# Installed on the operator's explicit instruction (2026-08-03). Note the discrepancy, since
# it will bite in production and not here: staging reports `price: null` for this app, while
# ADR 0006 decision 2 records `channex_messages` as **paid, per property**. Staging pricing
# does not reflect production pricing, so enabling it here says nothing about its cost later.
# The price guard in `ensure_application` still applies — if Channex ever reports a price,
# this aborts rather than subscribing to anything.
CHANNEX_MESSAGES_CODE = "channex_messages"

# Apps this script may install automatically. **An allowlist, not "whatever has no price"** —
# see `ensure_application` for why the price check alone was not a guard at all.
#
# `channex_messages` was installed once on 2026-08-03 on the operator's explicit instruction and
# stays installed in that account, but it is deliberately NOT here: ADR 0006 decision 2 records
# it as **paid and per property**, and staging reporting `price: null` says nothing about
# production. A reproducible setup script must not subscribe a paid app on whatever account it
# is next pointed at. Installing it is a decision, so it stays a manual one.
APPS_TO_INSTALL = (BOOKING_CRS_CODE,)

# Verified free in staging AND required for the sandbox to work at all (`POST /bookings` is a
# 403 without `booking_crs`). Adding a code here is an assertion that somebody checked.
KNOWN_FREE_APPS = frozenset({BOOKING_CRS_CODE})


def ensure_application(client: httpx.Client, property_id: str, code: str) -> None:
    """Install a Channex application on the property, idempotently.

    `POST /bookings` answers **403 Forbidden** without this: the Booking CRS app is what
    grants API access to create and edit bookings, and Channex's own docs say so
    ("Property should have Booking CRS App installed to have access"). Discovering that from
    the 403 alone is impossible, which is why it is recorded here.

    **Guarded by an allowlist, because the price check alone was not a guard.** The first
    version aborted only when the provider's catalogue reported a truthy `price`/`vr_price`, and
    the security panel showed that in the single case it existed for it did not fire:
    `channex_messages` is paid per ADR 0006 and staging reports `price: null` for it. The check
    was also bound to exactly two field names, so any other pricing key (`monthly_price`,
    `cost`) read as free.

    So the rule is inverted: a code must be in `KNOWN_FREE_APPS` — somebody checked — and the
    price fields are kept as a second line that can only ever add a refusal.
    """
    installed = _rows(client, "/applications/installed")
    for row in installed:
        attributes = row.get("attributes") or {}
        if attributes.get("application_code") == code and attributes.get("property_id") == property_id:
            print(f"app          reused  {code}")
            return

    if code not in KNOWN_FREE_APPS:
        raise SystemExit(
            f"channex-bootstrap: refusing to install {code!r} — it is not in KNOWN_FREE_APPS. "
            "Add it there only after confirming it is free, or install it deliberately from the "
            "panel. A setup script must not be able to subscribe a paid app."
        )
    catalogue = _find_by_code(_rows(client, "/applications"), code)
    if catalogue is None:
        raise SystemExit(f"channex-bootstrap: no application with code {code!r}")
    prices = {
        key: value
        for key, value in (catalogue.get("attributes") or {}).items()
        if ("price" in key or "cost" in key or "fee" in key) and value
    }
    if prices:
        # Second line only. `price: null` is NOT evidence that an app is free — that is exactly
        # what the allowlist above is for.
        raise SystemExit(
            f"channex-bootstrap: refusing to install {code!r} — the catalogue reports a cost "
            f"({prices}) even though it is listed as free. Re-check before installing."
        )

    _create(
        client,
        "/applications/install",
        {"application_installation": {"property_id": property_id, "application_code": code}},
    )
    print(f"app          installed {code} (free)")


def _find_by_code(rows: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    for row in rows:
        if (row.get("attributes") or {}).get("code") == code:
            return row
    return None


def ensure_bookings(
    client: httpx.Client, property_id: str, room_type_id: str, rate_plan_id: str
) -> int:
    existing = {
        (row.get("attributes") or {}).get("ota_reservation_code")
        for row in _rows(client, "/bookings", **{"filter[property_id]": property_id})
    }
    created = 0
    for spec in BOOKINGS:
        if spec["code"] in existing:
            print(f"booking      reused  {spec['code']}")
            continue
        booking: dict[str, Any] = {
            "property_id": property_id,
            "ota_reservation_code": spec["code"],
            "ota_name": spec["ota_name"],
            "arrival_date": ARRIVAL,
            "departure_date": DEPARTURE,
            "currency": "EUR",
            "customer": {
                # Obviously fake, and `.invalid` can never route anywhere. The probe
                # anonymises these on capture anyway (R4.2) — this is belt and braces so
                # nothing plausible-looking ever exists in the account either.
                "name": "Test",
                "surname": "Guest",
                "mail": "test.guest@example.invalid",
                "phone": "+34600000000",
                "address": "Calle de Prueba 1",
                "city": "Madrid",
                "zip": "28039",
                "country": "ES",
            },
            "rooms": [
                {
                    "room_type_id": room_type_id,
                    "rate_plan_id": rate_plan_id,
                    "days": {
                        "2026-09-15": NIGHTLY_RATE,
                        "2026-09-16": NIGHTLY_RATE,
                        "2026-09-17": NIGHTLY_RATE,
                    },
                    "occupancy": {"adults": 2, "children": 0, "infants": 0},
                }
            ],
        }
        if spec["ota_commission"]:
            booking["ota_commission"] = spec["ota_commission"]
        result = _create(client, "/bookings", {"booking": booking})
        print(f"booking      created {spec['code']} -> {result['id']}")
        created += 1
    return created


def main(argv: list[str] | None = None) -> int:
    _reject_credential_arguments(list(sys.argv[1:] if argv is None else argv))
    base_url = os.environ.get(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL
    host = urlparse(base_url).hostname or ""
    if host not in ALLOWED_HOSTS:
        # This script WRITES: properties, room types, rate plans, app installs, bookings. The
        # host check is the only control standing between a mistyped base URL and provisioning
        # test data into a live Channex account.
        #
        # An exact **hostname** match, because the first version tested `"staging" not in
        # base_url` and the security panel showed what that accepts:
        #   https://app.channex.io/api/v1?env=staging     -> a live account
        #   https://staging:x@app.channex.io/api/v1       -> userinfo, also live
        #   https://staging.channex.io.example.net/api/v1 -> not Channex at all, and it would
        #                                                    receive the `user-api-key` header
        raise SystemExit(
            f"channex-bootstrap: refusing to write against host {host!r} "
            f"(allowed: {', '.join(sorted(ALLOWED_HOSTS))})"
        )

    with httpx.Client(
        base_url=base_url, headers={"user-api-key": _api_key()}, timeout=30.0
    ) as client:
        prop = ensure_property(client)
        room_type = ensure_room_type(client, prop["id"])
        rate_plan = ensure_rate_plan(client, prop["id"], room_type["id"])
        # One per currency, so whichever Booking.com test hotel frees first is mappable. See
        # EXTRA_CURRENCIES for why a single EUR plan makes exactly one of the eight usable.
        for currency in EXTRA_CURRENCIES:
            ensure_rate_plan(client, prop["id"], room_type["id"], currency=currency)
        # Before the bookings, not after: without `booking_crs` `POST /bookings` is a 403.
        for code in APPS_TO_INSTALL:
            ensure_application(client, prop["id"], code)
        ensure_bookings(client, prop["id"], room_type["id"], rate_plan["id"])

    print(
        "\n"
        + json.dumps(
            {
                "property_id": prop["id"],
                "room_type_id": room_type["id"],
                "rate_plan_id": rate_plan["id"],
            },
            indent=2,
        )
    )
    print(
        "\nNext: write this property_id into `Property.pms_external_id` of the AutoHostAI "
        "property that should sync from this sandbox (task 6.1)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
