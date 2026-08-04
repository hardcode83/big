"""Measurement bench for the Beds24 API V2 — cost per request, and payload capture.

Lives outside `app/` on purpose (design D1, inheriting D9 of `channex-staging-adapter`): a
throwaway measurement tool must not travel in the deployed package. There is no
`Beds24Adapter` here and no `beds24_*` setting in `app/core/config.py` — this change measures
the provider, `pms-beds24-adapter` integrates it.

Run it from `backend/`:

    BEDS24_REFRESH_TOKEN=... uv run python scripts/beds24_probe.py probe --out /tmp/cost.jsonl
    BEDS24_REFRESH_TOKEN=... uv run python scripts/beds24_probe.py capture bookings
    uv run python scripts/beds24_probe.py report --out /tmp/cost.jsonl

Why this exists: [ADR 0006] picks Beds24 for the MVP but records that its per-request cost is
**dynamic and unpublished** — 100 credits per 5 minutes, per account, with the cost of each
call computed from its complexity. The cadence of the `celery-jobs` scheduler is a function of
that budget, and the budget cannot be derived from documentation. It has to be measured.

Credentials come from the environment ONLY. See `_reject_unknown_arguments`: an argument this
script does not recognise is refused **without echoing it**, because it may be the credential.
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

# `scripts/` is not a package (design D9), so this resolves via sys.path[0] when the script is
# run directly, and via `load_script` in `tests/integrations/conftest.py` under pytest.
from anonymise import anonymise

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "integrations" / "fixtures" / "beds24"

REFRESH_TOKEN_ENV = "BEDS24_REFRESH_TOKEN"
BASE_URL_ENV = "BEDS24_BASE_URL"

# CONFIRMED 2026-08-04 against the provider's published API V2 documentation (step 0): the base
# is `https://beds24.com/api/v2`. There is no `api.` subdomain — it was allowlisted as a guess
# and has been removed, per D8's "deja solo ese". A narrower allowlist is the whole value of
# this constant, so a second spelling "just in case" defeats it.
DEFAULT_BASE_URL = "https://beds24.com/api/v2"
ALLOWED_HOSTS = frozenset({"beds24.com"})

# CONFIRMED 2026-08-04 (step 0). The V2 flow is: invite code -> refresh token -> 24 h access
# token. `GET /authentication/setup` with a `code` header performs the first exchange and is a
# ONE-OFF the operator runs by hand — this script starts from the refresh token, so it never
# holds the invite code. `GET /authentication/token` with a `refreshToken` header performs the
# second, and the access token then travels in a `token` header. The response carries `token`,
# `expiresIn` and `refreshToken`.
REFRESH_HEADER = "refreshToken"
ACCESS_HEADER = "token"
TOKEN_PATH = "/authentication/token"
SETUP_PATH = "/authentication/setup"

# MEASURED 2026-08-04 against the real API. The header is `X-Request-Cost` — **with hyphens**.
# The guessed spelling `x-requestcost` matched nothing, so every measurement would have recorded
# a null cost and the report would have said "cadencia no calculable" with no visible error.
# A silent wrong answer, which is exactly what step 0 exists to catch.
COST_HEADER = "x-request-cost"

# MEASURED alongside it: `X-Five-Min-Limit-Remaining` (a DECIMAL — 96.8, so costs are
# fractional) and `X-Five-Min-Limit-Resets-In` (seconds). Both are picked up by the shape match
# in `_credit_headers`, which needs no change.

# The credit-window model ADR 0006 records. Used to derive the sustainable cadence (R4.4), not
# to discover the ceiling: R4.1 forbids finding the limit by hitting it.
CREDIT_WINDOW_SECONDS = 300
CREDIT_WINDOW_ALLOWANCE = 100

# Self-imposed pacing (R4.3). Conservative on purpose: an accidental run must not eat the
# window another measurement session is using.
DEFAULT_MIN_INTERVAL_SECONDS = 2.0

# Business fields a Beds24 fixture must keep verbatim (R3.2). **Deliberately incomplete.**
#
# The field names of one provider say nothing about another's, and this project already
# learned — in `channex-staging-adapter` — that a provider's documentation does not predict its
# payload. So this starts with what is structurally certain and gets widened after reading the
# first real capture (design D3). That loop is safe because the policy is fail-closed: a key
# missing from here is over-scrubbed, which produces a less useful fixture, never a leak.
PRESERVED_KEYS = frozenset(
    {
        "id",
        "status",
        "currency",
        "propertyid",
        "roomid",
        "bookingid",
        # Never allowlist a credential- or card-shaped name here: `business_keys` is checked
        # BEFORE the PII needles, so a name in this set defeats them (see `anonymise.py`).
        "channel",
        "referer",
        "arrival",
        "departure",
        "numadult",
        "numchild",
        "adults",
        "children",
        "price",
        "commission",
        "bookingtime",
        "modifiedtime",
        "canceltime",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RequestShape:
    """One way of asking for the same thing.

    Each endpoint is measured with at least two of these (R1.2). Without a second shape a
    measurement cannot tell a flat cost from one that scales — and that difference is what
    decides whether the sync may paginate or has to shard.
    """

    label: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogueEntry:
    name: str
    path: str
    method: str
    shapes: tuple[RequestShape, ...]


# The requests the `celery-jobs` sync is expected to make. The axis varied per endpoint is the
# one suspected of moving the cost: page size, date-range width, number of properties.
#
# ASSUMPTION: these paths and their parameter names come from ADR 0006's reading of the V2 API,
# not from a response we have seen. Same status as the header names above, and the same
# remedy — step 0 of the runbook confirms them against the published OpenAPI document before
# the first authenticated call.
CATALOGUE: tuple[CatalogueEntry, ...] = (
    CatalogueEntry(
        name="bookings",
        path="/bookings",
        method="GET",
        shapes=(
            RequestShape("page-10", {"limit": 10}),
            RequestShape("page-100", {"limit": 100}),
            RequestShape("window-1d", {"limit": 10, "arrivalFrom": "P0D", "arrivalTo": "P1D"}),
            RequestShape("window-90d", {"limit": 10, "arrivalFrom": "P0D", "arrivalTo": "P90D"}),
        ),
    ),
    CatalogueEntry(
        name="properties",
        path="/properties",
        method="GET",
        shapes=(
            RequestShape("all", {}),
            RequestShape("single", {"id": 1}),
        ),
    ),
    CatalogueEntry(
        name="calendar",
        path="/inventory/rooms/calendar",
        method="GET",
        shapes=(
            RequestShape("window-7d", {"startDate": "P0D", "endDate": "P7D"}),
            RequestShape("window-90d", {"startDate": "P0D", "endDate": "P90D"}),
        ),
    ),
)

CAPTURES: dict[str, str] = {
    "bookings": "/bookings",
    # EXTERNAL_DEPENDENCY: comes back empty until a booking with a guest conversation exists.
    "messages": "/bookings/messages",
}

SUBCOMMANDS = ("probe", "capture", "report", "provoke")

# CONFIRMED 2026-08-04 (step 0): `POST /bookings` is the documented write endpoint, and the
# response envelope carries `modified`, `errors`, `warnings` and `info`. The `errors` check in
# `_extract_booking_ref` therefore matches a real field, not a guessed one.
#
# STILL AN ASSUMPTION: **where the new booking's id sits in that envelope.** This is the one
# unknown whose failure costs a write, so `_extract_booking_ref` refuses anything it does not
# recognise and `provoke` aborts with the orphan warning rather than guessing.
BOOKINGS_WRITE_PATH = "/bookings"

# The three events `provoke` causes, in order, to give R2.3 its minimum of three measurements.
PROVOKE_ACTIONS = ("create", "modify", "cancel")


class QuotaExhausted(RuntimeError):
    """The account's credit window is spent. Not an error to retry — one to wait out."""


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    """Remove any secret that managed to reach a string bound for a log or an exception.

    Covers the **escaped** rendering as well as the literal one. A credential pasted with a
    stray newline reaches h11 as `b'token\\n'` and comes back embedded in the error message in
    its `repr` form, where a plain `str.replace` of the raw value finds nothing.
    """
    for secret in secrets:
        if not secret:
            continue
        for form in {secret, repr(secret)[1:-1], repr(secret.encode())[2:-1]}:
            if form:
                text = text.replace(form, "***redacted***")
    return text


