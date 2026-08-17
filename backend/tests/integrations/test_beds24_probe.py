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


@pytest.mark.parametrize("url", ["https://beds24.com/api/v2", "https://beds24.com/api/v2/bookings"])
def test_host_allowlist_accepts_the_real_host(url):
    beds24.assert_host_allowed(url)


def test_the_guessed_api_subdomain_is_no_longer_allowed():
    """Step 0 confirmed the base is `beds24.com`; `api.beds24.com` was a guess and is gone.

    Keeping a second spelling "just in case" would defeat the point of the allowlist — the
    narrower it is, the more it is worth.
    """
    with pytest.raises(SystemExit, match="refusing to talk to host"):
        beds24.assert_host_allowed("https://api.beds24.com/v2/bookings")


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
    """Header names are the MEASURED ones. This test used to assert the guessed spellings and
    passed, which is precisely how the wrong constant survived into a committed script."""
    record = beds24.build_cost_record(
        endpoint="/bookings",
        method="GET",
        shape="page-100",
        status=200,
        headers=httpx.Headers({"X-Request-Cost": "7", "X-Five-Min-Limit-Remaining": "93"}),
        booking_ref="BK-1",
    )

    assert record["x_request_cost"] == 7
    assert record["credit_headers"] == {"x-five-min-limit-remaining": "93"}
    assert record["shape"] == "page-100"
    assert record["booking_ref"] == "BK-1"


def test_a_missing_cost_header_is_null_and_never_zero():
    """R1.3 — an unknown cost and a free call lead to different budgets."""
    record = beds24.build_cost_record(
        endpoint="/bookings", method="GET", shape="page-10", status=200, headers=httpx.Headers({})
    )

    assert record["x_request_cost"] is None


def test_the_real_header_name_is_matched():
    """MEASURED: the header is `X-Request-Cost`, with hyphens.

    The guessed `x-requestcost` matched nothing, so every measurement would have recorded a
    null cost and the report would have said "no calculable" with no visible error.
    """
    record = beds24.build_cost_record(
        endpoint="/properties",
        method="GET",
        shape="all",
        status=200,
        headers=httpx.Headers({"X-Request-Cost": "1"}),
    )

    assert record["x_request_cost"] == 1


def test_a_fractional_cost_is_kept_and_not_dropped():
    """`X-Five-Min-Limit-Remaining` came back as 96.8, so the provider bills fractionally.

    `int("0.2")` raises, and the previous parser turned that into `None` — a fractional cost
    recorded as "not measured" makes the derived cadence optimistic.
    """
    record = beds24.build_cost_record(
        endpoint="/bookings",
        method="GET",
        shape="page-10",
        status=200,
        headers=httpx.Headers({"X-Request-Cost": "0.2"}),
    )

    assert record["x_request_cost"] == 0.2


def test_the_measured_credit_headers_are_captured():
    record = beds24.build_cost_record(
        endpoint="/properties",
        method="GET",
        shape="all",
        status=200,
        headers=httpx.Headers(
            {
                "X-Request-Cost": "1",
                "X-Five-Min-Limit-Remaining": "96.8",
                "X-Five-Min-Limit-Resets-In": "215",
            }
        ),
    )

    assert record["credit_headers"] == {
        "x-five-min-limit-remaining": "96.8",
        "x-five-min-limit-resets-in": "215",
    }


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
    # "del ciclo" since the report grew a second table: the count names which one it refers to.
    assert "1 de 2 peticiones del ciclo no devolvieron" in rendered
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

    records = beds24.provoke(_bench(handler), room_id="713992")

    assert [r["shape"] for r in records] == ["provoke-create", "provoke-modify", "provoke-cancel"]
    assert {r["booking_ref"] for r in records} == {"777"}


def test_provoke_refuses_the_follow_ups_when_the_create_returns_no_id():
    """Writing modify/cancel without a certain id could act on somebody else's booking.

    It raises rather than returning a partial record set: a confirmed booking may exist and
    the operator has to be told, not left to notice a short list.
    """
    with pytest.raises(SystemExit, match="WILL NOT BE CANCELLED"):
        beds24.provoke(
            _bench(lambda request: httpx.Response(200, json=[{}])), room_id="713992"
        )


