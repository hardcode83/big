"""The Channex HTTP client: envelopes, pagination, errors and credential hygiene.

Every test drives `httpx.MockTransport` — no network, ever (R2.5). The suite must pass on
a machine that has never seen a Channex account, which is also what makes it usable in CI.
"""

import json
import traceback

import httpx
import pytest

from app.integrations.domain.errors import PmsUnavailableError
from app.integrations.infrastructure.channex.client import REDACTED, ChannexClient

API_KEY = "uU08XiMgk8a7CrY4xUjAReUIuTrn83R123adaVb8Tf"
BASE_URL = "https://staging.channex.io/api/v1"


def _client(handler, *, max_pages: int = 50, page_limit: int = 100) -> ChannexClient:
    return ChannexClient(
        api_key=API_KEY,
        base_url=BASE_URL,
        max_pages=max_pages,
        page_limit=page_limit,
        transport=httpx.MockTransport(handler),
    )


def _page(rows: list[dict], *, total: int, page: int, limit: int) -> httpx.Response:
    return httpx.Response(
        200,
        json={"meta": {"total": total, "page": page, "limit": limit}, "data": rows},
    )


def _row(index: int) -> dict:
    return {"type": "booking", "id": f"id-{index}", "attributes": {"unique_id": f"U-{index}"}}


def test_rejects_an_empty_api_key_before_any_request():
    with pytest.raises(ValueError, match="empty"):
        ChannexClient(api_key="   ", base_url=BASE_URL, max_pages=1, page_limit=1)


@pytest.mark.asyncio
async def test_sends_the_user_api_key_header():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return _page([_row(1)], total=1, page=1, limit=100)

    await _client(handler).get_collection("/bookings")
    assert seen["user-api-key"] == API_KEY


@pytest.mark.asyncio
async def test_single_page_collection():
    def handler(request: httpx.Request) -> httpx.Response:
        return _page([_row(1), _row(2)], total=2, page=1, limit=100)

    rows = await _client(handler).get_collection("/bookings")
    assert [row["id"] for row in rows] == ["id-1", "id-2"]


@pytest.mark.asyncio
async def test_paginates_until_total_is_reached():
    """The reason pagination is not optional: Channex's default `limit` is 10."""
    pages = {1: [_row(1), _row(2)], 2: [_row(3), _row(4)], 3: [_row(5)]}
    requested: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested.append(request.url.params.get("limit"))
        return _page(pages[page], total=5, page=page, limit=2)

    rows = await _client(handler, page_limit=2).get_collection("/bookings")
    assert [row["id"] for row in rows] == ["id-1", "id-2", "id-3", "id-4", "id-5"]
    assert requested == ["2", "2", "2"]


@pytest.mark.asyncio
async def test_stops_on_a_page_shorter_than_the_limit_the_provider_declares():
    """No `total`, but `meta.limit` is there AND differs from what we asked for.

    The mismatch is what makes it trustworthy: it is evidently the provider's own page
    size, not our `?limit=` echoed back.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        rows = [_row(1), _row(2)] if page == 1 else [_row(3)]
        return httpx.Response(200, json={"meta": {"page": page, "limit": 2}, "data": rows})

    rows = await _client(handler, page_limit=5).get_collection("/bookings")
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_does_not_trust_a_meta_limit_that_merely_echoes_the_request():
    """The same silent truncation as design D6, one layer deeper.

    Plenty of REST APIs echo `?limit=N` straight back into `meta.limit`, and an echo is
    indistinguishable from an honest server-side cap. A provider that echoes 100 while
    really serving pages of 10 would make page 1 look short and end the sync at 10 of 30.
    When `meta.limit` equals what we asked for, it is ambiguous and gets ignored.
    """
    provider_page_size = 10
    all_rows = [_row(index) for index in range(30)]

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested_limit = int(request.url.params["limit"])
        start = (page - 1) * provider_page_size
        return httpx.Response(
            200,
            json={
                # Echoes our request verbatim while serving a tenth of it, and omits `total`.
                "meta": {"page": page, "limit": requested_limit},
                "data": all_rows[start : start + provider_page_size],
            },
        )

    rows = await _client(handler, page_limit=100).get_collection("/bookings")
    assert len(rows) == 30


@pytest.mark.asyncio
async def test_does_not_truncate_when_the_provider_caps_pages_below_the_requested_limit():
    """Design D6, and the silent-truncation hole the QA panel proved.

    We ask for 100 per page; the provider quietly serves 10 and omits `total`. Inferring
    "last page" from OUR requested limit returned 10 of 30 reservations with no error — a
    sync that drops two thirds of its rows and looks exactly like an empty PMS.
    """
    provider_page_size = 10
    all_rows = [_row(index) for index in range(30)]

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        start = (page - 1) * provider_page_size
        # No `total` AND no `limit` in `meta`: the provider tells us nothing.
        return httpx.Response(
            200, json={"meta": {"page": page}, "data": all_rows[start : start + provider_page_size]}
        )

    rows = await _client(handler, page_limit=100).get_collection("/bookings")
    assert len(rows) == 30


@pytest.mark.asyncio
async def test_a_lying_total_does_not_prevent_termination():
    """A provider promising rows it never sends must not spin to the page cap."""
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        rows = [_row(1)] if page == 1 else []
        return httpx.Response(200, json={"meta": {"total": 500, "page": page}, "data": rows})

    rows = await _client(handler, max_pages=4, page_limit=10).get_collection("/bookings")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_non_integer_total_falls_back_to_paging_until_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        rows = [_row(page)] if page <= 3 else []
        return httpx.Response(200, json={"meta": {"total": "many", "page": page}, "data": rows})

    rows = await _client(handler, page_limit=10).get_collection("/bookings")
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_reaching_the_page_cap_raises_instead_of_truncating():
    """Design D6: a short list inside a sync reads as "the PMS had nothing more"."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        # Always claims there is more, which is the provider bug the cap exists for.
        return _page([_row(page)], total=10_000, page=page, limit=1)

    with pytest.raises(PmsUnavailableError, match="refusing to truncate"):
        await _client(handler, max_pages=3, page_limit=1).get_collection("/bookings")


