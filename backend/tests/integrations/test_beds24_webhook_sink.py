"""The Beds24 webhook sink (`scripts/beds24_webhook_sink.py`), section 5.

Offline like the rest of the suite: these drive the pure functions directly rather than
standing up the HTTP server, which is a thin stdlib shell over `build_webhook_record`.
"""

import json

import pytest

from tests.integrations.conftest import load_script

sink = load_script("beds24_webhook_sink")


def _record(body, headers=None, now=None):
    return sink.build_webhook_record(
        method="POST",
        path="/hook",
        headers=headers or {"Content-Type": "application/json"},
        body=json.dumps(body).encode("utf-8"),
        now=now,
    )


# --- 5.1: nothing raw reaches disk ----------------------------------------------------------


def test_card_data_in_a_webhook_body_leaves_no_trace():
    """R3.4 / security rule 13 — the receiver is named in that rule, not just the adapter."""
    record = _record(
        {
            "bookingId": 42,
            "card_number": "4111111111111111",
            "cvv": "123",
            "expiration_date": "12/2027",
        }
    )

    raw = json.dumps(record)
    for leaked in ("4111111111111111", "12/2027"):
        assert leaked not in raw, leaked


def test_the_static_auth_header_value_never_reaches_the_record():
    """R2.5 — Beds24 offers a static header instead of a signature, so it is a credential."""
    record = _record(
        {"bookingId": 1},
        headers={"X-Beds24-Secret": "the-shared-secret", "Content-Type": "application/json"},
    )

    assert "the-shared-secret" not in json.dumps(record)
    assert "x-beds24-secret" in record["header_names"]


def test_guest_personal_data_in_the_body_is_scrubbed():
    record = _record({"bookingId": 1, "guestName": "Ana Perez", "guestEmail": "ana@gmail.com"})

    raw = json.dumps(record)
    assert "Ana Perez" not in raw
    assert "ana@gmail.com" not in raw
    assert record["booking_ref"] == "1"


def test_a_non_json_body_does_not_crash_the_receiver():
    record = sink.build_webhook_record(
        method="POST", path="/hook", headers={}, body=b"\xff\xfe not json"
    )

    assert record["body"] is None
    assert record["booking_ref"] is None


def test_the_reception_instant_is_stamped_by_us():
    """D6 — the timestamp is the measurement, so it must not come from an intermediary."""
    from datetime import datetime, timezone

    moment = datetime(2026, 8, 3, 13, 19, 39, tzinfo=timezone.utc)

    record = _record({"bookingId": 1}, now=moment)

    assert record["received_at_utc"] == "2026-08-03T13:19:39+00:00"


# --- 5.2: latency by booking_ref ------------------------------------------------------------


def test_latency_prefers_the_payload_timestamp():
    """R2.2 step 1 — the provider's own instant, when it sends one."""
    webhooks = [
        {
            "received_at_utc": "2026-08-03T13:20:39+00:00",
            "booking_ref": "BK-1",
            "event_time": "2026-08-03T13:19:39+00:00",
        }
    ]

    [result] = sink.compute_latencies(webhooks, [])

    assert result["latency_seconds"] == 60.0
    assert result["source"] == "payload"


def test_latency_falls_back_to_the_probe_line_with_the_same_booking_ref():
    """R2.2 step 2 — the probe caused the event, so its response is an upper bound."""
    webhooks = [
        {
            "received_at_utc": "2026-08-03T13:20:39+00:00",
            "booking_ref": "BK-1",
            "event_time": None,
        }
    ]
    probe_records = [
        {"ts_utc": "2026-08-03T13:19:09+00:00", "booking_ref": "BK-1"},
        {"ts_utc": "2026-08-03T13:00:00+00:00", "booking_ref": "BK-OTHER"},
    ]

    [result] = sink.compute_latencies(webhooks, probe_records)

    assert result["latency_seconds"] == 90.0
    assert result["source"] == "probe"


def test_an_uncorrelatable_webhook_reports_none_rather_than_a_guess():
    """Matching by temporal proximity was rejected precisely to avoid inventing this number."""
    webhooks = [
        {"received_at_utc": "2026-08-03T13:20:39+00:00", "booking_ref": None, "event_time": None}
    ]

    [result] = sink.compute_latencies(webhooks, [{"ts_utc": "2026-08-03T13:19:00+00:00"}])

    assert result["latency_seconds"] is None
    assert result["source"] is None


# --- 5.3: ordering ---------------------------------------------------------------------------


def test_out_of_order_arrival_is_detected():
    """R2.4 — ADR 0006 says the provider gives no ordering guarantee; this checks it."""
    webhooks = [
        # event at 13:00, arrived 13:02
        {
            "received_at_utc": "2026-08-03T13:02:00+00:00",
            "booking_ref": "A",
            "event_time": "2026-08-03T13:00:00+00:00",
        },
        # event at 13:01 (later), arrived 13:01:30 (earlier) -> inverted
        {
            "received_at_utc": "2026-08-03T13:01:30+00:00",
            "booking_ref": "B",
            "event_time": "2026-08-03T13:01:00+00:00",
        },
    ]

    latencies = sink.compute_latencies(webhooks, [])

    assert sink.detect_out_of_order(latencies, webhooks) is True


