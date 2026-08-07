"""HTTP transport for the Beds24 API V2 (R1, R3, design D2, D4-D8).

Measured against the real API by `pms-beds24-spike`, not taken from documentation — this
project has been wrong twice by trusting provider docs (the cost header was guessed as
`x-requestcost` and matched nothing; four rules of the Channex mapping contradict what its
docs implied). What is measured:

- Base: `https://beds24.com/api/v2`. There is **no** `api.` subdomain.
- Auth is two-legged: a long-lived refresh token buys a 24 h access token from
  `GET /authentication/token` (sent as a `refreshToken` header), and the access token then
  travels as a `token` header. The response carries `token`, `expiresIn` and `refreshToken`.
- The refresh token does **not** rotate on use.
- The cost header is `X-Request-Cost`, **with hyphens**, and its value is **decimal** —
  writes cost fractionally. `X-Five-Min-Limit-Remaining` came back as `96.8`.
- The quota is 100 credits / 300 s **per account**, and a rejected request costs nothing.
- **The provider answers `2xx` even when it refuses**, putting the verdict in the body. A
  client that trusts the status code reports success for something that never happened.

Everything this module raises outward is `PmsUnavailableError`, so no caller learns that
Beds24 is reached over HTTP or that we use httpx — the same contract `ChannexClient` keeps.

**The credential arrives already decrypted, from `pms_credentials`** (`pms-provider-resolution`),
never from the environment. `BEDS24_REFRESH_TOKEN` exists only for the measurement bench in
`scripts/`, which rule 8 of `steering/security.md` covers; the application is governed by
rule 3, and this module is downstream of the single `decrypt` call in `pms_factory`.
"""

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.integrations.domain.errors import PmsUnavailableError

# CONSTANTS, not settings, and that is a security decision rather than an omission (design D2).
#
# `specs/pms-beds24-spike.md` requires the allowlist to be "derivada de una constante y **no**
# de `BEDS24_BASE_URL`: quien controle el entorno controlaría el destino, que es el ataque del
# que protege". The bench had a case for a configurable base (an operator pointing it
# somewhere); the application has none — Beds24 has **no staging environment**, so the reason
# `channex_base_url` is configurable (defaulting to staging so a mistake cannot touch a live
# account) does not exist here. A configurable base would be a lever with no use case guarding
# a credential that grants write access to every property in the account.
BEDS24_BASE_URL = "https://beds24.com/api/v2"
ALLOWED_HOSTS = frozenset({"beds24.com"})

TOKEN_PATH = "/authentication/token"
REFRESH_HEADER = "refreshToken"
ACCESS_HEADER = "token"

COST_HEADER = "x-request-cost"
REDACTED = "***redacted***"

logger = logging.getLogger(__name__)