def assert_host_allowed(url: str) -> None:
    """Refuse any URL that is not HTTPS to an allowlisted host (R6.5).

    Compares the **hostname**, never a substring of the URL: `api.beds24.com.evil.tld` contains
    `api.beds24.com` and a substring check would wave it through. The allowlist is a constant
    here rather than derived from `BEDS24_BASE_URL`, because deriving it would mean whoever
    controls the environment controls the destination — which is the attack it exists to stop.

    **The scheme is checked too, and that is not a formality.** The credential this script
    sends is `BEDS24_REFRESH_TOKEN`, which ADR 0006 records as an **account** credential: it
    grants write access over every property in the account. Allowing `http://beds24.com` would
    put it on the wire in cleartext for any on-path observer, and it takes exactly one dropped
    `s` in an environment variable to get there.
    """
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme != "https":
        raise SystemExit(
            f"beds24-probe: refusing scheme {scheme!r} — only https. An account-level "
            "credential must never travel in cleartext."
        )
    if host not in ALLOWED_HOSTS:
        raise SystemExit(
            f"beds24-probe: refusing to talk to host {host!r}. "
            f"Allowed: {', '.join(sorted(ALLOWED_HOSTS))}."
        )


def _credit_headers(headers: Any) -> dict[str, str]:
    """Whatever the response says about remaining credit (R1.4).

    Matched by shape rather than by a list of names taken from documentation: the point of this
    script is that the provider's documentation is not trusted to describe its own responses.
    """
    found = {}
    for name, value in headers.items():
        lowered = name.lower()
        if lowered == COST_HEADER:
            continue
        if lowered.startswith("x-") and any(
            needle in lowered for needle in ("credit", "limit", "remaining", "cost")
        ):
            found[lowered] = value
    return found


