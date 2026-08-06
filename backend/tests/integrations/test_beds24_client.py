"""The Beds24 transport (`app/integrations/infrastructure/beds24/client.py`), R1 and R3.

Offline by construction: the HTTP boundary is an `httpx.MockTransport`. R2.6 forbids a test
that reaches the network, and the reasoning `pms-beds24-spike` design D9 fixed applies here
too — a test that only runs when somebody holds a paid account reports green in CI while never
executing.
"""

import traceback

import httpx
import pytest

from app.integrations.domain.errors import PmsUnavailableError
from app.integrations.infrastructure.beds24.client import (
    ACCESS_HEADER,
    BEDS24_BASE_URL,
    REFRESH_HEADER,
    Beds24Client,
    parse_cost,
)

REFRESH = "refresh-secret"
ACCESS = "access-secret"


def _client(handler, **kwargs):
    options = {"max_pages": 5, "page_limit": 100} | kwargs
    return Beds24Client(
        refresh_token=REFRESH, transport=httpx.MockTransport(handler), **options
    )


def _token_response(refresh_token=REFRESH):
    return httpx.Response(
        200, json={"token": ACCESS, "expiresIn": 86400, "refreshToken": refresh_token}
    )


def _page(rows, *, more=False, cost="1"):
    return httpx.Response(
        200,
        json={
            "success": True,
            "type": "booking",
            "count": len(rows),
            "pages": {"nextPageExists": more, "nextPageLink": "https://evil.tld/next"},
            "data": rows,
        },
        headers={"X-Request-Cost": cost, "X-Five-Min-Limit-Remaining": "96.8"},
    )


def _routing(**by_path):
    """A handler that dispatches on path, answering the token exchange by default."""

    def handler(request):
        if request.url.path.endswith("/authentication/token"):
            return by_path.get("token", _token_response())
        return by_path.get("bookings", _page([]))

    return handler


# --- R1: the credential ----------------------------------------------------------------------


def test_an_empty_credential_is_refused_before_any_request():
    """A configuration mistake made before a request exists, so not `PmsUnavailableError`."""
    with pytest.raises(ValueError, match="refresh token is empty"):
        Beds24Client(refresh_token="   ", max_pages=5, page_limit=100)


def test_repr_never_carries_a_credential():
    """R1.4 — a repr of a credential-holding object is one `logger.debug` away from disk."""
    rendered = repr(_client(_routing()))

    assert REFRESH not in rendered
    assert "***redacted***" in rendered


@pytest.mark.asyncio
async def test_the_access_token_is_exchanged_once_and_reused():
    """R1.2 and R1.6 — one exchange per adapter, which the grouped sync makes one per run."""
    exchanges = []

    def handler(request):
        if request.url.path.endswith("/authentication/token"):
            exchanges.append(request.headers.get(REFRESH_HEADER))
            return _token_response()
        assert request.headers.get(ACCESS_HEADER) == ACCESS
        return _page([])

    client = _client(handler)
    await client.get_collection("/bookings")
    await client.get_collection("/bookings")

    assert exchanges == [REFRESH]


@pytest.mark.asyncio
async def test_a_transport_failure_on_the_exchange_never_prints_the_token():
    """R1.4 — h11 embeds an illegal header value verbatim, so a token with a stray newline
    would otherwise print in full on the very first run. Asserted over the whole traceback."""

    def handler(request):
        raise httpx.ConnectError(f"bad header value {REFRESH}")

    with pytest.raises(PmsUnavailableError) as caught:
        await _client(handler).get_collection("/bookings")

    rendered = "".join(
        traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__)
    )
    assert REFRESH not in rendered


@pytest.mark.asyncio
async def test_a_failed_exchange_does_not_echo_the_response_body():
    """A 4xx from an auth endpoint can echo what was sent."""
    handler = _routing(token=httpx.Response(401, text=f"bad token {REFRESH}"))

    with pytest.raises(PmsUnavailableError) as caught:
        await _client(handler).get_collection("/bookings")

    assert REFRESH not in str(caught.value)
    assert "not shown" in str(caught.value)


@pytest.mark.asyncio
async def test_a_rotated_refresh_token_fails_loudly_without_printing_it():
    """R1.5, design D5.

    MEASURED: it does not rotate. If it ever does, the adapter must NOT persist the new value —
    that would make it a second credential-writing path, and the CLI is declared the only one
    (`specs/pms-provider-resolution.md`). Failing is the safe direction: the alternative is the
    account locking itself out 30 days later.
    """
    rotated = "brand-new-refresh-token"
    handler = _routing(token=_token_response(refresh_token=rotated))

    with pytest.raises(PmsUnavailableError) as caught:
        await _client(handler).get_collection("/bookings")

    assert rotated not in str(caught.value)
    assert "pms_credentials rotate" in str(caught.value)


