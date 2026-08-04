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
import re
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


def _find_key(payload: Any, key: str) -> Any:
    """Depth-first search for one exact key anywhere in the payload."""
    if isinstance(payload, dict):
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
        for value in payload.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for member in payload:
            found = _find_key(member, key)
            if found is not None:
                return found
    return None


def _first_present(payload: Any, keys: tuple[str, ...]) -> Any:
    """The value of the most specific of `keys` present anywhere in the payload.

    **Priority is per key, not per nesting level**, and that distinction is the whole point.
    The first version walked the tree once and, at each node, accepted whichever of `keys` that
    node happened to have — so on a payload shaped like

        {"property": {"id": 99}, "booking": {"id": 555}}

    it returned the *property* id, because `property` sorts first among the dict's values. A
    wrong join key is worse than a missing one: `None` shows up as an unmeasured latency, while
    99 quietly produces a plausible wrong number in the published findings.

    So each key is searched across the whole payload before the next is tried, which puts the
    unambiguous spellings (`bookingId`, `booking_id`) ahead of the bare `id` fallback.
    """
    for key in keys:
        found = _find_key(payload, key)
        if found is not None:
            return found
    return None


def _booking_ref(payload: Any) -> str | None:
    """The booking identity, or `None` when it cannot be established unambiguously.

    The bare `id` fallback only applies when the payload carries **exactly one** `id` anywhere.
    With more than one there is no way to tell the booking's from a room's or a property's, and
    guessing would corrupt both the latency of R2.2 and the ordering check of R2.4 with a
    number that looks perfectly reasonable in the output.
    """
    for key in BOOKING_REF_KEYS:
        if key == "id":
            continue
        found = _find_key(payload, key)
        if found is not None:
            return str(found)

    ids = _collect_key(payload, "id")
    if len(ids) == 1:
        return str(ids[0])
    return None


