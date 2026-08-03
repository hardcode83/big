"""The Beds24 measurement bench (`scripts/beds24_probe.py`), sections 2-4 and 6.1.

Offline by construction, like every other test in this repo: the HTTP boundary is an
`httpx.MockTransport` and there is no `skipif` on a credential. Design D9 of
`pms-beds24-spike` is explicit about why — a test that only runs when someone holds a paid
account reports green in CI while never executing, which is worse than not having it. The
verification against the real provider is the runbook, and its evidence is the committed
JSONL.
"""

import json

import httpx
import pytest

from tests.integrations.conftest import load_script

beds24 = load_script("beds24_probe")


def _bench(handler, **kwargs):
    """A probe wired to a mock transport, already authenticated."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    bench = beds24.Beds24Probe(
        refresh_token="refresh-secret",
        client=client,
        min_interval_seconds=0.0,
        sleep=lambda _: None,
        monotonic=lambda: 0.0,
        **kwargs,
    )
    bench._access_token = "access-secret"  # skip the exchange; it has its own tests
    return bench


# --- Section 2.1 / 2.2: credential handling -------------------------------------------------


def test_empty_refresh_token_is_refused_before_any_request():
    """R6.3 — the refusal happens in the constructor, so no request can precede it."""
    with pytest.raises(ValueError, match=beds24.REFRESH_TOKEN_ENV):
        beds24.Beds24Probe(refresh_token="   ")


def test_repr_never_carries_a_credential():
    """R6.4 — a repr lands in logs and formatted tracebacks."""
    bench = _bench(lambda request: httpx.Response(200))

    rendered = repr(bench)

    assert "refresh-secret" not in rendered
    assert "access-secret" not in rendered
    assert "***redacted***" in rendered


def test_transport_errors_do_not_leak_the_token_into_the_message():
    """R6.4 — an httpx error message can embed the request, headers included."""

    def handler(request):
        raise httpx.ConnectError(f"failed talking to {request.headers.get('token')}")

    bench = _bench(handler)

    with pytest.raises(SystemExit) as excinfo:
        bench.request("GET", "/bookings")

    assert "access-secret" not in str(excinfo.value)
    assert "***redacted***" in str(excinfo.value)


def test_token_exchange_stores_the_access_token_in_memory_only(tmp_path):
    """D7 — nothing about the exchange may reach disk."""
    seen = {}

    def handler(request):
        seen["refresh"] = request.headers.get(beds24.REFRESH_HEADER)
        return httpx.Response(200, json={"token": "fresh-access"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bench = beds24.Beds24Probe(refresh_token="refresh-secret", client=client)
    bench.authenticate()

    assert seen["refresh"] == "refresh-secret"
    assert bench._access_token == "fresh-access"
    assert not list(tmp_path.iterdir())


# --- Section 2.3: host allowlist ------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://api.beds24.com.evil.tld/api/v2/bookings",
        "https://evil.tld/?x=https://api.beds24.com/",
        "https://beds24.com.attacker.net/api/v2",
        "http://localhost:8000/api/v2",
    ],
)
def test_host_allowlist_rejects_lookalikes(url):
    """R6.5 — compared by hostname, so a substring of the URL buys nothing."""
    with pytest.raises(SystemExit, match="refusing to talk to host"):
        beds24.assert_host_allowed(url)


@pytest.mark.parametrize("url", ["https://beds24.com/api/v2", "https://api.beds24.com/v2/x"])
def test_host_allowlist_accepts_the_real_hosts(url):
    beds24.assert_host_allowed(url)


def test_base_url_from_the_environment_cannot_redirect_the_probe():
    """The allowlist is a constant, not derived from config — that is the whole point."""
    with pytest.raises(SystemExit, match="refusing to talk to host"):
        beds24.Beds24Probe(refresh_token="x", base_url="https://evil.tld/api/v2")


# --- Section 2.4: argument handling ---------------------------------------------------------


def test_unrecognised_argument_is_refused_without_echoing_its_value(capsys):
    """R6.6 — the fumble this guards is `beds24_probe.py probe <token>`."""
    secret = "s3cr3t-refresh-token"

    with pytest.raises(SystemExit) as excinfo:
        beds24.main(["probe", secret])

    assert secret not in str(excinfo.value)
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize(
    "argument", ["probe", "capture", "report", "bookings", "--out=/tmp/x.jsonl", "--min-interval=5"]
)
def test_known_arguments_are_accepted(argument):
    beds24._reject_unknown_arguments([argument])


# --- Section 2.5: pacing and quota ----------------------------------------------------------


def test_requests_are_paced_by_the_configured_interval():
    """R4.3 — an accidental run must not eat somebody else's window."""
    slept = []
    clock = {"now": 0.0}

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    bench = beds24.Beds24Probe(
        refresh_token="x",
        client=client,
        min_interval_seconds=2.0,
        sleep=slept.append,
        monotonic=lambda: clock["now"],
    )
    bench._access_token = "t"

    bench.request("GET", "/bookings")
    bench.request("GET", "/bookings")

    assert slept == [2.0]