@pytest.mark.asyncio
async def test_an_exchange_without_a_token_is_not_treated_as_success():
    handler = _routing(token=httpx.Response(200, json={"expiresIn": 86400}))

    with pytest.raises(PmsUnavailableError, match="no access token"):
        await _client(handler).get_collection("/bookings")


# --- R1.3: where the requests go --------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://beds24.com/api/v2/bookings",
        "https://beds24.com.evil.tld/api/v2/bookings",
        "https://api.beds24.com/v2/bookings",
        "ftp://beds24.com/x",
    ],
)
def test_only_https_to_the_exact_host_is_allowed(url):
    """A substring check would pass `api.beds24.com.evil.tld`, which contains the real host."""
    from app.integrations.infrastructure.beds24.client import _assert_host_allowed

    with pytest.raises(PmsUnavailableError):
        _assert_host_allowed(url)


def test_the_real_base_is_allowed():
    from app.integrations.infrastructure.beds24.client import _assert_host_allowed

    _assert_host_allowed(f"{BEDS24_BASE_URL}/bookings")


def _host_recorder(contacted):
    def handler(request):
        contacted.append(request.url.host)
        if request.url.path.endswith("/authentication/token"):
            return _token_response()
        return _page([])

    return handler


@pytest.mark.asyncio
async def test_an_absolute_path_is_refused_before_it_reaches_a_foreign_host():
    """R1.3, through the composition where the guard actually runs.

    The two tests above call `_assert_host_allowed` with pre-built URLs, which is how the
    control could be inoperative while looking covered: it used to receive
    `f"{BEDS24_BASE_URL}{path}"`, whose hostname is `beds24.com` **whatever `path` says**,
    while `httpx` ignores `base_url` entirely for an absolute path. The guard read
    `beds24.com` and the request went to `evil.tld` with the access token attached.

    Driving it through `get_collection` is what makes the assertion mean something.
    """
    contacted = []

    with pytest.raises(PmsUnavailableError, match="refusing"):
        await _client(_host_recorder(contacted)).get_collection("https://evil.tld/steal")

    assert "evil.tld" not in contacted


@pytest.mark.asyncio
async def test_a_protocol_relative_path_lands_on_the_real_host():
    """MEASURED, and the reason this is a separate test rather than a second parameter.

    `//evil.tld/steal` looks like the same attack and is not: `httpx` normalises it onto the
    base URL (`https://beds24.com/api/v2/steal`), so there is nothing for the guard to refuse.
    Asserting a refusal here would have pinned behaviour the library does not have; what is
    worth pinning is that the request does not leave the allowed host.
    """
    contacted = []

    await _client(_host_recorder(contacted)).get_collection("//evil.tld/steal")

    assert set(contacted) == {"beds24.com"}


# --- R3.3 / D6: the verdict is in the body -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_refusal_under_a_2xx_is_not_read_as_success():
    """The measured normative finding: Beds24 answers 201 while refusing.

    Not only a write concern — the captured READ payload carries `success` too, so a client
    that goes straight for `data` trusts the status code exactly where the provider says not to.
    """
    handler = _routing(
        bookings=httpx.Response(
            201, json=[{"success": False, "errors": [{"field": "arrival", "message": "invalid"}]}]
        )
    )

    with pytest.raises(PmsUnavailableError, match="arrival: invalid"):
        await _client(handler).get_collection("/bookings")


@pytest.mark.asyncio
async def test_the_write_success_envelope_is_accepted():
    """Shape 2 of the four measured — `[{"success": true, "new": {...}}]`.

    R3.3 asks for all four and this one had no test anywhere in the suite (QA panel of sections
    3-5). It has no production caller yet: this change is read-only, and the first writer is
    `beds24-messaging-adapter`. Which is exactly why it is worth pinning now — an envelope shape
    the client silently mishandles would surface as a "successful" write that never happened,
    on the change that can least afford it.
    """
    handler = _routing(
        bookings=httpx.Response(201, json=[{"success": True, "new": {"id": 90923575}}])
    )

    rows = await _client(handler).get_collection("/bookings")

    assert rows == []  # no `data` in a write envelope, and that is not an error