class Beds24Client:
    """Paginating, cost-aware transport. Owns one account's credential for one run.

    `transport` exists for the tests: the suite drives this through `httpx.MockTransport` fed
    by the captured fixtures, because R2.6 forbids a test that reaches the network.
    """

    def __init__(
        self,
        *,
        refresh_token: str,
        max_pages: int,
        page_limit: int,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not refresh_token.strip():
            # Not a `PmsUnavailableError`: an empty credential is a configuration mistake made
            # before any request exists. `ChannexClient` refuses the same way.
            raise ValueError("Beds24 refresh token is empty")
        self._refresh_token = refresh_token.strip()
        self._access_token: str | None = None
        # R1.6 is a guarantee about exchanges per run, and a plain `if self._access_token is
        # None` does not enforce it: the QA panel of sections 3-5 gathered three concurrent
        # `get_collection` calls on one client and measured **three** exchanges, because all
        # three observed `None` before any of them assigned. No caller does that today — the
        # grouped sync calls `list_reservations` once per provider group, sequentially — so
        # this is a latent trap rather than a live bug, and a lock is cheaper than the comment
        # explaining why the invariant only holds by accident.
        self._exchange_lock = asyncio.Lock()
        self._max_pages = max_pages
        self._page_limit = page_limit
        self._timeout = timeout
        self._transport = transport

    def __repr__(self) -> str:
        """Redacted (R1.4). A repr of a credential-holding object is one `logger.debug` from disk.

        Both tokens matter here, not just the refresh one: the access token is good for 24 h and
        grants the same account-wide write access.
        """
        return f"Beds24Client(base_url={BEDS24_BASE_URL!r}, refresh_token={REDACTED})"

    async def get_collection(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Every `data` element across every page, or raise.

        Termination, in the order it is checked:

        - `pages.nextPageExists` is false -> done. The provider's own signal.
        - a page comes back empty -> done, whatever `nextPageExists` claimed.
        - `max_pages` reached -> **raise**, never truncate.

        Raising on the cap is `ChannexClient`'s reasoning and it transfers intact: a short list
        returned from inside a sync is indistinguishable from "the PMS had nothing more", so
        truncating silently loses reservations with no symptom.

        **`pages.nextPageLink` is deliberately ignored** (design D7). It is an absolute URL that
        arrives *in the response body*, so following it would let whoever can influence that
        body choose where the next request — carrying an account-scoped credential — is sent.
        The host allowlist exists precisely to prevent that, and honouring a link from the body
        would route around it. Paging with our own counter costs nothing and cannot be steered.
        """
        collected: list[dict[str, Any]] = []
        page = 1
        async with self._session() as client:
            while True:
                if page > self._max_pages:
                    raise PmsUnavailableError(
                        f"Beds24 returned more than {self._max_pages} pages for {path}; "
                        "refusing to truncate a reservation sync"
                    )
                payload = await self._get(
                    client, path, params={**(params or {}), "page": page}
                )
                rows = payload.get("data")
                if rows is None:
                    rows = []
                if not isinstance(rows, list):
                    raise PmsUnavailableError(
                        f"Beds24 returned a non-list `data` for the collection {path}"
                    )
                # **Everything travels, including elements that are not dicts.** This used to
                # filter with `if isinstance(row, dict)`, which defeated R2.4 one layer below
                # where R2.4 is implemented: the adapter maps per element and reports what it
                # cannot map, but it never saw a row this line had already dropped. The QA
                # panel of sections 3-5 reproduced it — a page of
                # `[{"id": 1}, None, "not-a-booking"]` came back as one row, with no log line
                # and no `PmsRowFailure` for the other two.
                #
                # It was also inconsistent with `get_resource` twenty lines down, which raises
                # on exactly this shape. Letting the element through is the better of the two:
                # the adapter turns it into a reported failure, and reporting beats both
                # dropping it and failing the whole page for it.
                collected.extend(rows)

                if not rows:
                    return collected
                pages = payload.get("pages")
                more = pages.get("nextPageExists") if isinstance(pages, dict) else None
                if more is not True:
                    # Anything that is not an explicit `true` ends the walk — `false`, absent,
                    # or a shape we do not recognise. The opposite default would keep paging a
                    # provider that never says stop, all the way to the cap, and turn a missing
                    # field into a failed sync.
                    return collected
                page += 1

    async def get_resource(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """The first `data` element, or `None` when the provider has no such id.

        `None` rather than an error because `PMSAdapter.get_reservation` promises exactly that
        and `MockPMSAdapter` behaves that way — substitutability is a contract
        (`steering/backend-architecture.md`: "mismas excepciones, misma forma de retorno").

        Beds24 has no per-id resource route for bookings: you filter the collection. So an
        unknown id is an **empty `data`**, not a 404, and that is what maps to `None` here.
        """
        async with self._session() as client:
            payload = await self._get(client, path, params=params or {})
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        first = rows[0]
        if not isinstance(first, dict):
            raise PmsUnavailableError(
                f"Beds24 returned a non-object element for the resource {path}"
            )
        return first

    def _session(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BEDS24_BASE_URL, timeout=self._timeout, transport=self._transport
        )

    async def _access(self, client: httpx.AsyncClient) -> str:
        """The 24 h access token, exchanged on first use and kept **in memory only** (R1.2).

        Lazy rather than exchanged in the constructor: `_build` in the factory constructs the
        adapter, and a constructor that goes to the network makes every future cheap path pay
        for a request it may not need. Cached on the instance rather than in a process-wide
        store, so R1.6 ("one exchange per run and account") is satisfied by the shape the sync
        already has — `_sync_one_provider` resolves one adapter per provider group and uses it
        for the whole group. A shared cache would keep an account credential alive past the run
        that decrypted it, which is the invariant `pms_factory`'s "caches no adapter" docstring
        states and tests.
        """
        if self._access_token is not None:
            return self._access_token

        async with self._exchange_lock:
            # Re-checked inside the lock: whoever waited here while another coroutine did the
            # exchange must use its result, not queue up a second one.
            if self._access_token is not None:
                return self._access_token
            return await self._exchange(client)

    async def _exchange(self, client: httpx.AsyncClient) -> str:
        request = client.build_request(
            "GET", TOKEN_PATH, headers={REFRESH_HEADER: self._refresh_token}
        )
        _assert_host_allowed(request.url)
        try:
            response = await client.send(request)
        except httpx.HTTPError as error:
            # The only request that carries the REFRESH token, so the one that most needs the
            # message bounded to a class name. h11 embeds an illegal header value verbatim in
            # its error, so a token stored with a stray newline would otherwise print in full.
            raise PmsUnavailableError(
                f"Beds24 token exchange failed: {type(error).__name__}"
            ) from None

        if response.status_code != 200:
            raise PmsUnavailableError(
                f"Beds24 token exchange answered {response.status_code}. "
                "Response body not shown — it can echo what was sent."
            )
        try:
            payload = response.json() or {}
        except ValueError:
            raise PmsUnavailableError(
                "Beds24 token exchange returned a non-JSON body"
            ) from None

        token = payload.get("token")
        if not token or not isinstance(token, str):
            raise PmsUnavailableError("Beds24 token exchange returned no access token")

        rotated = payload.get("refreshToken")
        if rotated and rotated != self._refresh_token:
            # MEASURED: it does not rotate. This branch is defensive, and it FAILS rather than
            # continuing (design D5). Persisting the new value from here would make the adapter
            # a second credential-writing path, and `specs/pms-provider-resolution.md` declares
            # the CLI "**única** vía de aprovisionamiento" because every other one skips the
            # encryption, the cross-tenant guard or the audit row.
            #
            # Failing loudly is the safe direction: the alternative is the account locking
            # itself out 30 days after an unnoticed rotation. The value is never printed.
            raise PmsUnavailableError(
                "Beds24 returned a NEW refresh token, which contradicts the measured behaviour "
                "of this API. The stored credential is now stale: rotate it with "
                "`python -m app.integrations.cli.pms_credentials rotate` before syncing again."
            )

        self._access_token = token
        return token

    async def _get(
        self, client: httpx.AsyncClient, path: str, *, params: dict[str, Any]
    ) -> dict[str, Any]:
        token = await self._access(client)
        request = client.build_request(
            "GET",
            path,
            params={**params, "limit": self._page_limit},
            headers={ACCESS_HEADER: token},
        )
        _assert_host_allowed(request.url)
        try:
            response = await client.send(request)
        except httpx.HTTPError as error:
            raise PmsUnavailableError(
                f"Beds24 request to {path} failed: {type(error).__name__}"
            ) from None

        _log_cost(path, response)

        if response.status_code == 429:
            # No retry, by measurement and by contract. The quota is 100 credits / 300 s per
            # ACCOUNT, so retrying competes with the legitimate sync and with any other consumer
            # of the same account. `PmsUnavailableError` is the error whose meaning is "this
            # sync did not happen", which `pms_sync` already maps to exit code 3.
            raise PmsUnavailableError(
                f"Beds24 credit window exhausted on {path} (HTTP 429); "
                "stopping instead of retrying — the quota is per account"
            )
        if response.status_code >= 400:
            raise PmsUnavailableError(
                self._redact(
                    f"Beds24 answered {response.status_code} for {path}: "
                    f"{_error_detail(response)}"
                )
            )
        try:
            payload = response.json()
        except ValueError:
            raise PmsUnavailableError(
                f"Beds24 answered {response.status_code} for {path} with a non-JSON body"
            ) from None
        try:
            return _accepted(payload, path)
        except PmsUnavailableError as error:
            raise PmsUnavailableError(self._redact(str(error))) from None

    def _redact(self, message: str) -> str:
        """Remove this client's own credentials from a message before it escapes (R1.4).

        The last line of defence, and the security panel of sections 3-5 showed it was missing:
        a `401` body of `{"error": "Invalid token: <the token we sent>"}` produced
        `Beds24 answered 401 for /bookings: Invalid token: <token>`, which
        `SyncReservationsFromPmsUseCase` folds verbatim into the operator's report — under a
        comment claiming the message carries "the adapter's vocabulary, never a provider
        payload".

        `_access` already refused to show a body for exactly this reason. `_get` did not, and
        `_get` is the request that carries the **access token**, which is good for 24 h and
        grants the same account-wide write access as the refresh token.
        """
        for secret in (self._refresh_token, self._access_token):
            if secret:
                message = message.replace(secret, REDACTED)
        return message


def _accepted(payload: Any, path: str) -> dict[str, Any]:
    """The read envelope, or `PmsUnavailableError` — the verdict is in the BODY (R3.3, D6).

    The measured normative finding of `pms-beds24-spike` is that Beds24 answers `201` while
    refusing a write. It is not only a write concern: the captured **read** payload carries
    `success` too (`fixtures/beds24/bookings.json` -> `payload.success`), so a client that
    reads `data` without checking the envelope trusts the status code exactly where the
    provider says not to.

    The four measured shapes:

    1. read/success  -> `{"success": true, "count": N, "pages": {...}, "data": [...]}`
    2. write/success -> `[{"success": true, "new": {"id": ...}, "info": [...]}]`
    3. write/refused -> `[{"success": false, "errors": [...]}]`, under HTTP **201**
    4. malformed     -> `{"success": false, "code": 400, "error": "..."}` — a dict, not a list

    Shapes 2 and 3 are handled although this change makes no writes: the module owns the
    envelope, and leaving a measured refusal shape unrecognised would make the first write
    (`beds24-messaging-adapter`) inherit a client that silently accepts it.
    """
    element = payload
    if isinstance(payload, list):
        # A single-element list is the write envelope; anything else from a GET is a shape we
        # do not recognise, and guessing which member speaks for the request is how a refusal
        # gets read as an acceptance.
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise PmsUnavailableError(
                f"Beds24 returned an unrecognised envelope for {path}"
            )
        element = payload[0]

    if not isinstance(element, dict):
        raise PmsUnavailableError(f"Beds24 returned an unrecognised envelope for {path}")

    if element.get("success") is False:
        raise PmsUnavailableError(
            f"Beds24 refused {path} in the body: {_envelope_detail(element)}"
        )
    return element


def _envelope_detail(element: dict[str, Any]) -> str:
    """The provider's own structured verdict. **Never the raw body.**

    Rule 11 of `steering/security.md` requires error sinks to take a structured form rather
    than whatever the provider handed back, and a 4xx from a misrouted request can echo what
    was sent — which, for a PMS, includes guest data and (rule 13) cardholder data.

    `warnings` as well as `errors`: MEASURED, a refused `additionalData` came back as
    `[{"success": false, "warnings": [...]}]`. The name says warning, `success` is false and
    nothing happened, so reading only `errors` would report "refused without detail" and hide
    the one line naming the field.
    """
    for key in ("errors", "warnings"):
        detail = element.get(key)
        if isinstance(detail, list) and detail:
            return _bounded(
                "; ".join(
                    f"{_bounded(item.get('field', '?'))}: {_bounded(item.get('message', '?'))}"
                    for item in detail
                    if isinstance(item, dict)
                )
            )
    error = element.get("error")
    return _bounded(error) if isinstance(error, str) else "no detail in the envelope"


MAX_DETAIL_LENGTH = 200


def _bounded(value: Any) -> str:
    """Provider text, stripped of control characters and capped.

    The same treatment `ChannexAdapter._element_reference` gives an identifier, and for the
    reason measured there: this text reaches `logger`-shaped sinks and the operator's report,
    so a 2000-character value carrying a newline forges an extra line that looks like ours.
    Provider text is attacker-influenceable input going into a line-oriented sink, so it is
    bounded rather than merely typed.

    Control characters first, then the cap: stripping after truncating could leave a partial
    escape sequence at the cut.
    """
    text = "".join(character for character in str(value) if character.isprintable())
    return text.strip()[:MAX_DETAIL_LENGTH]


def _error_detail(response: httpx.Response) -> str:
    """Structured detail for an HTTP-level failure, degrading safely."""
    try:
        body = response.json()
    except ValueError:
        return "unparseable error body"
    if isinstance(body, dict):
        return _envelope_detail(body)
    return "no recognisable error object in the response"


def parse_cost(headers: Any) -> float | int | None:
    """`X-Request-Cost`, or `None` when the provider did not send it (R3.1).

    **Never zero for a missing header.** An unknown cost and a free call lead to different
    budgets, and conflating them is the mistake the whole measurement exists to avoid.

    Parsed as a **float**: the provider bills fractionally (writes measured at `1.1`), and
    `int("1.1")` raises — which would record a fractional cost as "not measured" and make the
    derived budget optimistic. An integral value comes back as `int` so a log reads `1`.
    """
    raw = headers.get(COST_HEADER)
    if raw is None:
        return None
    try:
        cost = float(str(raw).strip())
    except ValueError:
        return None
    return int(cost) if cost.is_integer() else cost


def _log_cost(path: str, response: httpx.Response) -> None:
    """One structured line per request: what it cost and what is left (R3.1).

    Deliberately carries no payload and no credential — path, method, cost, remaining and
    status only. This line is the operator's only view of the credit budget in production.

    **The budget figure is deliberately NOT repeated here.** It lives in
    `docs/beds24-spike.md`, which is where it is measured and regenerated from the committed
    record. This docstring restated it as "8 per cycle" and the number went stale inside the
    very change that corrected it to 10 — which is exactly what R3.4 means by "citando la spec
    en vez de reformular la cifra". A number copied into a comment has no way of learning it
    was superseded.

    Pacing is NOT done here (design D8). The cadence belongs to the scheduler
    (`celery-jobs`); a `sleep` inside a shared adapter hides the cost where nobody measures it.
    """
    remaining = {
        name.lower(): value
        for name, value in response.headers.items()
        if name.lower().startswith("x-") and "limit" in name.lower()
    }
    cost = parse_cost(response.headers)
    logger.info(
        "beds24: GET %s status=%s cost=%s remaining=%s",
        path,
        response.status_code,
        "unknown" if cost is None else cost,
        remaining or "unknown",
    )


def _assert_host_allowed(url: Any) -> None:
    """Exact hostname against a constant allowlist, and `https` (R1.3).

    The hostname is compared **exactly**, never as a substring of the URL:
    `api.beds24.com.evil.tld` contains the real host. And the scheme is checked because the
    credential behind this is an **account** credential — it grants write access over every
    property of the account — so one dropped `s` in a base URL would put it on the wire in
    cleartext.

    **It must be handed the URL that will actually be requested**, which is why both callers
    build the request first and pass `request.url`. Found by the security panel of sections
    3-5, executed rather than argued: this used to receive `f"{BEDS24_BASE_URL}{path}"`, whose
    hostname is `beds24.com` **whatever `path` says** — while `httpx` ignores `base_url`
    entirely when the path is absolute. So `path="https://evil.tld/steal"` passed a guard that
    read `beds24.com` and then sent the 24 h access token to `evil.tld`.

    Nothing reached it that way today: both call sites pass module constants. What made it
    worth fixing rather than noting is that the control was **inoperative while certifying
    itself** — the previous version of this docstring claimed exactly the protection the code
    did not provide, which is what the next author builds on. D7's whole argument for ignoring
    `nextPageLink` rests on this guard being real.
    """
    parts = urlsplit(str(url))
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme != "https":
        raise PmsUnavailableError(
            f"Beds24: refusing scheme {scheme!r} — only https. An account-level credential "
            "must never travel in cleartext."
        )
    if host not in ALLOWED_HOSTS:
        raise PmsUnavailableError(
            f"Beds24: refusing to talk to host {host!r}. "
            f"Allowed: {', '.join(sorted(ALLOWED_HOSTS))}."
        )