def _parse_cost(headers: Any) -> float | int | None:
    """`X-Request-Cost`, or `None` when the provider did not send it (R1.3).

    **Never zero for a missing header.** An unknown cost and a free call lead to different
    budgets, and conflating them is exactly the mistake this whole change exists to avoid.

    Parsed as a **float**, not an int: `X-Five-Min-Limit-Remaining` came back as `96.8`, so the
    provider bills fractionally. `int("0.2")` raises, which the previous version turned into
    `None` — a fractional cost would have been recorded as "not measured" and silently dropped
    from the budget, making the derived cadence optimistic. An integral value is returned as an
    `int` so the report reads `1` rather than `1.0`.
    """
    raw = headers.get(COST_HEADER)
    if raw is None:
        return None
    try:
        cost = float(str(raw).strip())
    except ValueError:
        return None
    return int(cost) if cost.is_integer() else cost


def build_cost_record(
    *,
    endpoint: str,
    method: str,
    shape: str,
    status: int,
    headers: Any,
    booking_ref: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One measurement, in the schema design D4/D11 fixes.

    `booking_ref` is the key that joins this log to the webhook sink's, which is what makes the
    latency of R2.2 and the out-of-order detection of R2.4 computable at all.
    """
    return {
        "ts_utc": (now or _utc_now()).isoformat(),
        "booking_ref": booking_ref,
        "endpoint": endpoint,
        "method": method,
        "shape": shape,
        "x_request_cost": _parse_cost(headers),
        "credit_headers": _credit_headers(headers),
        "status": status,
    }


def write_records(records: list[dict[str, Any]], out_path: Path) -> Path:
    """One JSON object per line (R1.5).

    Committed alongside the report so the findings derive from reviewable data rather than a
    transcript. Nothing here is sensitive: paths, integers and timestamps.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return out_path


def read_records(out_path: Path) -> list[dict[str, Any]]:
    lines = out_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class Beds24Probe:
    """Transport for the measurement bench: token exchange, host allowlist, pacing.

    The access token is held in memory only (design D7). Caching it on disk would save one
    exchange per run and create a file holding a live credential for 24 hours; the refresh
    token behind it is an **account** credential, so that file would grant write access over
    every property in the account.
    """

    def __init__(
        self,
        *,
        refresh_token: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not refresh_token.strip():
            raise ValueError(f"{REFRESH_TOKEN_ENV} is empty")
        assert_host_allowed(base_url)
        self._refresh_token = refresh_token.strip()
        self._access_token: str | None = None
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)
        self._min_interval = min_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def __repr__(self) -> str:
        """No credential in a repr, a log, or a formatted traceback (R6.4)."""
        return f"<Beds24Probe base_url={self.base_url!r} token=***redacted***>"

    @property
    def _secrets(self) -> tuple[str, ...]:
        return (self._refresh_token, self._access_token or "")

    def authenticate(self) -> None:
        """Exchange the long-lived refresh token for a 24 h access token."""
        url = f"{self.base_url}{TOKEN_PATH}"
        assert_host_allowed(url)
        try:
            response = self._client.get(url, headers={REFRESH_HEADER: self._refresh_token})
        except httpx.HTTPError as exc:
            # This is the ONLY call that carries the refresh token, so it is the one that most
            # needs the redaction wrapper — and it was the one that lacked it. h11 embeds an
            # illegal header value verbatim in its error, so a token pasted with a stray
            # newline would print in full on the operator's very first run.
            raise SystemExit(
                f"beds24-probe: token exchange failed: {_redact(str(exc), self._secrets)}"
            ) from None
        if response.status_code != 200:
            raise SystemExit(
                f"beds24-probe: token exchange failed with HTTP {response.status_code}. "
                "Response body not shown — it can echo what was sent."
            )
        token = (response.json() or {}).get("token")
        if not token:
            raise SystemExit("beds24-probe: token exchange returned no token")
        self._access_token = token

    def _pace(self) -> None:
        """Self-imposed rate limit (R4.3)."""
        if self._last_request_at is not None:
            elapsed = self._monotonic() - self._last_request_at
            remaining = self._min_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        json_body: Any = None,
    ):
        """One paced, host-checked call. Raises `QuotaExhausted` instead of retrying (R4.2)."""
        if self._access_token is None:
            raise RuntimeError("authenticate() must run before any request")
        url = f"{self.base_url}{path}"
        assert_host_allowed(url)
        self._pace()
        try:
            response = self._client.request(
                method,
                url,
                params=params or {},
                json=json_body,
                headers={ACCESS_HEADER: self._access_token},
            )
        except httpx.HTTPError as exc:  # transport failure: never let the token reach the text
            raise SystemExit(
                f"beds24-probe: transport error: {_redact(str(exc), self._secrets)}"
            ) from None
        if response.status_code == 429:
            raise QuotaExhausted(f"credit window spent at {_utc_now().isoformat()}")
        return response


