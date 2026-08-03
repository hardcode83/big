"""Timestamped receiver for Beds24 webhooks, to measure their latency and their ordering.

Lives outside `app/` (design D1/D9) and is **not** the product's webhook endpoint. Our API
still exposes no inbound route and this script never writes to `webhook_events`. Building the
real thing means satisfying rule 12 of `steering/security.md` in full — per-tenant static
header compared in constant time, unguessable per-tenant route, rate limit, body cap, and an
API re-read that is queued and coalesced rather than one outbound call per webhook received —
and that is the entire scope of `reservations-webhooks`.

Run it from `backend/`, then expose it with an ephemeral tunnel:

    uv run python scripts/beds24_webhook_sink.py --out /tmp/beds24-webhooks.jsonl
    cloudflared tunnel --url http://localhost:8099

Why a local receiver rather than a public capture service (design D6): the timestamp has to be
**ours** — it is literally the quantity being measured, and an intermediary would add its own
latency to the number — and the reservation payload must not leave the machine.

**Nothing raw reaches disk.** The body and the headers go through the same fail-closed
anonymiser the fixture capture uses, before the line is written. A webhook receiver that
persists the raw body is precisely the pattern rule 13 of `steering/security.md` forbids, and
it forbids it at design time, not as a cleanup pass. Of the headers only the **names** survive:
one of them is the static credential Beds24 uses in place of a signature.
"""

import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

# `scripts/` is not a package (design D9); resolved via sys.path[0] or the pytest loader.
from anonymise import anonymise

DEFAULT_PORT = 8099
DEFAULT_OUT = Path("/tmp/beds24-webhooks.jsonl")
MAX_BODY_BYTES = 1_000_000

# Business fields a webhook record may keep verbatim. Same fail-closed contract as the probe's
# allowlist, and the same warning: never list a credential- or card-shaped name here, because
# `business_keys` is checked before the PII needles.
PRESERVED_KEYS = frozenset(
    {
        "id",
        "status",
        "action",
        "bookingid",
        "propertyid",
        "roomid",
        "arrival",
        "departure",
        "bookingtime",
        "modifiedtime",
        "canceltime",
        "timestamp",
    }
)

# ASSUMPTION: the payload keys that carry the booking identity, confirmed on the first real
# webhook. `booking_ref` is what joins this log to the probe's cost log (design D11) — without
# it the latency of R2.2 cannot be computed, so a miss here is worth noticing rather than
# silently degrading.
BOOKING_REF_KEYS = ("bookingId", "bookingid", "booking_id", "id")

# ASSUMPTION: the payload key carrying the provider's own timestamp for the event.
EVENT_TIME_KEYS = ("modifiedTime", "modifiedtime", "bookingTime", "timestamp", "time")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _first_present(payload: Any, keys: tuple[str, ...]) -> Any:
    """Depth-first search for the first of `keys` present anywhere in the payload."""
    if isinstance(payload, dict):
        for key in keys:
            if key in payload and payload[key] not in (None, ""):
                return payload[key]
        for value in payload.values():
            found = _first_present(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for member in payload:
            found = _first_present(member, keys)
            if found is not None:
                return found
    return None


def build_webhook_record(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One received webhook, in the schema design D6/D11 fixes.

    `received_at_utc` is stamped here, at the moment of arrival, because that instant is the
    measurement. Everything else is anonymised or reduced to a name.
    """
    received_at = (now or _utc_now()).isoformat()
    try:
        payload = json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None

    booking_ref = _first_present(payload, BOOKING_REF_KEYS)
    event_time = _first_present(payload, EVENT_TIME_KEYS)

    return {
        "received_at_utc": received_at,
        "booking_ref": str(booking_ref) if booking_ref is not None else None,
        "event_time": str(event_time) if event_time is not None else None,
        "method": method,
        "path": path,
        # Names only. One of these is the static header Beds24 offers instead of a signature,
        # and its value is a credential (R2.5).
        "header_names": sorted(name.lower() for name in headers),
        "body": anonymise(payload, business_keys=PRESERVED_KEYS) if payload is not None else None,
    }


def _parse(moment: str | None) -> datetime | None:
    if not moment:
        return None
    try:
        parsed = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def compute_latencies(
    webhooks: list[dict[str, Any]], probe_records: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Latency per webhook, by the two-step rule of design D11 (R2.2).

    The instant of the event is taken from the payload's own timestamp when it carries one;
    otherwise from the probe log line with the same `booking_ref` — the probe is what caused
    the event, so the instant of its response is an upper bound on when the event happened.

    A webhook that can be correlated by neither route reports `None` rather than a guess.
    Matching by temporal proximity was rejected: it breaks as soon as two events share a
    window, which is exactly the scenario R2.4 wants to measure.
    """
    by_ref = {}
    for record in probe_records or []:
        ref = record.get("booking_ref")
        if ref is not None:
            by_ref.setdefault(str(ref), record)

    results = []
    for webhook in webhooks:
        received = _parse(webhook.get("received_at_utc"))
        source = "payload"
        event_at = _parse(webhook.get("event_time"))
        if event_at is None:
            source = "probe"
            match = by_ref.get(webhook.get("booking_ref") or "")
            event_at = _parse(match.get("ts_utc")) if match else None
        if event_at is None or received is None:
            results.append(
                {"booking_ref": webhook.get("booking_ref"), "latency_seconds": None, "source": None}
            )
            continue
        results.append(
            {
                "booking_ref": webhook.get("booking_ref"),
                "latency_seconds": (received - event_at).total_seconds(),
                "source": source,
            }
        )
    return results


def detect_out_of_order(latencies: list[dict[str, Any]], webhooks: list[dict[str, Any]]) -> bool:
    """Did the webhooks arrive in a different order than the events that caused them (R2.4)?

    ADR 0006 states the provider gives no ordering guarantee, and `reservations-webhooks`
    depends on that being true, so it gets checked rather than assumed.
    """
    pairs = []
    for latency, webhook in zip(latencies, webhooks):
        received = _parse(webhook.get("received_at_utc"))
        if latency["latency_seconds"] is None or received is None:
            continue
        pairs.append((received.timestamp() - latency["latency_seconds"], received.timestamp()))

    arrival_by_event = [arrival for _, arrival in sorted(pairs, key=lambda pair: pair[0])]
    return arrival_by_event != sorted(arrival_by_event)


def make_handler(out_path: Path, records: list[dict[str, Any]]):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — the stdlib dictates this name
            length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY_BYTES)
            body = self.rfile.read(length) if length else b""
            record = build_webhook_record(
                method="POST",
                path=self.path,
                headers=dict(self.headers.items()),
                body=body,
            )
            records.append(record)
            with out_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):  # noqa: A002 — stdlib signature
            """Silenced: the default logs the request line, and a query string could carry data."""

    return Handler


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out_path = DEFAULT_OUT
    port = DEFAULT_PORT
    for argument in args:
        if argument.startswith("--out="):
            out_path = Path(argument.removeprefix("--out="))
        elif argument.startswith("--port="):
            port = int(argument.removeprefix("--port="))
        else:
            raise SystemExit(
                "beds24-webhook-sink: unrecognised argument (value not echoed on purpose). "
                "Accepted: --out=PATH, --port=N."
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    server = HTTPServer(("127.0.0.1", port), make_handler(out_path, []))
    print(f"beds24-webhook-sink: listening on http://127.0.0.1:{port} -> {out_path}")
    print("expose it with:  cloudflared tunnel --url http://localhost:%d" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeds24-webhook-sink: stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