@pytest.mark.asyncio
async def test_a_page_keeps_elements_it_cannot_recognise():
    """R2.4 — "nunca descartándolo en silencio", and the transport is a layer BELOW where the
    adapter implements that promise.

    This used to filter non-dicts out of `data`, so the adapter never saw them: a page of
    `[{...}, None, "not-a-booking"]` arrived as one row with no failure reported. Measured by
    the QA panel of sections 3-5.
    """
    handler = _routing(bookings=_page([{"id": 1}, None, "not-a-booking"]))

    rows = await _client(handler).get_collection("/bookings")

    assert len(rows) == 3


@pytest.mark.asyncio
async def test_concurrent_calls_share_one_token_exchange():
    """R1.6 — three concurrent calls measured three exchanges before the lock.

    Nothing calls it this way today; the guarantee is stated by the requirement, so the code
    enforces it rather than relying on every future caller staying sequential.
    """
    import asyncio

    exchanges = []

    def handler(request):
        if request.url.path.endswith("/authentication/token"):
            exchanges.append(1)
            return _token_response()
        return _page([])

    client = _client(handler)
    await asyncio.gather(*(client.get_collection("/bookings") for _ in range(3)))

    assert len(exchanges) == 1


@pytest.mark.asyncio
async def test_a_malformed_request_envelope_is_recognised():
    """Shape 4: a dict rather than a list, with `error` instead of `errors`."""
    handler = _routing(
        bookings=httpx.Response(
            200, json={"success": False, "code": 400, "error": "Request body must be an array"}
        )
    )

    with pytest.raises(PmsUnavailableError, match="must be an array"):
        await _client(handler).get_collection("/bookings")


@pytest.mark.asyncio
async def test_a_refusal_reported_only_as_a_warning_is_still_a_refusal():
    """MEASURED: a rejected field came back under `warnings` with `success: false`.

    Reading only `errors` would report "refused without detail" and hide the naming line.
    """
    handler = _routing(
        bookings=httpx.Response(
            201,
            json=[{"success": False, "warnings": [{"field": "webhooks", "message": "Invalid"}]}],
        )
    )

    with pytest.raises(PmsUnavailableError, match="webhooks: Invalid"):
        await _client(handler).get_collection("/bookings")


@pytest.mark.asyncio
async def test_an_unrecognised_envelope_is_a_failure_not_a_guess():
    """A multi-element list from a GET: guessing which member speaks for the request is how a
    refusal gets read as an acceptance."""
    handler = _routing(bookings=httpx.Response(200, json=[{"success": True}, {"success": False}]))

    with pytest.raises(PmsUnavailableError, match="unrecognised envelope"):
        await _client(handler).get_collection("/bookings")


@pytest.mark.asyncio
async def test_an_error_body_that_echoes_our_token_never_reaches_the_report():
    """R1.4 — and the sink is the operator's report, not just a log.

    `SyncReservationsFromPmsUseCase` folds this message verbatim into the run report under a
    comment claiming it carries "the adapter's vocabulary, never a provider payload". A 401
    body of `{"error": "Invalid token: <what we sent>"}` made that false. `_access` already
    refused to show a body for this reason; `_get` — the request carrying the 24 h access
    token — did not.
    """
    handler = _routing(
        bookings=httpx.Response(401, json={"error": f"Invalid token: {ACCESS}"})
    )

    with pytest.raises(PmsUnavailableError) as caught:
        await _client(handler).get_collection("/bookings")

    assert ACCESS not in str(caught.value)
    assert "***redacted***" in str(caught.value)


@pytest.mark.asyncio
async def test_provider_text_cannot_forge_a_second_report_line():
    """Bounded like `ChannexAdapter._element_reference`, and for the measured reason: a long
    value carrying a newline forges an extra line shaped like ours in a line-oriented sink."""
    forged = "boom\nbeds24: everything is fine cost=0\n" + "x" * 3000
    handler = _routing(bookings=httpx.Response(400, json={"error": forged}))

    with pytest.raises(PmsUnavailableError) as caught:
        await _client(handler).get_collection("/bookings")

    assert "\n" not in str(caught.value)
    assert len(str(caught.value)) < 400


@pytest.mark.asyncio
async def test_a_refusal_in_the_body_that_echoes_our_token_is_redacted_too():
    """The 2xx-with-`success:false` path composes its own message and needs the same guard."""
    handler = _routing(
        bookings=httpx.Response(
            201, json=[{"success": False, "error": f"bad token {ACCESS}"}]
        )
    )

    with pytest.raises(PmsUnavailableError) as caught:
        await _client(handler).get_collection("/bookings")

    assert ACCESS not in str(caught.value)