def test_in_order_arrival_is_not_flagged():
    webhooks = [
        {
            "received_at_utc": "2026-08-03T13:00:30+00:00",
            "booking_ref": "A",
            "event_time": "2026-08-03T13:00:00+00:00",
        },
        {
            "received_at_utc": "2026-08-03T13:01:30+00:00",
            "booking_ref": "B",
            "event_time": "2026-08-03T13:01:00+00:00",
        },
    ]

    latencies = sink.compute_latencies(webhooks, [])

    assert sink.detect_out_of_order(latencies, webhooks) is False


@pytest.mark.parametrize("argument", ["--nope", "some-token"])
def test_unrecognised_arguments_are_refused_without_echoing(argument):
    with pytest.raises(SystemExit) as excinfo:
        sink.main([argument])

    assert argument not in str(excinfo.value)


# --- Panel fixes (sections 2-6 review) -------------------------------------------------------


def test_booking_ref_is_not_confused_with_a_property_id():
    """A wrong join key is worse than a missing one: it produces a plausible wrong number.

    Regression for the DFS that accepted whichever of the candidate keys a node happened to
    have, returning the property id from `{"property": {"id": 99}, "booking": {"id": 555}}`.
    """
    record = _record(
        {
            "type": "booking",
            "property": {"id": 99, "name": "Redes 11"},
            "booking": {"id": 555, "arrival": "2026-09-01", "status": "confirmed"},
        }
    )

    assert record["booking_ref"] != "99"
    assert record["booking_ref"] is None, "two bare ids is ambiguous — refuse rather than guess"


def test_an_unambiguous_booking_key_wins_over_a_bare_id():
    record = _record({"property": {"id": 99}, "booking": {"bookingId": 555}})

    assert record["booking_ref"] == "555"


def test_a_single_bare_id_is_still_accepted():
    record = _record({"booking": {"id": 555, "status": "confirmed"}})

    assert record["booking_ref"] == "555"


def test_the_query_string_never_reaches_disk():
    """The runbook has the operator paste a tunnel URL into a panel; secrets land in URLs."""
    record = sink.build_webhook_record(
        method="POST",
        path="/hook?token=STATIC-AUTH-SECRET&mail=ana@gmail.com",
        headers={},
        body=b"{}",
    )

    rendered = json.dumps(record)
    assert "STATIC-AUTH-SECRET" not in rendered
    assert "ana@gmail.com" not in rendered
    assert record["path_depth"] == 1
    assert record["path_head"] == "hook"
    assert record["query_keys"] == ["mail", "token"]


@pytest.mark.parametrize("declared,expected", [("-1", None), ("12abc", None), ("", None),
                                               ("50", 50), ("99999999", 1_000_000)])
def test_content_length_is_clamped_and_never_negative(declared, expected):
    """`min(-1, MAX)` is -1, and `rfile.read(-1)` reads until EOF — an unbounded write to disk."""

    from pathlib import Path

    handler_cls = sink.make_handler(Path("/tmp/unused.jsonl"), [])
    instance = handler_cls.__new__(handler_cls)
    instance.headers = {"Content-Length": declared}

    assert handler_cls._body_length(instance) == expected


def test_probe_fallback_picks_the_latest_preceding_line_for_a_repeated_ref():
    """`provoke` writes three lines for one booking, so a ref legitimately repeats."""
    webhooks = [
        {
            "received_at_utc": "2026-08-03T13:10:05+00:00",
            "booking_ref": "BK-1",
            "event_time": None,
        }
    ]
    probe_records = [
        {"ts_utc": "2026-08-03T13:00:00+00:00", "booking_ref": "BK-1"},
        {"ts_utc": "2026-08-03T13:10:00+00:00", "booking_ref": "BK-1"},
    ]

    [result] = sink.compute_latencies(webhooks, probe_records)

    assert result["latency_seconds"] == 5.0, "must not measure against the create request"


def test_ref_matching_is_not_nearest_timestamp_matching():
    """The discriminator the previous test lacked: the nearest line has the WRONG ref.

    Design D11 rejects proximity matching explicitly — "falla en cuanto hay dos hechos en la
    misma ventana". This fails if the implementation ever drifts back to it.
    """
    webhooks = [
        {
            "received_at_utc": "2026-08-03T13:10:05+00:00",
            "booking_ref": "BK-1",
            "event_time": None,
        }
    ]
    probe_records = [
        {"ts_utc": "2026-08-03T13:00:00+00:00", "booking_ref": "BK-1"},
        # Nearest in time, but a DIFFERENT booking.
        {"ts_utc": "2026-08-03T13:10:04+00:00", "booking_ref": "BK-OTHER"},
    ]

    [result] = sink.compute_latencies(webhooks, probe_records)

    assert result["latency_seconds"] == 605.0, "proximity matching would report 1.0"


def test_an_unguessable_route_token_is_not_persisted():
    """Rule 12(b) puts the secret IN the path, so reducing only the query was half the job.

    The product route is `/api/v1/webhooks/{provider}/{webhook_token}`; an operator imitating
    that convention here would otherwise have written the token into the log in cleartext.
    """
    record = sink.build_webhook_record(
        method="POST",
        path="/api/v1/webhooks/beds24/9f3a2c7e1b4d8a6f0c5e",
        headers={},
        body=b"{}",
    )

    rendered = json.dumps(record)
    assert "9f3a2c7e1b4d8a6f0c5e" not in rendered
    assert record["path_depth"] == 5
    assert record["path_head"] == "api"