def probe(
    bench: Beds24Probe,
    *,
    catalogue: tuple[CatalogueEntry, ...] = CATALOGUE,
    on_quota_exhausted: Callable[[], None] | None = None,
) -> list[dict[str, Any]]:
    """Walk the catalogue, recording one measurement per request.

    On an exhausted window it stops and waits for the next one rather than retrying
    immediately (R4.2) — hammering a spent quota is how a measurement turns into an outage.
    """
    records: list[dict[str, Any]] = []
    for entry in catalogue:
        for shape in entry.shapes:
            try:
                response = bench.request(entry.method, entry.path, shape.params)
            except QuotaExhausted:
                records.append(
                    {
                        "ts_utc": _utc_now().isoformat(),
                        "booking_ref": None,
                        "endpoint": entry.path,
                        "method": entry.method,
                        "shape": shape.label,
                        "x_request_cost": None,
                        "credit_headers": {},
                        "status": 429,
                    }
                )
                if on_quota_exhausted is not None:
                    on_quota_exhausted()
                return records
            records.append(
                build_cost_record(
                    endpoint=entry.path,
                    method=entry.method,
                    shape=shape.label,
                    status=response.status_code,
                    headers=response.headers,
                )
            )
    return records


def assert_account_has_no_ota_channels(bench: Beds24Probe) -> None:
    """Refuse to write unless the account is the empty measurement account (R6.1).

    This is the pre-flight that `steering/security.md` rule 8 assigns to `CHANNEX_BASE_URL`'s
    staging default — *"ese default apuntando a staging es lo que impide que un descuido
    escriba en una cuenta viva"*. **Beds24 has no staging**, so nothing plays that role here
    and the guard has to be an explicit check instead of a safe default.

    What it protects: REDES11 and PAJARITOS8 are live listings, and Airbnb allows a single
    channel manager per account. An operator with the wrong `BEDS24_REFRESH_TOKEN` exported
    would otherwise create, modify and cancel a booking on a flat that is actually selling.
    """
    # `includeAllRooms=true` because the default `/properties` body is documented as slim, and a
    # slim body is exactly the case that used to read as "no channels connected". Asking for the
    # full shape gives the guard something to recognise; if it still finds no channel field it
    # refuses, which is the point.
    response = bench.request("GET", "/properties", {"includeAllRooms": "true"})
    if response.status_code != 200:
        raise SystemExit(
            "beds24-probe: refusing to write — could not read /properties to confirm the "
            f"account has no OTA channels connected (HTTP {response.status_code})."
        )
    try:
        payload = response.json()
    except ValueError:
        raise SystemExit(
            "beds24-probe: refusing to write — /properties did not return JSON, so the "
            "no-OTA-channels precondition of R6.1 could not be verified."
        ) from None

    recognised, connected = _connected_channels(payload)

    # **Fails CLOSED**, and that is the whole design of this guard. The first version only
    # refused when it positively found a channel, so any response shape it did not recognise
    # read as "clean" — and since the shape is an unverified ASSUMPTION, the most likely real
    # case was the fail-open one. A guard protecting two selling listings cannot treat
    # "I did not understand the answer" as "go ahead".
    #
    # The cost of failing closed is one refusal that the operator resolves in step 0 by
    # confirming the real shape. The cost of failing open is a booking written to REDES11.
    if not recognised:
        raise SystemExit(
            "beds24-probe: REFUSING TO WRITE. Could not find a channel field in the "
            "/properties response, so it is impossible to confirm this account has no OTA "
            "channels connected (R6.1).\n"
            "  This is expected until step 0 of docs/beds24-spike.md confirms the real shape: "
            "add the right key name to `_connected_channels` and re-run.\n"
            "  Do NOT bypass this check — it is the only thing standing between a measurement "
            "and a write to a live listing, and Beds24 has no staging account."
        )
    if connected:
        raise SystemExit(
            "beds24-probe: REFUSING TO WRITE. This account has OTA channels connected "
            f"({len(connected)} found). R6.1 is a hard rule: the measurement account carries "
            "no channels, because writing to one that does can touch a live listing. "
            "Check which account BEDS24_REFRESH_TOKEN belongs to."
        )


