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
    """R6.5 — compared by hostname, so a substring of the URL buys nothing.

    `refusing` rather than `refusing to talk to host`: the plain-HTTP entry is now caught by
    the scheme check first, which is a stricter refusal for a better reason. What this test
    pins is that none of these URLs is reachable, not which guard stops them.
    """
    with pytest.raises(SystemExit, match="refusing"):
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


# --- Panel fixes (sections 2-6 review) -------------------------------------------------------


@pytest.mark.parametrize("url", ["http://beds24.com/api/v2", "http://api.beds24.com/v2",
                                 "ftp://beds24.com/x"])
def test_non_https_schemes_are_refused(url):
    """The refresh token is an ACCOUNT credential; cleartext is one dropped `s` away."""
    with pytest.raises(SystemExit, match="refusing scheme"):
        beds24.assert_host_allowed(url)


def test_token_exchange_errors_are_redacted_even_in_their_escaped_form():
    """h11 embeds an illegal header value in its error, in repr form."""

    def handler(request):
        raise httpx.LocalProtocolError("Illegal header value b'refresh\\nsecret'")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bench = beds24.Beds24Probe(refresh_token="refresh\nsecret", client=client)

    with pytest.raises(SystemExit) as excinfo:
        bench.authenticate()

    assert "refresh\\nsecret" not in str(excinfo.value)
    assert "***redacted***" in str(excinfo.value)


def test_substituted_keys_never_republish_a_scrubbed_key(tmp_path, monkeypatch):
    """The fixture header must not carry the PII the payload block had scrubbed out."""
    written = _capture_payload(
        {"guests_by_mail": {"john.smith@gmail.com": {"adults": 2}}}, tmp_path, monkeypatch
    )

    rendered = json.dumps(written)
    assert "john.smith@gmail.com" not in rendered
    assert any("scrubbed-key" in key for key in written["_substituted"])


def test_two_colliding_scrubbed_keys_do_not_collapse_into_one(tmp_path, monkeypatch):
    """Losing an entry is safe for privacy and useless for a fixture."""
    written = _capture_payload(
        {"bookings": {"ana@x.com": {"adults": 1}, "bob@x.com": {"adults": 2}}},
        tmp_path,
        monkeypatch,
    )

    assert len(written["payload"]["bookings"]) == 2


def test_provoke_records_the_booking_ref_so_the_latency_join_works():
    """R2.2's fallback is dead unless something on our side causes the event AND knows its id."""
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=[{"id": 777}])
        return httpx.Response(200, json=[{"id": 777}])

    records = beds24.provoke(_bench(handler), property_id="R1")

    assert [r["shape"] for r in records] == ["provoke-create", "provoke-modify", "provoke-cancel"]
    assert {r["booking_ref"] for r in records} == {"777"}


def test_provoke_refuses_the_follow_ups_when_the_create_returns_no_id():
    """Writing modify/cancel without a certain id could act on somebody else's booking.

    It raises rather than returning a partial record set: a confirmed booking may exist and
    the operator has to be told, not left to notice a short list.
    """
    with pytest.raises(SystemExit, match="WILL NOT BE CANCELLED"):
        beds24.provoke(
            _bench(lambda request: httpx.Response(200, json=[{}])), property_id="R1"
        )


# --- Round-2 panel fixes: the write path ------------------------------------------------------


def test_provoke_refuses_to_run_without_explicit_confirmation():
    """It is the only subcommand that writes, against an account with no staging twin."""
    with pytest.raises(SystemExit, match="--confirm-writes"):
        beds24.main(["provoke", "--property=R1"])


def test_write_is_refused_when_the_account_has_ota_channels_connected():
    """R6.1 as an executable pre-flight: Beds24 has no staging to fall back on."""
    bench = _bench(
        lambda request: httpx.Response(
            200, json=[{"id": 1, "channels": ["Airbnb", "BookingCom"]}]
        )
    )

    with pytest.raises(SystemExit, match="REFUSING TO WRITE"):
        beds24.assert_account_has_no_ota_channels(bench)