# --- Round-2 panel fixes: the write path ------------------------------------------------------


def test_provoke_refuses_to_run_without_explicit_confirmation():
    """It is the only subcommand that writes, against an account with no staging twin."""
    with pytest.raises(SystemExit, match="--confirm-writes"):
        beds24.main(["provoke", "--room=713992"])


def _properties(*props):
    """A `/properties` body shaped like the real one, measured 2026-08-04."""
    return {"success": True, "type": "property", "count": len(props), "data": list(props)}


def _measurement_account():
    return _properties({"id": 345754, "name": "TEST-MEDICION", "roomTypes": [{"id": 713992}]})


def test_write_proceeds_on_the_measurement_account():
    bench = _bench(lambda request: httpx.Response(200, json=_measurement_account()))

    beds24.assert_account_is_a_measurement_account(bench, room_id="713992")


def test_write_is_refused_on_an_account_holding_more_than_one_property():
    """The measurement account holds one property; the live one holds REDES11 and PAJARITOS8.

    This replaced a channel-detection check that could not work: measured against the real API,
    `/properties` carries no channel field at all, so the original guard would have refused
    every run. Counting properties tests the same risk more directly — the danger is pointing
    the script at the wrong account.
    """
    bench = _bench(
        lambda request: httpx.Response(
            200,
            json=_properties(
                {"id": 1, "name": "REDES11", "roomTypes": [{"id": 713992}]},
                {"id": 2, "name": "PAJARITOS8", "roomTypes": [{"id": 999}]},
            ),
        )
    )

    with pytest.raises(SystemExit, match="holds 2 properties"):
        beds24.assert_account_is_a_measurement_account(bench, room_id="713992")


def test_write_is_refused_when_the_room_belongs_to_another_account():
    """A stale room id from a different account must not slip through."""
    bench = _bench(lambda request: httpx.Response(200, json=_measurement_account()))

    with pytest.raises(SystemExit, match="does not belong"):
        beds24.assert_account_is_a_measurement_account(bench, room_id="000000")


def test_write_is_refused_when_the_precondition_cannot_be_verified():
    """Unverifiable is not the same as fine."""
    bench = _bench(lambda request: httpx.Response(500))

    with pytest.raises(SystemExit, match="could not read /properties"):
        beds24.assert_account_is_a_measurement_account(bench, room_id="713992")


def test_write_is_refused_when_the_property_list_is_unusable():
    bench = _bench(lambda request: httpx.Response(200, json={"success": True, "data": []}))

    with pytest.raises(SystemExit, match="no usable property list"):
        beds24.assert_account_is_a_measurement_account(bench, room_id="713992")


def test_channels_still_refuse_if_the_provider_ever_reports_them():
    """Secondary assertion: absence is measured, but presence must still stop the write."""
    bench = _bench(
        lambda request: httpx.Response(
            200,
            json=_properties(
                {"id": 345754, "roomTypes": [{"id": 713992}], "channels": ["Airbnb"]}
            ),
        )
    )

    with pytest.raises(SystemExit, match="reports OTA channels connected"):
        beds24.assert_account_is_a_measurement_account(bench, room_id="713992")


def test_the_refusal_message_does_not_render_the_provider_structure():
    """The channel structure may nest guest or contact data; count it, do not print it."""
    bench = _bench(
        lambda request: httpx.Response(
            200,
            json=_properties(
                {
                    "id": 345754,
                    "roomTypes": [{"id": 713992}],
                    "channels": [{"name": "Airbnb", "contact": "ana@gmail.com"}],
                }
            ),
        )
    )

    with pytest.raises(SystemExit) as excinfo:
        beds24.assert_account_is_a_measurement_account(bench, room_id="713992")

    assert "ana@gmail.com" not in str(excinfo.value)


