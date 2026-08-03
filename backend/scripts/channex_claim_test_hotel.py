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
import uuid
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

# Statuses that mean "stop", not "retry": bad or revoked credential, no access, wrong ids.
FATAL_STATUSES = frozenset({401, 403, 404})
# Throttling and provider faults: back off instead of hammering at the fixed sweep rate.
BACKOFF_STATUSES = frozenset({429, 500, 502, 503, 504})
BACKOFF_SECONDS = 60.0


def _error_detail(response: httpx.Response) -> str:
    """The documented `{"errors": {...}}` envelope, never the raw body.

    Same posture as `app/integrations/infrastructure/channex/client.py`: a 4xx body can echo what
    was sent, and what was sent might be a pasted credential.
    """
    try:
        body = response.json()
    except ValueError:
        return "unparseable error body"
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, dict):
        return f"code={errors.get('code')!r} details={errors.get('details')!r}"
    return "no `errors` object"


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
    if response.status_code in FATAL_STATUSES:
        # Abort, do not retry. With a 5s sweep over 7 candidates for up to 4 hours, a revoked or
        # mistyped key would otherwise produce ~17.000 failed WRITE attempts against a third
        # party's account shared with other integrators — the opposite of the politeness this
        # module claims in its own docstring. Found by the feature-scale security panel.
        raise SystemExit(
            f"channex-claim: aborting — provider answered {response.status_code} "
            f"({_error_detail(response)}). Check {API_KEY_ENV} and the ids."
        )
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
                # **Fatal, not a warning.** The first version printed and still returned "won",
                # which hands the operator a channel that is invisible in the panel and cannot be
                # mapped — while the slot is consumed and another integrator cannot take it. Worth
                # failing loudly so it gets fixed instead of looking like a success.
                # `_error_detail`, not the raw body, for the same reason as everywhere else.
                raise SystemExit(
                    f"channex-claim: won {hotel_id} but could NOT attach the property "
                    f"({attach.status_code} {_error_detail(attach)}). Channel "
                    f"{created['id']} exists and is unusable — attach it or delete it."
                )
        return "won", created
    if response.status_code == 422 and TAKEN_MARKER in response.text:
        return "taken", None
    # Status plus the documented `errors` object — never the raw body. A 4xx validation body
    # echoes back what was sent, so if an operator pasted the API key where an id belongs it
    # would land in the terminal or a CI log (R2.3). `client.py` refuses the same fallback.
    return "error", f"{response.status_code} {_error_detail(response)}"


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
                    if any(str(code) in str(payload).split()[0] for code in BACKOFF_STATUSES):
                        # Throttled or the provider is unwell: waiting is the cooperative move,
                        # and retrying at the sweep rate would make it worse.
                        print(f"  backing off {BACKOFF_SECONDS:.0f}s", flush=True)
                        await asyncio.sleep(BACKOFF_SECONDS)
            if sweeps % 12 == 1:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] sweep {sweeps}: all "
                    f"{len(CANDIDATES)} taken",
                    flush=True,
                )
            await asyncio.sleep(SWEEP_SECONDS)

    print(f"channex-claim: gave up after {MAX_MINUTES} minutes", flush=True)
    return 1


USAGE = (
    "usage: channex_claim_test_hotel.py <property-id> <group-id>  "
    "(both are UUIDs, printed by channex_bootstrap.py / GET /groups). "
    f"The API key comes from {API_KEY_ENV} and must never be passed as an argument."
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit(USAGE)
    # **Both positionals must parse as UUIDs, and a rejected value is never echoed.** Without
    # this, an operator who pastes the organisation API key where `<group-id>` belongs sends it
    # to Channex as a `group_id`, and it comes back inside the 422 validation body — into the
    # terminal and any CI log, on top of the shell history. R4.4 and R2.3, and the posture
    # `channex_probe.py` already takes for the same class of mistake.
    for label, value in (("property-id", args[0]), ("group-id", args[1])):
        try:
            uuid.UUID(value)
        except ValueError:
            raise SystemExit(
                f"channex-claim: {label} is not a UUID (value not echoed on purpose — it may "
                f"be a credential).\n{USAGE}"
            ) from None
    return asyncio.run(run(args[0], args[1]))


if __name__ == "__main__":
    raise SystemExit(main())