def _connected_channels(payload: Any) -> tuple[bool, list[Any]]:
    """`(was a channel field recognised at all, the channels found under it)`.

    The first element is what lets the caller fail closed. Without it a payload carrying no
    channel field is indistinguishable from an account with no channels — and those two need
    opposite answers.

    The channel values are returned raw rather than stringified because the caller only counts
    them: rendering an unverified structure into an error message would print whatever the
    provider nests there, which may include property names or contact data.
    """
    recognised = False
    found: list[Any] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower().replace("_", "")
            if lowered in ("channels", "connectedchannels", "channel", "ota", "otas",
                           "channelmanager"):
                recognised = True
                if isinstance(value, list):
                    found.extend(member for member in value if member)
                elif isinstance(value, dict):
                    found.extend(k for k, v in value.items() if v)
                elif value:
                    found.append(value)
            nested_recognised, nested_found = _connected_channels(value)
            recognised = recognised or nested_recognised
            found.extend(nested_found)
    elif isinstance(payload, list):
        for member in payload:
            nested_recognised, nested_found = _connected_channels(member)
            recognised = recognised or nested_recognised
            found.extend(nested_found)
    return recognised, found


def provoke(bench: Beds24Probe, *, property_id: str) -> list[dict[str, Any]]:
    """Cause three booking events and record each with its `booking_ref` (R2.2, R2.3, D11).

    This exists because R2.2's fallback is worded as *"el registro del sondeo **que provocó el
    hecho**"* — the join between the cost log and the webhook log only works if something on
    our side both causes an event and knows its booking id. Without this the probe log carries
    `booking_ref: null` on every line, the fallback branch is dead code, and any webhook whose
    payload lacks its own timestamp reports no latency at all.

    Create, then modify, then cancel: three events (R2.3's minimum) on one booking, in a known
    order, which is also what makes the out-of-order check of R2.4 meaningful — a single event
    cannot be out of order with anything.

    ASSUMPTION: the request bodies below follow ADR 0006's reading of the V2 write API and are
    confirmed in step 0 of the runbook. `provoke` is the only part of this script that WRITES;
    everything else is a read.
    """
    records: list[dict[str, Any]] = []
    booking_ref: str | None = None

    for action in PROVOKE_ACTIONS:
        if action == "create":
            body = [{"roomId": property_id, "status": "confirmed", "numAdult": 1}]
        elif action == "modify":
            body = [{"id": booking_ref, "numAdult": 2}]
        else:
            body = [{"id": booking_ref, "status": "cancelled"}]

        if action != "create" and booking_ref is None:
            # The create did not give us an id, so the two follow-ups have nothing to act on.
            # Stopping is right: writing without an id could create two more bookings.
            break

        response = bench.request("POST", BOOKINGS_WRITE_PATH, json_body=body)

        if action == "create":
            if response.status_code >= 300:
                raise SystemExit(
                    f"beds24-probe: create failed (HTTP {response.status_code}); not "
                    "attempting modify or cancel. Nothing was written."
                )
            booking_ref = _extract_booking_ref(response)
            if booking_ref is None:
                # The follow-ups are a modify and a CANCEL. Acting on an id we are not certain
                # about means cancelling somebody else's booking, so an unrecognised response
                # shape stops the run. The read-only join refuses an ambiguous id
                # (`beds24_webhook_sink._booking_ref`); the destructive path must be at least
                # as strict, not less.
                raise SystemExit(
                    "beds24-probe: the create response did not carry a booking id in a shape "
                    "this script recognises, so it cannot safely modify or cancel.\n"
                    "  *** A CONFIRMED BOOKING MAY NOW EXIST AND WILL NOT BE CANCELLED. ***\n"
                    "  Check the Beds24 panel and remove it by hand, then fix "
                    "`_extract_booking_ref` against the real response shape (step 0)."
                )

        records.append(
            build_cost_record(
                endpoint=BOOKINGS_WRITE_PATH,
                method="POST",
                shape=f"provoke-{action}",
                status=response.status_code,
                headers=response.headers,
                booking_ref=booking_ref,
            )
        )
    return records