def _collect_key(payload: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(payload, dict):
        for member_key, value in payload.items():
            if member_key == key and value not in (None, ""):
                found.append(value)
            found.extend(_collect_key(value, key))
    elif isinstance(payload, list):
        for member in payload:
            found.extend(_collect_key(member, key))
    return found


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

    booking_ref = _booking_ref(payload)
    event_time = _first_present(payload, EVENT_TIME_KEYS)

    # Neither the query string nor the literal path. `self.path` is the full request target,
    # and the secret can live in EITHER half: the runbook has the operator paste a tunnel URL
    # into the webhook config, and the product route this measurement feeds is
    # `/api/v1/webhooks/{provider}/{webhook_token}` — rule 12(b) puts an unguessable token in
    # the **path** by design. Reducing only the query was half the job; an operator imitating
    # the product convention would have written the route secret into the log in cleartext.
    path_only, _, query = path.partition("?")
    segments = [seg for seg in path_only.split("/") if seg]

    return {
        "received_at_utc": received_at,
        "booking_ref": str(booking_ref) if booking_ref is not None else None,
        "event_time": str(event_time) if event_time is not None else None,
        "method": method,
        # Shape, not content: how many segments the route had, and the first one if it is a
        # plain word. Enough to tell "/hook" from "/a/b/c" when debugging, useless to anyone
        # who wants to forge a request.
        "path_depth": len(segments),
        "path_head": segments[0] if segments and segments[0].isalpha() else None,
        "query_keys": sorted({pair.partition("=")[0] for pair in query.split("&") if pair}),
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
    by_ref: dict[str, list[datetime]] = {}
    for record in probe_records or []:
        ref = record.get("booking_ref")
        moment = _parse(record.get("ts_utc"))
        if ref is not None and moment is not None:
            by_ref.setdefault(str(ref), []).append(moment)

    results = []
    for webhook in webhooks:
        received = _parse(webhook.get("received_at_utc"))
        source = "payload"
        event_at = _parse(webhook.get("event_time"))
        if event_at is None:
            source = "probe"
            # The LATEST probe line for this ref that precedes the webhook, not the first one
            # in the file. `provoke` writes three lines for one booking — create, modify,
            # cancel — so a booking_ref legitimately repeats, and taking the first would
            # measure the cancel webhook against the create request and report a latency of
            # minutes where the real one is seconds.
            candidates = [
                moment
                for moment in by_ref.get(webhook.get("booking_ref") or "", [])
                if received is None or moment <= received
            ]
            event_at = max(candidates) if candidates else None
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


def make_handler(
    out_path: Path, records: list[dict[str, Any]], dropped_counter: list[int] | None = None
):
    dropped: list[int] = [] if dropped_counter is None else dropped_counter

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — the stdlib dictates this name
            # Everything is wrapped, because an exception escaping this method is handled by
            # `socketserver.BaseServer.handle_error`, which prints a traceback straight to
            # stderr and never passes through `log_message`. That traceback embeds
            # request-derived text — a raw header value, a fragment of the body — which is
            # exactly what this sink promises never to emit.
            try:
                length = self._body_length()
                if length is None:
                    self.send_response(400)
                    self.end_headers()
                    return
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
            except Exception:  # noqa: BLE001 — nothing request-derived may reach stderr
                # Silence would be worse than the traceback this replaced. R2.3 needs at least
                # three events, and a webhook dropped to a full disk during the measurement
                # window has to be visible NOW — reconstructing it later means re-provoking on
                # a trial that is counting down. The message is a fixed string: nothing derived
                # from the request, which is the whole reason the traceback had to go.
                dropped.append(1)
                print(
                    f"beds24-webhook-sink: DROPPED a webhook (write or parse failed). "
                    f"{len(dropped)} lost so far — the measurement is incomplete.",
                    file=sys.stderr,
                )
                try:
                    self.send_response(500)
                    self.end_headers()
                except Exception:  # noqa: BLE001 — the connection is already gone
                    pass

        def _body_length(self) -> int | None:
            """The declared body size, clamped, or `None` if the header is unusable.

            `min(int(...), MAX_BODY_BYTES)` was the first version and a negative
            `Content-Length` sailed through it: `min(-1, 1_000_000)` is `-1`, and
            `rfile.read(-1)` reads until EOF. For the whole measurement window this sink is an
            unauthenticated, internet-reachable endpoint that writes to disk, so an unbounded
            read is somebody filling the operator's disk and ending the session.
            """
            raw = self.headers.get("Content-Length")
            if raw is None:
                return 0
            try:
                declared = int(raw)
            except (TypeError, ValueError):
                return None
            if declared < 0:
                return None
            return min(declared, MAX_BODY_BYTES)

        def log_message(self, format, *args):  # noqa: A002 — stdlib signature
            """Silenced: the default logs the request line, and a query string could carry data."""

    return Handler


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out_path = DEFAULT_OUT
    port = DEFAULT_PORT
    # Shape-checked BEFORE conversion, and nothing is ever echoed. Matching the prefix was not
    # enough: `--port=<pasted token>` used to reach `int()`, whose ValueError prints the value
    # verbatim in a traceback — which is precisely the fumble R6.6 exists to prevent, just
    # arriving through an accepted flag instead of a rejected one.
    for argument in args:
        if re.fullmatch(r"--out=\S+", argument):
            out_path = Path(argument.removeprefix("--out="))
        elif re.fullmatch(r"--port=\d{1,5}", argument):
            port = int(argument.removeprefix("--port="))
        else:
            raise SystemExit(
                "beds24-webhook-sink: unrecognised or malformed argument (value not echoed on "
                "purpose — it may be a credential). Accepted: --out=PATH, --port=N."
            )

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # `exc` renders the path, which came from argv — same non-echoing rule applies.
        raise SystemExit(
            f"beds24-webhook-sink: cannot create the output directory ({exc.strerror})."
        ) from None
    received: list[dict[str, Any]] = []
    dropped: list[int] = []
    server = HTTPServer(("127.0.0.1", port), make_handler(out_path, received, dropped))
    print(f"beds24-webhook-sink: listening on http://127.0.0.1:{port} -> {out_path}")
    print(f"expose it with:  cloudflared tunnel --url http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\nbeds24-webhook-sink: stopped. {len(received)} received, {len(dropped)} dropped.")
        if dropped:
            print(
                "  Some webhooks were lost, so the latency sample is incomplete — "
                "provoke the missing events again before writing the findings.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