def test_a_failed_create_never_leads_to_a_modify_or_cancel():
    """Acting on an id from an error envelope means cancelling somebody else's booking."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json=[{"id": 999, "error": "bad request"}])

    with pytest.raises(SystemExit, match="create failed"):
        beds24.provoke(_bench(handler), room_id="713992")

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
            room_id="713992",
        )


# --- webhook: measured to be writable, contradicting ADR 0006 --------------------------------


def test_set_webhook_sends_the_measured_envelope():
    """MEASURED: `POST /properties` with a `webhooks` object returns 201 and persists."""
    sent = {}

    def handler(request):
        sent["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json=[{"success": True, "modified": {"webhooks": {"url": "https://x/y"}}}],
            headers={"X-Request-Cost": "1"},
        )

    record = beds24.set_webhook(
        _bench(handler), property_id=345754, url="https://x/y", secret="X-Probe: 1"
    )

    assert sent["body"] == [
        {
            "id": 345754,
            "webhooks": {
                "version": "one",
                "url": "https://x/y",
                "additionalData": "none",
                "customHeader": "X-Probe: 1",
            },
        }
    ]
    assert record["shape"] == "webhook-set"
    assert record["x_request_cost"] == 1


def test_clearing_the_webhook_is_recorded_as_such():
    record = beds24.set_webhook(
        _bench(lambda request: httpx.Response(201, json=[{"success": True}])),
        property_id=345754,
        url="",
        secret="",
    )

    assert record["shape"] == "webhook-clear"


def test_webhook_needs_explicit_write_confirmation():
    with pytest.raises(SystemExit, match="--confirm-writes"):
        beds24.main(["webhook", "--url=https://x/y"])


def test_the_guard_returns_the_single_property_without_a_room_id():
    """`webhook` is per property, so the guard must work without a room to check."""
    bench = _bench(lambda request: httpx.Response(200, json=_measurement_account()))

    prop = beds24.assert_account_is_a_measurement_account(bench)

    assert prop["id"] == 345754


# --- catalogue validated against the real API -------------------------------------------------


def test_windowed_shapes_send_absolute_dates_not_iso_durations():
    """MEASURED: the API answers 400 to `P0D` — *"Expected format: YYYY-MM-DD"*.

    The first version sent ISO-8601 durations and every windowed shape returned 400, so two of
    the four `/bookings` shapes measured nothing at all.
    """
    from datetime import date

    shape = next(
        s
        for entry in beds24.CATALOGUE
        if entry.name == "bookings"
        for s in entry.shapes
        if s.label == "window-90d"
    )

    params = shape.resolved_params(today=date(2026, 8, 4))

    assert params["arrivalFrom"] == "2026-08-04"
    assert params["arrivalTo"] == "2026-11-02"


def test_no_catalogue_shape_sends_an_iso_duration():
    """A guard against reintroducing the format the provider rejects."""
    for entry in beds24.CATALOGUE:
        for shape in entry.shapes:
            for name, value in shape.resolved_params().items():
                assert not (
                    isinstance(value, str) and value.startswith("P")
                ), f"{entry.name}/{shape.label}: {name}={value!r} looks like an ISO duration"


def test_a_rotating_refresh_token_is_reported_loudly(capsys):
    """Not tested against the real API on purpose: finding out destructively would invalidate
    the operator's stored token. The script watches for it instead."""

    def handler(request):
        return httpx.Response(200, json={"token": "acc", "refreshToken": "A-DIFFERENT-ONE"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bench = beds24.Beds24Probe(refresh_token="the-original", client=client)

    bench.authenticate()

    err = capsys.readouterr().err
    assert "REFRESH TOKEN ROTATED" in err
    assert "A-DIFFERENT-ONE" not in err, "the new token must not be echoed"


def test_an_unchanged_refresh_token_is_not_reported():
    def handler(request):
        return httpx.Response(200, json={"token": "acc", "refreshToken": "the-original"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bench = beds24.Beds24Probe(refresh_token="the-original", client=client)

    bench.authenticate()

    assert bench._access_token == "acc"


def test_the_webhook_secret_is_not_accepted_as_an_argument():
    """Rule 12(a) calls the static header a credential, so it comes from the environment.

    Taking it from `--secret=` contradicted this script's own refusal message about credentials
    never travelling on the command line, where they stay in shell history and `ps`.
    """
    with pytest.raises(SystemExit) as excinfo:
        beds24._reject_unknown_arguments(["--secret=X-AutoHost-Probe: 1"])

    assert "X-AutoHost-Probe" not in str(excinfo.value)
    assert beds24.WEBHOOK_SECRET_ENV in str(excinfo.value)


@pytest.mark.parametrize("argument", ["--room=713 992", "--out=/tmp/a b.jsonl", "--min-interval=x"])
def test_the_other_options_stay_strict(argument):
    """Only the secret needs spaces; elsewhere a space is a mistake."""
    with pytest.raises(SystemExit):
        beds24._reject_unknown_arguments([argument])


@pytest.mark.parametrize(
    "envelope,expected",
    [
        ([{"success": False, "errors": [{"field": "arrival", "message": "invalid"}]}],
         "arrival: invalid"),
        # MEASURED: a rejected enum comes back under `warnings`, not `errors`, while still
        # reporting success=false and writing nothing.
        ([{"success": False, "warnings": [{"field": "webhooks_additionalData",
                                            "message": "Invalid"}]}],
         "webhooks_additionalData: Invalid"),
        ({"success": False, "code": 400, "error": "Request body must be an array"},
         "Request body must be an array"),
    ],
)
def test_every_measured_failure_envelope_is_recognised(envelope, expected):
    """Beds24 answers 201 even when it refuses the write; the verdict is in the body."""
    assert beds24._envelope_failure(httpx.Response(201, json=envelope)) == expected


def test_a_successful_envelope_is_not_reported_as_a_failure():
    envelope = [{"success": True, "new": {"id": 90923575}}]

    assert beds24._envelope_failure(httpx.Response(201, json=envelope)) is None


def test_the_create_id_is_read_from_the_measured_success_shape():
    """MEASURED: the new booking id lives under `new.id`."""
    response = httpx.Response(201, json=[{"success": True, "new": {"id": 90923575}}])

    assert beds24._extract_booking_ref(response) == "90923575"


def test_the_webhook_never_asks_for_card_data():
    """MEASURED: `additionalData` chooses between None / CVC / Token / CVC and Token.

    It decides whether Beds24 puts the card security code into the webhook body. Rule 13 of
    `steering/security.md` is categorical — PCI DSS forbids retaining the CVV — so the value is
    a constant here, not a parameter a caller could widen.
    """
    sent = {}

    def handler(request):
        sent["body"] = json.loads(request.content)
        return httpx.Response(201, json=[{"success": True}])

    beds24.set_webhook(_bench(handler), property_id=345754, url="https://x/y", secret="")

    assert sent["body"][0]["webhooks"]["additionalData"] == "none"


def test_set_webhook_takes_no_additional_data_argument():
    """A keyword nobody can pass is a keyword nobody can get wrong."""
    import inspect

    assert "additionalData" not in inspect.signature(beds24.set_webhook).parameters
    assert "additional_data" not in inspect.signature(beds24.set_webhook).parameters


def test_capture_records_the_cost_of_its_own_request(tmp_path, monkeypatch):
    """A measurement the tool cannot emit is a measurement somebody will transcribe by hand.

    `capture` used to make the only call to `/bookings/messages` without recording its cost, so
    the row published for that endpoint had no artifact behind it — the failure D5 rules out.
    """
    monkeypatch.setattr(beds24, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(beds24, "_CAPTURE_COSTS", [])
    bench = _bench(
        lambda request: httpx.Response(200, json={"data": []}, headers={"X-Request-Cost": "1"})
    )

    beds24.capture("messages", "/bookings/messages", bench=bench)

    [record] = beds24._CAPTURE_COSTS
    assert record["endpoint"] == "/bookings/messages"
    assert record["shape"] == "capture-messages"
    assert record["x_request_cost"] == 1


# --- `pms-beds24-adapter` section 1: the modification window --------------------------------
#
# Everything below belongs to the change that consumes this bench, not to the spike that built
# it. Its R2 needs `list_reservations(since)` to see modifications and cancellations, which
# Channex cannot do, and the bench is where that gets measured before any mapping is written.


def test_a_date_shape_and_a_datetime_shape_render_differently():
    """R2 — the format `modifiedFrom` accepts is unmeasured, so both spellings get a request."""
    base = beds24.date(2026, 8, 6)

    as_date = beds24.RequestShape("d", date_params={"modifiedFrom": -30}).resolved_params(base)
    as_datetime = beds24.RequestShape(
        "dt", datetime_params={"modifiedFrom": -30}
    ).resolved_params(base)

    assert as_date["modifiedFrom"] == "2026-07-07"
    assert as_datetime["modifiedFrom"] == "2026-07-07T00:00:00Z"


def test_the_pacing_clock_still_works():
    """Regression: `from datetime import time` would shadow the `time` module this uses.

    The module does `import time` for `time.sleep`/`time.monotonic`, so pulling `datetime.time`
    into the namespace to build a timestamp broke pacing — silently, because nothing else in the
    file touches it. Caught by the type checker, pinned here.
    """
    slept = []
    bench = beds24.Beds24Probe(
        refresh_token="t",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        min_interval_seconds=5.0,
        sleep=slept.append,
        monotonic=lambda: 0.0,
    )
    bench._access_token = "a"

    bench.request("GET", "/bookings")
    bench.request("GET", "/bookings")

    assert slept == [5.0]


def test_the_catalogue_measures_the_modification_window_in_both_spellings():
    """R2 — this is the shape the production adapter will actually issue."""
    bookings = next(e for e in beds24.CATALOGUE if e.path == "/bookings")

    modified = [s for s in bookings.shapes if "modifiedFrom" in s.resolved_params()]

    assert len(modified) == 2
    rendered = {s.resolved_params()["modifiedFrom"] for s in modified}
    assert any("T" in value for value in rendered), "one shape must send an instant"
    assert any("T" not in value for value in rendered), "one shape must send a plain date"


def test_the_report_excludes_writes_and_captures_from_the_cycle_total():
    """The defect that bites the moment R6 consolidates one JSONL.

    `main` appends `capture` and `provoke` records to the same file the report reads, so summing
    every record published the cost of creating a booking as part of a read-only sync cycle —
    and derived a slower, plausible, wrong cadence from it.
    """
    records = [
        {"endpoint": "/bookings", "shape": "page-10", "x_request_cost": 1, "status": 200},
        {"endpoint": "/properties", "shape": "all", "x_request_cost": 1, "status": 200},
        {"endpoint": "/bookings", "shape": "provoke-create", "x_request_cost": 5, "status": 201},
        {"endpoint": "/bookings/messages", "shape": "capture-messages",
         "x_request_cost": 3, "status": 200},
    ]

    rendered = beds24.report(records)

    assert "**2** créditos" in rendered
    assert "Fuera del ciclo de sync" in rendered
    # The excluded rows are still published — they are the evidence for the write endpoints.
    assert "provoke-create" in rendered
    assert "capture-messages" in rendered


def test_an_observer_that_fails_does_not_leave_a_booking_uncancelled():
    """The cycle's last action is a CANCEL, so nothing may abort the loop early."""
    actions = []

    def handler(request):
        actions.append(json.loads(request.content)[0])
        return httpx.Response(201, json=[{"success": True, "new": {"id": 90923575}}])

    def observer(action, booking_ref):
        raise RuntimeError("boom")

    beds24.provoke(_bench(handler), room_id="713992", observer=observer)

    assert [a.get("status") for a in actions][-1] == "cancelled"


def test_the_observer_contributes_its_records_to_the_log():
    def handler(request):
        return httpx.Response(201, json=[{"success": True, "new": {"id": 90923575}}])

    records = beds24.provoke(
        _bench(handler),
        room_id="713992",
        observer=lambda action, ref: [{"shape": f"observed-{action}"}],
    )

    assert [r["shape"] for r in records if "observed" in r.get("shape", "")] == [
        "observed-create",
        "observed-modify",
        "observed-cancel",
    ]


def _window_handler(*, reject_date_form=False, listing_ids=(90923575,), capture_fails=False):
    def handler(request):
        if request.method == "POST":
            return httpx.Response(201, json=[{"success": True, "new": {"id": 90923575}}])
        sent = request.url.params.get("modifiedFrom")
        if sent is None:
            # A fixture capture: narrowed by `id`, no window filter.
            if capture_fails:
                return httpx.Response(500)
            return httpx.Response(200, json={"success": True, "data": []})
        if reject_date_form and "T" not in sent:
            return httpx.Response(400, json={"success": False, "error": "invalid format"})
        return httpx.Response(
            200,
            json={"success": True, "data": [{"id": i} for i in listing_ids]},
            headers={"X-Request-Cost": "1"},
        )

    return handler


def test_the_window_check_records_whether_the_booking_is_visible(monkeypatch, tmp_path):
    """R2.2 — the evidence that Beds24 does not inherit the Channex limitation."""
    monkeypatch.setattr(beds24, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(beds24, "_CAPTURE_COSTS", [])

    records = beds24.verify_window(_bench(_window_handler()), room_id="713992")

    checks = [r for r in records if "booking_visible" in r]
    assert [r["shape"] for r in checks] == [
        "window-after-create-date",
        "window-after-modify-date",
        "window-after-cancel-date",
    ]
    assert all(r["booking_visible"] is True for r in checks)


def test_the_window_check_falls_back_to_the_datetime_spelling(monkeypatch, tmp_path):
    """Retrying is free — MEASURED: a rejected request consumes no credit."""
    monkeypatch.setattr(beds24, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(beds24, "_CAPTURE_COSTS", [])

    records = beds24.verify_window(
        _bench(_window_handler(reject_date_form=True)), room_id="713992"
    )

    checks = [r for r in records if "booking_visible" in r]
    # The first action pays for the rejected spelling; afterwards the accepted one is reused.
    assert checks[0]["shape"] == "window-after-create-date"
    assert checks[0]["status"] == 400
    assert checks[1]["shape"] == "window-after-create-datetime"
    assert checks[1]["modified_from_format"] == "datetime"
    assert [r["shape"] for r in checks[2:]] == [
        "window-after-modify-datetime",
        "window-after-cancel-datetime",
    ]


def test_an_invisible_booking_is_recorded_rather_than_raised(monkeypatch, tmp_path):
    """Absence after `cancel` is a FINDING — it means the adapter needs a status filter.

    A script that raised here would destroy the measurement it exists to collect.
    """
    monkeypatch.setattr(beds24, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(beds24, "_CAPTURE_COSTS", [])

    records = beds24.verify_window(
        _bench(_window_handler(listing_ids=())), room_id="713992"
    )

    assert all(r["booking_visible"] is False for r in records if "booking_visible" in r)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"data": "not a list"}),
    ],
)
def test_an_unanswerable_visibility_question_is_none_not_false(response):
    """"The provider said no" and "we could not tell" lead to opposite conclusions."""
    assert beds24._contains_booking(response, "90923575") is None


def test_the_window_run_captures_the_modified_and_cancelled_fixtures(monkeypatch, tmp_path):
    """The mapping has no other way to see a `cancelTime` or a non-confirmed status."""
    monkeypatch.setattr(beds24, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(beds24, "_CAPTURE_COSTS", [])

    beds24.verify_window(_bench(_window_handler()), room_id="713992")

    assert (tmp_path / "bookings_modified.json").exists()
    assert (tmp_path / "bookings_cancelled.json").exists()
    assert not (tmp_path / "bookings_created.json").exists()


def test_a_failed_fixture_capture_does_not_cost_the_measurement(monkeypatch, tmp_path):
    """The visibility rows are what the run paid credits for; a fixture can be retaken.

    `provoke` only logs what the observer RETURNS, so an exception thrown after the rows were
    collected discarded a measurement that had already been made.
    """
    monkeypatch.setattr(beds24, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(beds24, "_CAPTURE_COSTS", [])

    records = beds24.verify_window(
        _bench(_window_handler(capture_fails=True)), room_id="713992"
    )

    checks = [r for r in records if "booking_visible" in r]
    assert [r["shape"] for r in checks] == [
        "window-after-create-date",
        "window-after-modify-date",
        "window-after-cancel-date",
    ]


def test_capture_narrows_the_request_when_given_params(monkeypatch, tmp_path):
    monkeypatch.setattr(beds24, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(beds24, "_CAPTURE_COSTS", [])
    seen = {}

    def handler(request):
        seen["id"] = request.url.params.get("id")
        return httpx.Response(200, json={"data": []})

    beds24.capture("one", "/bookings", bench=_bench(handler), params={"id": "90923575"})

    assert seen["id"] == "90923575"


# --- `messages`: can a message be written without an OTA channel? ---------------------------


def _messages_handler(*, on_message):
    """Route `/bookings/messages` to `on_message` and everything else to the booking cycle."""

    def handler(request):
        if request.url.path.endswith("/bookings/messages"):
            return on_message(request)
        return httpx.Response(200, json=[{"id": 777}])

    return handler


def test_messages_refuses_to_run_without_explicit_confirmation():
    """It writes: a booking cycle plus messages onto it."""
    with pytest.raises(SystemExit, match="--confirm-writes"):
        beds24.main(["messages", "--room=713992"])


def test_messages_records_an_accepted_guest_write():
    """The finding that would unblock the inbound half of `beds24-messaging-adapter`."""
    records = beds24.probe_messages(
        _bench(_messages_handler(on_message=lambda r: httpx.Response(200, json=[{"id": 1}]))),
        room_id="713992",
    )

    guest = [r for r in records if r.get("message_source") == "guest" and "write_accepted" in r]
    assert guest and guest[0]["write_accepted"] is True
    assert guest[0]["write_rejected"] is None


def test_messages_treats_a_201_with_success_false_as_a_refusal():
    """The provider answers 2xx while refusing; the verdict is in the body, not the status.

    This is the trap `_envelope_failure` exists for, and a probe that read the status alone
    would report "messaging works without a channel" — the exact wrong answer, on the exact
    question this subcommand exists to settle.
    """
    refusal = httpx.Response(
        201, json=[{"success": False, "errors": [{"field": "source", "message": "invalid"}]}]
    )
    records = beds24.probe_messages(
        _bench(_messages_handler(on_message=lambda r: refusal)), room_id="713992"
    )

    writes = [r for r in records if "write_accepted" in r]
    assert writes and all(r["write_accepted"] is False for r in writes)
    assert "source: invalid" in writes[0]["write_rejected"]


def test_messages_stops_trying_shapes_once_one_is_accepted():
    """A rejected request costs no credit, but an accepted one does — so it does not repeat."""
    seen = []

    def on_message(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        seen.append(request.content)
        if len(seen) == 1:  # the flat shape is refused, the nested one is not
            return httpx.Response(201, json=[{"success": False, "error": "no such field"}])
        return httpx.Response(200, json=[{"id": 1}])

    records = beds24.probe_messages(
        _bench(_messages_handler(on_message=on_message)), room_id="713992"
    )

    shapes = [r["shape"] for r in records if "write_accepted" in r]
    # guest tries flat (refused) then nested (accepted); host goes straight to nested.
    assert shapes == ["write-guest-flat", "write-guest-nested", "write-host-nested"]


def test_message_count_says_unknown_rather_than_zero_when_it_cannot_ask():
    """"Nothing came back" and "we could not ask" are different findings."""
    assert beds24._message_count(httpx.Response(500, text="nope")) is None
    assert beds24._message_count(httpx.Response(200, text="not json")) is None
    assert beds24._message_count(httpx.Response(200, json={"data": [{"id": 1}]})) == 1