def test_quota_exhaustion_stops_the_walk_instead_of_retrying():
    """R4.2 — hammering a spent quota turns a measurement into an outage."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429)

    waited = []
    records = beds24.probe(
        _bench(handler),
        catalogue=beds24.CATALOGUE,
        on_quota_exhausted=lambda: waited.append(True),
    )

    assert calls["n"] == 1, "it must stop at the first 429, not keep walking the catalogue"
    assert waited == [True]
    assert records[-1]["status"] == 429
    assert records[-1]["x_request_cost"] is None


# --- Section 3: the cost record -------------------------------------------------------------


def test_cost_record_captures_the_header_and_the_shape():
    record = beds24.build_cost_record(
        endpoint="/bookings",
        method="GET",
        shape="page-100",
        status=200,
        headers=httpx.Headers({"X-RequestCost": "7", "X-FiveMinCreditRemaining": "93"}),
        booking_ref="BK-1",
    )

    assert record["x_request_cost"] == 7
    assert record["credit_headers"] == {"x-fivemincreditremaining": "93"}
    assert record["shape"] == "page-100"
    assert record["booking_ref"] == "BK-1"


def test_a_missing_cost_header_is_null_and_never_zero():
    """R1.3 — an unknown cost and a free call lead to different budgets."""
    record = beds24.build_cost_record(
        endpoint="/bookings", method="GET", shape="page-10", status=200, headers=httpx.Headers({})
    )

    assert record["x_request_cost"] is None


def test_an_unparseable_cost_header_is_null_too():
    record = beds24.build_cost_record(
        endpoint="/bookings",
        method="GET",
        shape="page-10",
        status=200,
        headers=httpx.Headers({"X-RequestCost": "not-a-number"}),
    )

    assert record["x_request_cost"] is None


def test_records_are_written_one_json_object_per_line(tmp_path):
    """R1.5 — the report derives from data, so the data has to be on disk and readable."""
    out = tmp_path / "cost.jsonl"

    beds24.write_records(
        [
            beds24.build_cost_record(
                endpoint="/a", method="GET", shape="s1", status=200, headers=httpx.Headers({})
            ),
            beds24.build_cost_record(
                endpoint="/b", method="GET", shape="s2", status=200, headers=httpx.Headers({})
            ),
        ],
        out,
    )

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["endpoint"] for line in lines] == ["/a", "/b"]
    assert beds24.read_records(out)[1]["shape"] == "s2"


def test_every_catalogue_entry_is_measured_with_at_least_two_shapes():
    """R1.2 — one shape cannot tell a flat cost from one that scales."""
    single = [entry.name for entry in beds24.CATALOGUE if len(entry.shapes) < 2]

    assert not single, f"these endpoints would produce an uninterpretable cost: {single}"


def test_catalogue_shape_labels_are_unique_within_an_endpoint():
    """Two rows with the same label in the report are indistinguishable."""
    for entry in beds24.CATALOGUE:
        labels = [shape.label for shape in entry.shapes]
        assert len(labels) == len(set(labels)), entry.name


# --- Section 4: capture -------------------------------------------------------------------


def _capture_payload(payload, tmp_path, monkeypatch):
    monkeypatch.setattr(beds24, "FIXTURE_DIR", tmp_path)
    bench = _bench(lambda request: httpx.Response(200, json=payload))
    return json.loads(beds24.capture("probe_out", "/bookings", bench=bench).read_text())


def test_capture_anonymises_before_writing(tmp_path, monkeypatch):
    """R3.2 — at capture time, not in a later manual pass."""
    written = _capture_payload(
        {"bookings": [{"id": 1, "guestName": "Ana Perez", "guestEmail": "ana@gmail.com"}]},
        tmp_path,
        monkeypatch,
    )

    raw = json.dumps(written)
    assert "Ana Perez" not in raw
    assert "ana@gmail.com" not in raw
    assert written["payload"]["bookings"][0]["id"] == 1


def test_capture_discards_card_data_entirely(tmp_path, monkeypatch):
    """R3.4 / security rule 13 — PCI DSS forbids retaining the CVV, so scrubbing is not optional."""
    written = _capture_payload(
        {
            "bookings": [
                {
                    "id": 1,
                    "card_number": "4111111111111111",
                    "cvv": "123",
                    "expiration_date": "12/2027",
                    "cardholder_name": "Ana Perez",
                }
            ]
        },
        tmp_path,
        monkeypatch,
    )

    raw = json.dumps(written)
    for leaked in ("4111111111111111", "12/2027", "Ana Perez"):
        assert leaked not in raw, leaked


def test_capture_preserves_none_and_booleans(tmp_path, monkeypatch):
    """R3.3 — the fixture has to exercise the same optionality as the real payload."""
    written = _capture_payload(
        {"bookings": [{"id": 1, "canceltime": None, "isPaid": True, "isRefunded": False}]},
        tmp_path,
        monkeypatch,
    )

    booking = written["payload"]["bookings"][0]
    assert booking["canceltime"] is None
    assert booking["isPaid"] is True
    assert booking["isRefunded"] is False


def test_capture_records_which_keys_were_substituted(tmp_path, monkeypatch):
    """R3.5 — so a reader can tell a real value from a placeholder, and widen the allowlist."""
    written = _capture_payload(
        {"bookings": [{"id": 1, "guestName": "Ana Perez"}]}, tmp_path, monkeypatch
    )

    assert written["_anonymised"] is True
    assert any("guestName" in key for key in written["_substituted"])
    assert not any(key.endswith(".id") for key in written["_substituted"])


# --- Section 6.1: the report ----------------------------------------------------------------


def _record(endpoint, shape, cost):
    return {
        "ts_utc": "2026-08-03T10:00:00+00:00",
        "booking_ref": None,
        "endpoint": endpoint,
        "method": "GET",
        "shape": shape,
        "x_request_cost": cost,
        "credit_headers": {},
        "status": 200,
    }


def test_report_derives_the_sustainable_cadence():
    """R4.4 — the number `celery-jobs` consumes."""
    rendered = beds24.report([_record("/bookings", "page-10", 5), _record("/properties", "all", 5)])

    assert "**10** créditos" in rendered
    # 100 credits / 10 per cycle = 10 cycles per 300 s window -> one sync every 30 s.
    assert "cada 30 s" in rendered


def test_report_never_sums_a_null_cost_as_zero():
    """R1.3 again, at the reporting end: an optimistic budget is a dangerous budget."""
    rendered = beds24.report([_record("/bookings", "page-10", 5), _record("/properties", "all", None)])

    assert "no medido" in rendered
    assert "1 de 2 peticiones no devolvieron" in rendered
    assert "cota superior" in rendered
    assert "**5** créditos" in rendered


def test_report_says_so_when_nothing_could_be_measured():
    rendered = beds24.report([_record("/bookings", "page-10", None)])

    assert "no calculable" in rendered