@pytest.mark.asyncio
async def test_an_http_error_body_is_never_echoed_raw():
    """Rule 11 of steering/security.md: error sinks take a structured form.

    A 4xx from a misrouted request can echo what was sent — guest data, and per rule 13,
    cardholder data.
    """
    handler = _routing(
        bookings=httpx.Response(400, json={"guest": "Ana Perez", "cvv": "737"})
    )

    with pytest.raises(PmsUnavailableError) as caught:
        await _client(handler).get_collection("/bookings")

    assert "Ana Perez" not in str(caught.value)
    assert "737" not in str(caught.value)


# --- R2 / D7: pagination -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_pages_until_the_provider_says_there_is_no_more():
    pages = [_page([{"id": 1}], more=True), _page([{"id": 2}], more=False)]
    seen = []

    def handler(request):
        if request.url.path.endswith("/authentication/token"):
            return _token_response()
        seen.append(request.url.params.get("page"))
        return pages[len(seen) - 1]

    rows = await _client(handler).get_collection("/bookings")

    assert [row["id"] for row in rows] == [1, 2]
    assert seen == ["1", "2"]


@pytest.mark.asyncio
async def test_the_next_page_link_from_the_body_is_never_followed():
    """Design D7 — it is an absolute URL arriving in the response body.

    Following it would let whoever can influence that body choose where the next request, which
    carries an account-scoped credential, is sent. `_page` puts `https://evil.tld/next` there.
    """
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.path.endswith("/authentication/token"):
            return _token_response()
        return _page([{"id": 1}], more=len(hosts) < 3)

    await _client(handler).get_collection("/bookings")

    assert set(hosts) == {"beds24.com"}


@pytest.mark.asyncio
async def test_an_empty_page_ends_the_walk_whatever_the_provider_claims():
    """Also what stops a provider that keeps promising rows it never sends."""
    calls = []

    def handler(request):
        if request.url.path.endswith("/authentication/token"):
            return _token_response()
        calls.append(1)
        return _page([], more=True)

    rows = await _client(handler).get_collection("/bookings")

    assert rows == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reaching_the_page_cap_raises_instead_of_truncating():
    """A short list returned from inside a sync is indistinguishable from "nothing more"."""
    handler = _routing(bookings=_page([{"id": 1}], more=True))

    with pytest.raises(PmsUnavailableError, match="refusing to truncate"):
        await _client(handler, max_pages=3).get_collection("/bookings")


@pytest.mark.asyncio
async def test_a_non_list_data_is_refused():
    handler = _routing(
        bookings=httpx.Response(200, json={"success": True, "data": {"id": 1}})
    )

    with pytest.raises(PmsUnavailableError, match="non-list"):
        await _client(handler).get_collection("/bookings")


# --- R3.1 / R3.2: credits ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [("1", 1), ("1.1", 1.1), ("0", 0), ("nonsense", None)],
)
def test_the_cost_header_is_read_as_a_decimal(raw, expected):
    """`int("1.1")` raises, which would record a fractional write cost as "not measured" and
    make the derived budget optimistic."""
    assert parse_cost(httpx.Headers({"X-Request-Cost": raw})) == expected


def test_an_absent_cost_header_is_unknown_and_never_zero():
    """An unknown cost and a free call lead to different budgets."""
    assert parse_cost(httpx.Headers({})) is None


@pytest.mark.asyncio
async def test_an_exhausted_quota_stops_instead_of_retrying():
    """R3.2 — the quota is per ACCOUNT, so retrying competes with the legitimate sync."""
    calls = []

    def handler(request):
        if request.url.path.endswith("/authentication/token"):
            return _token_response()
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(PmsUnavailableError, match="credit window exhausted"):
        await _client(handler).get_collection("/bookings")

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_every_request_logs_its_cost_and_remaining_credit(caplog):
    """R3.1 — in production this line is the operator's only view of the budget."""
    with caplog.at_level("INFO"):
        await _client(_routing(bookings=_page([], cost="1.1"))).get_collection("/bookings")

    [line] = [r.getMessage() for r in caplog.records if "beds24:" in r.getMessage()]
    assert "cost=1.1" in line
    assert "96.8" in line
    assert REFRESH not in line and ACCESS not in line


# --- get_resource ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_id_is_none_rather_than_an_error():
    """The port promises `None` and `MockPMSAdapter` behaves that way — substitutability is a
    contract (`steering/backend-architecture.md`), not a courtesy.

    Beds24 has no per-id route for bookings, so an unknown id is an empty `data`, not a 404.
    """
    assert await _client(_routing(bookings=_page([]))).get_resource("/bookings") is None


@pytest.mark.asyncio
async def test_a_known_id_returns_its_element():
    found = await _client(_routing(bookings=_page([{"id": 90923575}]))).get_resource("/bookings")

    assert found == {"id": 90923575}
