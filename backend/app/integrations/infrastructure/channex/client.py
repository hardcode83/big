"""HTTP transport for the Channex API (R2, design D2, D5, D6).

Measured against the real documentation, not assumed:

- Base URL of the staging environment: `https://staging.channex.io/api/v1`.
- Authentication: the `user-api-key` header, issued in Organisation -> API Keys.
- Success envelope: `{"meta": {"total", "page", "limit"}, "data": [{"type", "id",
  "attributes"}]}`; a single resource returns `data` as an object.
- Error envelope: `{"errors": {"code", "title"}}`.
- Pagination: `?page=N&limit=N`, **default limit 10** — paginating is not optional.

Everything this module raises outward is `PmsUnavailableError`, so no caller has to know
that Channex is reached over HTTP or that we use httpx.
"""

from typing import Any

import httpx

from app.integrations.domain.errors import PmsUnavailableError

API_KEY_HEADER = "user-api-key"
REDACTED = "***redacted***"


class ChannexClient:
    """Thin, paginating client. Owns transport concerns and nothing else.

    `transport` exists for the tests: the suite drives this through
    `httpx.MockTransport` fed by the captured fixtures, because R2.5 forbids a test that
    reaches the network.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        max_pages: int,
        page_limit: int,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            # Not a PmsUnavailableError: an empty key is a configuration mistake made
            # before any request exists, and R3.2 wants the command to refuse to start.
            raise ValueError("Channex API key is empty")
        self._api_key = api_key
        self._base_url = base_url
        self._max_pages = max_pages
        self._page_limit = page_limit
        self._timeout = timeout
        self._transport = transport

    def __repr__(self) -> str:
        """Redacted on purpose (R2.3).

        The default dataclass-ish repr of a client holding a credential is one `logger.debug`
        away from writing the key to disk. Tested in `test_channex_client.py`.
        """
        return f"ChannexClient(base_url={self._base_url!r}, api_key={REDACTED})"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={API_KEY_HEADER: self._api_key},
            timeout=self._timeout,
            transport=self._transport,
        )

    async def get_collection(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Every `data` element across every page, or raise.

        Termination, and the subtlety that the QA panel caught:

        - `meta.total` present -> stop once `total` rows are collected.
        - `meta.total` absent but `meta.limit` present -> a page shorter than the
          provider's OWN declared page size is the last one.
        - neither present -> keep going until a page comes back **empty**, which costs one
          extra request and is the only safe signal left.

        What it deliberately does NOT do is infer "last page" from *our requested* limit. A
        provider that silently caps pages below what we asked for (ask 100, always get 10)
        would make the very first page look short, and the sync would return 10 of 30
        reservations with no error — the exact silent truncation design D6 forbids, and it
        is invisible precisely because it is indistinguishable from "the PMS had nothing
        more".

        Reaching `max_pages` **raises** for the same reason.
        """
        collected: list[dict[str, Any]] = []
        page = 1
        async with self._client() as client:
            while True:
                if page > self._max_pages:
                    raise PmsUnavailableError(
                        f"Channex returned more than {self._max_pages} pages for {path}; "
                        "refusing to truncate a reservation sync"
                    )
                payload = await self._get(client, path, params={
                    **(params or {}),
                    "page": page,
                    "limit": self._page_limit,
                })
                rows = payload.get("data") or []
                if not isinstance(rows, list):
                    raise PmsUnavailableError(
                        f"Channex returned a non-list `data` for the collection {path}"
                    )
                collected.extend(rows)

                if not rows:
                    # An empty page means there is nothing more, whatever `total` claims.
                    # Also what stops a provider that keeps promising rows it never sends
                    # from looping all the way to `max_pages`.
                    return collected

                meta = payload.get("meta") or {}
                total = meta.get("total")
                if isinstance(total, int):
                    if len(collected) >= total:
                        return collected
                else:
                    provider_limit = meta.get("limit")
                    if (
                        isinstance(provider_limit, int)
                        and 0 < provider_limit != self._page_limit
                        and len(rows) < provider_limit
                    ):
                        # Short against the page size the PROVIDER declares — and only when
                        # that number is NOT the one we asked for.
                        #
                        # `!= self._page_limit` is the whole point: many REST APIs echo the
                        # `?limit=` query parameter straight back into `meta.limit`, and we
                        # cannot tell an echo from an honest server-side cap. If a provider
                        # echoes 100 while really serving 10 pages of 10, trusting the echo
                        # reproduces the original silent-truncation bug one layer deeper. A
                        # `meta.limit` that differs from our request is evidently the
                        # provider's own number and can be trusted; one that matches is
                        # ambiguous, so we fall through and page until a page comes back
                        # empty. Costs one extra request; cannot lose reservations.
                        return collected
                page += 1

    async def get_resource(self, path: str) -> dict[str, Any] | None:
        """One resource's `data`, or `None` when the provider has no such id.

        `None` rather than an error because `PMSAdapter.get_reservation` promises exactly
        that, and `MockPMSAdapter` behaves that way — the substitutability
        `steering/backend-architecture.md` requires is a contract, not a courtesy.
        """
        async with self._client() as client:
            payload = await self._get(client, path, params=None, none_on_404=True)
            if payload is None:
                return None
            data = payload.get("data")
            if data is None:
                return None
            if not isinstance(data, dict):
                raise PmsUnavailableError(
                    f"Channex returned a non-object `data` for the resource {path}"
                )
            return data

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, Any] | None,
        none_on_404: bool = False,
    ) -> Any:
        try:
            response = await client.get(path, params=params)
        except httpx.HTTPError as error:
            # `from error` keeps the cause for debugging; the message we build carries the
            # class and the path, never the request headers. Tracebacks do not print locals,
            # so the key does not travel — asserted over the whole formatted traceback in
            # `test_channex_client.py` rather than assumed.
            raise PmsUnavailableError(
                f"Channex request to {path} failed: {type(error).__name__}"
            ) from error

        if none_on_404 and response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise PmsUnavailableError(
                f"Channex answered {response.status_code} for {path}: {_error_detail(response)}"
            )
        try:
            return response.json()
        except ValueError as error:
            raise PmsUnavailableError(
                f"Channex answered {response.status_code} for {path} with a non-JSON body"
            ) from error


def _error_detail(response: httpx.Response) -> str:
    """The `{"errors": {"code", "title"}}` envelope, degrading safely.

    Never falls back to the raw body: a 4xx from a misrouted request can echo what was
    sent, and rule 11 of `steering/security.md` is explicit that error sinks take a
    structured form rather than whatever the provider handed back.
    """
    try:
        body = response.json()
    except ValueError:
        return "unparseable error body"
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, dict):
        code = errors.get("code")
        title = errors.get("title")
        return f"code={code!r} title={title!r}"
    return "no `errors` object in the response"