@pytest.mark.asyncio
async def test_empty_page_terminates_even_when_total_disagrees():
    def handler(request: httpx.Request) -> httpx.Response:
        return _page([], total=99, page=1, limit=100)

    assert await _client(handler).get_collection("/bookings") == []


@pytest.mark.asyncio
async def test_get_resource_returns_none_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": {"code": "not_found", "title": "Not Found"}})

    assert await _client(handler).get_resource("/bookings/nope") is None


@pytest.mark.asyncio
async def test_get_resource_returns_the_data_object():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": _row(7)})

    resource = await _client(handler).get_resource("/bookings/id-7")
    assert resource is not None
    assert resource["id"] == "id-7"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500, 503])
async def test_error_statuses_become_pms_unavailable(status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"errors": {"code": "boom", "title": "Boom"}})

    with pytest.raises(PmsUnavailableError) as excinfo:
        await _client(handler).get_collection("/bookings")
    assert str(status) in str(excinfo.value)
    assert "code='boom'" in str(excinfo.value)


@pytest.mark.asyncio
async def test_transport_failure_becomes_pms_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(PmsUnavailableError, match="ConnectError"):
        await _client(handler).get_collection("/bookings")


@pytest.mark.asyncio
async def test_non_json_body_becomes_pms_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    with pytest.raises(PmsUnavailableError, match="non-JSON"):
        await _client(handler).get_collection("/bookings")


@pytest.mark.asyncio
async def test_a_4xx_body_is_never_echoed_raw():
    """Rule 11 of steering/security.md: error sinks take a structured form.

    A misrouted request can come back with the payload it sent, so the detail is built from
    the documented `errors` object and nothing else.
    """
    secret_ish = "SENSITIVE-ECHOED-BODY"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text=secret_ish)

    with pytest.raises(PmsUnavailableError) as excinfo:
        await _client(handler).get_collection("/bookings")
    assert secret_ish not in str(excinfo.value)


def test_repr_redacts_the_api_key():
    client = ChannexClient(api_key=API_KEY, base_url=BASE_URL, max_pages=1, page_limit=1)
    assert API_KEY not in repr(client)
    assert REDACTED in repr(client)


@pytest.mark.asyncio
async def test_the_api_key_never_reaches_a_traceback():
    """R2.3, and the reason it is a test and not a promise.

    `httpx` carries the request on its exceptions, so an error message built from
    `response.request.headers` would leak the credential into every log line that renders
    the traceback. This walks the FULL formatted traceback, chained causes included.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errors": {"code": "unauthorized", "title": "no"}})

    try:
        await _client(handler).get_collection("/bookings")
    except PmsUnavailableError as error:
        rendered = "".join(traceback.format_exception(error))
    else:  # pragma: no cover - the handler always fails
        pytest.fail("expected PmsUnavailableError")

    assert API_KEY not in rendered


@pytest.mark.asyncio
async def test_the_api_key_never_reaches_a_traceback_on_transport_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    try:
        await _client(handler).get_collection("/bookings")
    except PmsUnavailableError as error:
        rendered = "".join(traceback.format_exception(error))
    else:  # pragma: no cover
        pytest.fail("expected PmsUnavailableError")

    assert API_KEY not in rendered
    assert API_KEY not in json.dumps(rendered)
