"""Acquire one of Booking.com's shared test hotels the moment it frees (task 6.2).

**Why this exists.** Channex lends eight Booking.com test hotels, leased in time slots and
shared across all its integrators. Measured on 2026-08-03: at the exact minute the EUR hotel's
lease expired (13:50) it was already re-leased until 17:00, and the USD one went 13:00 -> 16:30
the same way. Nobody re-leases a hotel within seconds of its release by hand, so a person
clicking a button in the panel cannot win that race. The `Create Channel` form is the wrong tool.

**Why it is possible at all.** Channex's docs say *"Access to the channel API is only for
Whitelabel accounts"*, and that is not true for this account: `POST /channels` validates and
answers `422 {"settings": ["channel with the same settings already exists"]}` — the very message
the panel shows — so contention is detectable programmatically and acquisition is just a retry.

**Politeness matters here**: this is a resource shared with other integrators, not a private
sandbox. One sweep every `SWEEP_SECONDS` across the candidate list is ~2 requests/second at
worst, it stops the instant it wins, and it gives up after `MAX_MINUTES`. Do not turn this into
a tighter loop: Channex publishes no rate limit (one of this change's findings), and the absence
of a documented limit is not permission.

    docker compose exec backend uv run python scripts/channex_claim_test_hotel.py

On success it prints the channel id and the rate plan whose currency matches, which is what the
mapping step needs.
"""

import asyncio
import os
import sys
from datetime import datetime
from typing import Any

import httpx

API_KEY_ENV = "CHANNEX_API_KEY"
BASE_URL_ENV = "CHANNEX_BASE_URL"
DEFAULT_BASE_URL = "https://staging.channex.io/api/v1"
ALLOWED_HOSTS = frozenset({"staging.channex.io", "secure-staging.channex.io"})

CHANNEL_CODE = "BookingCom"
TITLE = "AutoHostAI test (auto-acquired)"

SWEEP_SECONDS = 5.0
MAX_MINUTES = 240

# `12152494` is deliberately absent: the docs say it requires a **real credit card**, and a test
# fixture is not worth putting one in.
CANDIDATES: tuple[tuple[str, str], ...] = (
    ("5868189", "GBP"),
    ("6519420", "GBP"),
    ("11140466", "GBP"),
    ("10745030", "GBP"),
    ("10484818", "JPY"),
    ("10485037", "USD"),
    ("4372137", "EUR"),
)

TAKEN_MARKER = "already exists"


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"channex-claim: {name} is not set in the environment")
    return value


async def _rate_plans(client: httpx.AsyncClient, property_id: str) -> dict[str, str]:
    """Rate plan id per currency, so the winner can be mapped straight away."""
    response = await client.get("/rate_plans", params={"filter[property_id]": property_id})
    response.raise_for_status()
    plans: dict[str, str] = {}
    for row in response.json().get("data") or []:
        attributes = row.get("attributes") or {}
        currency = (attributes.get("currency") or "").upper()
        if currency and currency not in plans:
            plans[currency] = row["id"]
    return plans


async def _attempt(
    client: httpx.AsyncClient, hotel_id: str, property_id: str, group_id: str
) -> tuple[str, Any]:
    body = {
        "channel": {
            "channel": CHANNEL_CODE,
            "property_id": property_id,
            "group_id": group_id,
            "title": f"{TITLE} {hotel_id}",
            "settings": {"hotel_id": hotel_id},
        }
    }
    response = await client.post("/channels", json=body)
    if response.status_code < 300:
        created = response.json().get("data")
        # **`property_id` in the create body is silently ignored.** The channel comes back with
        # `properties: []`, which means it exists but hangs outside the property — and the panel
        # lists channels *under* a property, so it is invisible there and cannot be mapped. Found
        # the hard way: the operator could not find the channel they had just been handed.
        #
        # The association is a separate `PUT`, and `properties` is a **flat array of UUIDs**, not
        # of objects — `[{"property_id": ...}]` returns a 500.
        if created:
            attach = await client.put(
                f"/channels/{created['id']}", json={"channel": {"properties": [property_id]}}
            )
            if attach.status_code >= 300:
                print(
                    f"  WARNING: won {hotel_id} but could not attach the property: "
                    f"{attach.status_code} {attach.text[:150]}",
                    flush=True,
                )
        return "won", created
    text = response.text
    if response.status_code == 422 and TAKEN_MARKER in text:
        return "taken", None
    return "error", f"{response.status_code} {text[:200]}"


async def run(property_id: str, group_id: str) -> int:
    base_url = os.environ.get(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL
    host = httpx.URL(base_url).host
    if host not in ALLOWED_HOSTS:
        raise SystemExit(f"channex-claim: refusing to write against host {host!r}")

    deadline = MAX_MINUTES * 60 / SWEEP_SECONDS
    sweeps = 0
    async with httpx.AsyncClient(
        base_url=base_url, headers={"user-api-key": _env(API_KEY_ENV)}, timeout=30.0
    ) as client:
        plans = await _rate_plans(client, property_id)
        print(f"rate plans by currency: {plans}", flush=True)

        while sweeps < deadline:
            sweeps += 1
            for hotel_id, currency in CANDIDATES:
                outcome, payload = await _attempt(client, hotel_id, property_id, group_id)
                if outcome == "won":
                    stamp = datetime.now().strftime("%H:%M:%S")
                    print(f"\n=== ACQUIRED {hotel_id} ({currency}) at {stamp} ===", flush=True)
                    print(f"channel_id  : {payload.get('id') if payload else '?'}", flush=True)
                    print(f"currency    : {currency}", flush=True)
                    print(f"rate_plan_id: {plans.get(currency, 'MISSING for ' + currency)}", flush=True)
                    print("\nNext: map one room + the FLEX rate against that rate plan.", flush=True)
                    return 0
                if outcome == "error":
                    # Anything that is not plain contention is worth seeing immediately: it may
                    # mean the payload contract moved, and silently retrying would hide it.
                    print(f"  {hotel_id} ({currency}) -> unexpected: {payload}", flush=True)
            if sweeps % 12 == 1:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] sweep {sweeps}: all "
                    f"{len(CANDIDATES)} taken",
                    flush=True,
                )
            await asyncio.sleep(SWEEP_SECONDS)

    print(f"channex-claim: gave up after {MAX_MINUTES} minutes", flush=True)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit(
            "usage: channex_claim_test_hotel.py <property-id> <group-id>  "
            "(both are printed by channex_bootstrap.py / GET /groups)"
        )
    return asyncio.run(run(args[0], args[1]))


if __name__ == "__main__":
    raise SystemExit(main())