def _extract_booking_ref(response) -> str | None:
    """The id of the booking just created, or `None` if the response did not clearly say.

    Deliberately strict, because the caller uses the result to CANCEL. It accepts an id only
    from a success-shaped element — an error envelope that happens to carry an `id` is not a
    created booking, and treating it as one would send a cancel for something we never made.
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, list):
        if len(payload) != 1:
            return None
        payload = payload[0]
    if not isinstance(payload, dict):
        return None
    # An explicit failure marker disqualifies the element regardless of what else it carries.
    if payload.get("success") is False or payload.get("errors") or payload.get("error"):
        return None
    nested = payload.get("new")
    if not isinstance(nested, dict):
        # `new` as a list is at least as plausible as the dict form — the envelope itself is
        # already a list. Calling `.get` on it raised an AttributeError that escaped all the
        # way out, so the operator got a stack trace instead of the orphan-booking warning and
        # a confirmed booking was left on the account unflagged.
        nested = {}
    for key in ("id", "bookingId", "bookId"):
        value = payload.get(key) or nested.get(key)
        if value:
            return str(value)
    return None


def capture(name: str, path: str, *, bench: Beds24Probe) -> Path:
    """Fetch one payload and write it anonymised (R3.1, R3.2).

    Anonymisation happens **here, at capture time**, not in a later pass: a fixture that has to
    be scrubbed by hand is a fixture that gets committed with real data the day somebody is in
    a hurry. Card-shaped values never reach disk at all (R3.4, `steering/security.md` rule 13)
    — PCI DSS forbids retaining the CVV, so scrubbing is not a courtesy.
    """
    response = bench.request("GET", path)
    response.raise_for_status()
    payload = response.json()
    clean = anonymise(payload, business_keys=PRESERVED_KEYS)
    target = FIXTURE_DIR / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"_anonymised": True, "_substituted": sorted(_substituted_keys(payload, clean)),
             "payload": clean},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def _substituted_keys(original: Any, clean: Any, prefix: str = "") -> set[str]:
    """Which key paths the anonymiser replaced (R3.5).

    Recorded in the fixture so whoever reads the mapping can tell a real value from a
    placeholder — and so the widening loop of design D3 has something to read.

    **It walks the CLEAN tree, never the original.** Walking the original was the first
    version and it defeated the whole point: a key the anonymiser had scrubbed *because it was
    itself a personal datum* — the `{"john.smith@gmail.com": {...}}` case that
    `anonymise.py`'s key-position rule exists for — got its original spelling written straight
    back into the fixture's header, in a field nobody thinks to check. The `payload` block
    looked clean while the PII sat two lines above it, committed to git forever.

    So the paths reported here are built from the **anonymised** keys. A scrubbed key appears
    as `***scrubbed-key***`, which says "something was replaced here" without saying what.
    """
    changed: set[str] = set()
    if isinstance(clean, dict):
        original_items = list(original.items()) if isinstance(original, dict) else []
        for index, (clean_key, clean_value) in enumerate(clean.items()):
            here = f"{prefix}.{clean_key}" if prefix else str(clean_key)
            original_key, original_value = (
                original_items[index] if index < len(original_items) else (None, None)
            )
            if original_key is not None and str(original_key) != str(clean_key):
                changed.add(here)
            changed |= _substituted_keys(original_value, clean_value, here)
    elif isinstance(clean, list):
        original_members = original if isinstance(original, list) else []
        for index, clean_member in enumerate(clean):
            member = original_members[index] if index < len(original_members) else None
            changed |= _substituted_keys(member, clean_member, f"{prefix}[{index}]")
    elif original != clean:
        changed.add(prefix or "<root>")
    return changed


def report(records: list[dict[str, Any]]) -> str:
    """Render the measurements as the table `docs/beds24-spike.md` publishes (D5, R4.4).

    Generated rather than transcribed, so the published number and the recorded data cannot
    drift apart. A `null` cost is reported as `no medido`, never summed as zero.
    """
    lines = ["| Endpoint | Forma | Coste | Estado |", "|---|---|---|---|"]
    total = 0
    unknown = 0
    for record in records:
        cost = record.get("x_request_cost")
        if cost is None:
            unknown += 1
            shown = "no medido"
        else:
            total += cost
            shown = str(cost)
        lines.append(
            f"| `{record['endpoint']}` | {record['shape']} | {shown} | {record['status']} |"
        )

    lines.append("")
    if unknown:
        lines.append(
            f"**{unknown} de {len(records)} peticiones no devolvieron `X-RequestCost`.** "
            "El coste del ciclo es un mínimo, no un total, y la cadencia derivada de él es "
            "optimista: trátala como cota superior hasta medir las que faltan."
        )
        lines.append("")
    lines.append(f"- Coste medido de un ciclo completo: **{total}** créditos.")
    if total > 0:
        per_window = CREDIT_WINDOW_ALLOWANCE / total
        interval = CREDIT_WINDOW_SECONDS / per_window if per_window else 0
        lines.append(
            f"- Ventana del proveedor: **{CREDIT_WINDOW_ALLOWANCE}** créditos / "
            f"{CREDIT_WINDOW_SECONDS} s, por cuenta."
        )
        lines.append(f"- Ciclos que caben en una ventana: **{per_window:.1f}**.")
        lines.append(
            f"- **Cadencia máxima sostenible: un sync cada {interval:.0f} s** "
            f"({interval / 60:.1f} min) por cuenta. Es la cifra que consume `celery-jobs`."
        )
    else:
        lines.append(
            "- **Cadencia máxima sostenible: no calculable** — sin ningún coste medido no hay "
            "nada que dividir."
        )
    return "\n".join(lines) + "\n"


def _is_known_argument(argument: str) -> bool:
    if argument in SUBCOMMANDS or argument in CAPTURES:
        return True
    return bool(
        re.fullmatch(
            r"--out=\S+|--min-interval=\d+(\.\d+)?|--property=[A-Za-z0-9_-]+|--confirm-writes",
            argument,
        )
    )


def _reject_unknown_arguments(argv: list[str]) -> None:
    """Refuse anything unrecognised, **without printing it** (R6.6).

    Shape-based, not spelling-based, and the value is never echoed: an operator who fumbles
    `beds24_probe.py probe <token>` would otherwise put the credential in a terminal transcript
    on top of their shell history.
    """
    for argument in argv:
        if not _is_known_argument(argument):
            raise SystemExit(
                "beds24-probe: unrecognised argument (value not echoed on purpose — it may be "
                f"a credential). Accepted: {', '.join(SUBCOMMANDS)}, capture names "
                f"({', '.join(CAPTURES)}), --out=PATH, --min-interval=SECONDS. The refresh "
                f"token is read from {REFRESH_TOKEN_ENV} and must never be passed on the "
                "command line, where it would stay in your shell history."
            )


def _refresh_token() -> str:
    token = os.environ.get(REFRESH_TOKEN_ENV, "").strip()
    if not token:
        raise SystemExit(f"beds24-probe: {REFRESH_TOKEN_ENV} is not set in the environment")
    return token


def _option(argv: list[str], prefix: str, default: str) -> str:
    for argument in argv:
        if argument.startswith(prefix):
            return argument.removeprefix(prefix)
    return default


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _reject_unknown_arguments(args)

    subcommand = next((a for a in args if a in SUBCOMMANDS), None)
    if subcommand is None:
        raise SystemExit(f"beds24-probe: expected one of {', '.join(SUBCOMMANDS)}")

    out_path = Path(_option(args, "--out=", "/tmp/beds24-request-cost.jsonl"))

    if subcommand == "report":
        print(report(read_records(out_path)), end="")
        return 0

    # Checked before the credential is even read: the operator must be told that this
    # subcommand writes before they are told anything else about why it will not run.
    if subcommand == "provoke" and "--confirm-writes" not in args:
        raise SystemExit(
            "beds24-probe: `provoke` is the only subcommand that WRITES to the provider — it "
            "creates, modifies and cancels a booking. Re-run with --confirm-writes once you "
            "have checked that BEDS24_REFRESH_TOKEN belongs to the empty measurement account "
            "and not to one with live listings (R6.1)."
        )

    bench = Beds24Probe(
        refresh_token=_refresh_token(),
        base_url=os.environ.get(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL,
        min_interval_seconds=float(
            _option(args, "--min-interval=", str(DEFAULT_MIN_INTERVAL_SECONDS))
        ),
    )
    bench.authenticate()

    if subcommand == "probe":
        records = probe(bench)
        written = write_records(records, out_path)
        print(f"beds24-probe: {len(records)} measurements -> {written}")
        return 0

    if subcommand == "provoke":
        property_id = _option(args, "--property=", "")
        if not property_id:
            raise SystemExit("beds24-probe: provoke needs --property=<room or property id>")
        assert_account_has_no_ota_channels(bench)
        records = provoke(bench, property_id=property_id)
        existing = read_records(out_path) if out_path.exists() else []
        written = write_records(existing + records, out_path)
        refs = sorted({r["booking_ref"] for r in records if r["booking_ref"]})
        print(f"beds24-probe: {len(records)} events (booking_ref={refs or 'none'}) -> {written}")
        return 0

    requested = [a for a in args if a in CAPTURES] or list(CAPTURES)
    for name in requested:
        written = capture(name, CAPTURES[name], bench=bench)
        print(f"beds24-probe: {CAPTURES[name]} -> {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