def test_write_proceeds_on_an_account_with_a_recognised_empty_channel_list():
    bench = _bench(lambda request: httpx.Response(200, json=[{"id": 1, "channels": []}]))

    beds24.assert_account_has_no_ota_channels(bench)


@pytest.mark.parametrize(
    "body",
    [
        {"success": True, "data": [{"id": 1, "name": "REDES11"}]},   # the slim default shape
        [{"id": 1, "propertyName": "REDES11"}],
        {"data": []},
    ],
)
def test_write_is_refused_when_no_channel_field_is_recognised(body):
    """Fails CLOSED: an unrecognised shape is not evidence of a clean account.

    The shape of /properties is an unverified ASSUMPTION, so the *likely* real response is one
    with no channel field at all. Reading that as "no channels connected" would let the guard
    wave through a write to a live listing — the exact thing it exists to stop.
    """
    bench = _bench(lambda request: httpx.Response(200, json=body))

    with pytest.raises(SystemExit, match="Could not find a channel field"):
        beds24.assert_account_has_no_ota_channels(bench)


@pytest.mark.parametrize(
    "body",
    [
        [{"channels": ["Airbnb"]}],
        [{"connected_channels": ["Airbnb", "BookingCom"]}],
        [{"channels": {"Airbnb": True}}],
        [{"property": {"id": 1, "ota": ["Airbnb"]}}],
    ],
)
def test_channels_are_detected_across_plausible_spellings(body):
    bench = _bench(lambda request: httpx.Response(200, json=body))

    with pytest.raises(SystemExit, match="REFUSING TO WRITE"):
        beds24.assert_account_has_no_ota_channels(bench)


def test_the_refusal_message_does_not_render_the_provider_structure():
    """The unverified shape may nest property names or contact data; count them, do not print."""
    bench = _bench(
        lambda request: httpx.Response(
            200, json=[{"channels": [{"name": "Airbnb", "contact": "ana@gmail.com"}]}]
        )
    )

    with pytest.raises(SystemExit) as excinfo:
        beds24.assert_account_has_no_ota_channels(bench)

    assert "ana@gmail.com" not in str(excinfo.value)


def test_a_list_shaped_new_envelope_does_not_bypass_the_orphan_warning():
    """An AttributeError here would replace the warning with a stack trace."""
    response = httpx.Response(200, json=[{"success": True, "new": [{"id": 555}]}])

    assert beds24._extract_booking_ref(response) is None


def test_write_is_refused_when_the_precondition_cannot_be_verified():
    """Unverifiable is not the same as fine."""
    bench = _bench(lambda request: httpx.Response(500))

    with pytest.raises(SystemExit, match="could not read /properties"):
        beds24.assert_account_has_no_ota_channels(bench)


def test_a_failed_create_never_leads_to_a_modify_or_cancel():
    """Acting on an id from an error envelope means cancelling somebody else's booking."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json=[{"id": 999, "error": "bad request"}])

    with pytest.raises(SystemExit, match="create failed"):
        beds24.provoke(_bench(handler), property_id="R1")

    assert len(calls) == 1, "it must not issue the follow-up writes"


def test_an_error_envelope_carrying_an_id_is_not_treated_as_a_created_booking():
    response = httpx.Response(200, json=[{"id": 999, "success": False}])

    assert beds24._extract_booking_ref(response) is None


def test_an_ambiguous_multi_element_response_is_not_treated_as_a_created_booking():
    response = httpx.Response(200, json=[{"id": 1}, {"id": 2}])

    assert beds24._extract_booking_ref(response) is None


def test_an_unparseable_create_response_warns_about_the_orphan_booking():
    """A confirmed booking may exist and will not be cancelled — say so loudly."""
    with pytest.raises(SystemExit, match="WILL NOT BE CANCELLED"):
        beds24.provoke(
            _bench(lambda request: httpx.Response(200, json={"unexpected": "shape"})),
            property_id="R1",
        )
