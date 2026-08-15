"""`X-Content-Type-Options: nosniff` as a property of the application, not of a route (R1, R2).

Before `app/core/response_headers.py` the header existed in exactly ONE response of the
whole backend and the other 64 operations went out without it. So the guard here is
deliberately not "assert the header on the routes somebody remembered": it ENUMERATES the
routes the application has mounted, drives a real request at each one and reports the ones
that come back without it. A route added tomorrow is covered with no edit to this file and
no allowlist — which is the difference from `test_route_authorization.py`, where the
property genuinely does depend on the route.

Three tests here run in RED on purpose (`steering/security.md` rule 13(c), and the pattern
of `test_route_authorization.py::test_the_check_catches_an_endpoint_that_forgets`): an app
without the middleware, an app with the two middlewares in the wrong order, and an app
carrying surface the walk cannot inspect. Without them "the enumeration passes" would be
compatible with the enumeration inspecting nothing.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.routing import Route

from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.http_limits import MaxBodySizeMiddleware
from app.core.response_headers import NoSniffMiddleware
from app.main import create_app
from tests.route_walk import flatten_routes

HEADER = "x-content-type-options"
NOSNIFF = "nosniff"

# Every `{...}` segment becomes this, so a parameterised path can actually be driven. Its
# value never matters: no assertion here depends on the request being answered `200`.
_A_UUID = "00000000-0000-4000-8000-000000000000"


@pytest_asyncio.fixture
async def wired_app(db_session):
    """`create_app()` with the database session pointed at the test database.

    The enumeration drives the anonymous routes too, and several of them reach the database
    before refusing (the guest portal and the webhook receiver authenticate against a row).
    Without the override those requests would raise out of the ASGI transport, which is not
    a header failure but would read as one.
    """
    from app.core.db import get_db_session

    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- 1. the header on responses that do and do not come from a route handler (R1) ---


@pytest.mark.asyncio
async def test_an_ordinary_route_response_carries_the_header() -> None:
    async with _client(create_app()) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers[HEADER] == NOSNIFF


@pytest.mark.asyncio
async def test_a_404_on_a_path_no_route_claims_carries_the_header() -> None:
    """R1.2: the header does not depend on a handler existing."""
    async with _client(create_app()) as client:
        response = await client.get("/api/v1/there-is-no-such-thing")

    assert response.status_code == 404
    assert response.headers[HEADER] == NOSNIFF


@pytest.mark.asyncio
async def test_a_405_on_the_wrong_method_carries_the_header() -> None:
    async with _client(create_app()) as client:
        response = await client.delete("/health")

    assert response.status_code == 405
    assert response.headers[HEADER] == NOSNIFF


@pytest.mark.asyncio
async def test_a_validation_error_envelope_carries_the_header() -> None:
    """The §23 envelope of `RequestValidationError`, which `errors.py` builds itself."""
    app = create_app()

    @app.get("/needs-a-query-parameter")
    async def needs(count: int) -> dict[str, int]:  # pragma: no cover - never reached
        return {"count": count}

    async with _client(app) as client:
        response = await client.get("/needs-a-query-parameter")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers[HEADER] == NOSNIFF


@pytest.mark.asyncio
async def test_an_app_error_envelope_carries_the_header() -> None:
    """The other §23 producer: a domain error mapped by the `AppError` handler."""
    app = create_app()

    @app.get("/raises-a-domain-error")
    async def raises() -> None:
        raise NotFoundError("nothing here")

    async with _client(app) as client:
        response = await client.get("/raises-a-domain-error")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.headers[HEADER] == NOSNIFF


@pytest.mark.asyncio
async def test_the_413_the_body_size_middleware_builds_itself_carries_the_header() -> None:
    """R1.3, and the test that holds the mounting order of D2.

    `MaxBodySizeMiddleware._refuse` composes this response — status, headers and body —
    and sends it without passing through any route or handler. The only way it can carry
    the header is if `NoSniffMiddleware` is mounted OUTSIDE it, which is what mounting it
    last achieves. Swap the two `add_middleware` calls in `app/main.py` and this is the
    test that falls.
    """
    async with _client(create_app()) as client:
        response = await client.post(
            "/api/v1/auth/login",
            content=b"x" * (settings.request_max_bytes + 1),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert response.headers[HEADER] == NOSNIFF


@pytest.mark.asyncio
async def test_the_route_that_stamps_it_itself_emits_exactly_one_value(wired_app) -> None:
    """R1.4. `GET /cleaning-photos/{id}` sets the header in `photos_router._respond` and
    keeps doing so (design D5), so this is the one response where a middleware that
    appended rather than wrote would emit it twice.

    Two things about the request are load-bearing, and the first version of this test got
    the second one wrong:

    * `get_list` and not `headers[...]` — reading the header by key collapses two values
      into one comma-joined string, so the naive assertion passes vacuously on a duplicate.
    * **`exp` and `sig` have to be present**, wrong but present. They are required query
      parameters, so omitting them makes FastAPI answer `422` in its own validation, before
      `serve_cleaning_photo` and therefore before `_respond` — the only line in the
      application that could produce the duplicate. Measured on that first version: swapping
      the middleware's `__setitem__` for `append` left all twelve tests in this file green.
      Present-and-wrong reaches the use case, which cannot resolve the photo and refuses
      through `_respond`, which is the path that stamps.

    Hence the `403` assertion below: it is not incidental, it is what pins that this request
    still reaches the router. A `422` here means the test went vacuous again.
    """
    async with _client(wired_app) as client:
        response = await client.get(
            f"/api/v1/cleaning-photos/{_A_UUID}", params={"exp": 0, "sig": "deadbeef"}
        )

    assert response.status_code == 403, (
        "this request must reach `photos_router._respond`; a 422 means it stopped at "
        "FastAPI's query validation and the assertion below proves nothing"
    )

    values = response.headers.get_list(HEADER)

    assert values == [NOSNIFF], f"expected exactly one value, got {values}"


@pytest.mark.asyncio
async def test_a_route_cannot_keep_a_value_that_contradicts_the_posture() -> None:
    """The other half of R1.4 — "sin duplicar **ni contradecir** el que la ruta puso".

    The duplication half is covered by the photo route above, but no route in this backend
    sets a *wrong* value, so on every live path `__setitem__` and `setdefault` behave
    identically and a regression from one to the other goes unnoticed. Measured: swapping
    them left all twelve other tests in this file green. This is the missing assertion, and
    it needs a route built to misbehave, because there is deliberately none in production.

    `setdefault` would keep the route's value; `append` would emit both. D4 rejects both,
    and this is the test that says so.
    """
    from fastapi.responses import JSONResponse

    app = FastAPI()
    app.add_middleware(NoSniffMiddleware)

    @app.get("/sets-the-header-wrong")
    async def wrong() -> JSONResponse:
        response = JSONResponse({"ok": True})
        response.headers["X-Content-Type-Options"] = "please-sniff-me"
        return response

    async with _client(app) as client:
        response = await client.get("/sets-the-header-wrong")

    assert response.headers.get_list(HEADER) == [NOSNIFF], (
        "the application-wide posture must overwrite what a route put there, not defer to "
        "it and not sit next to it"
    )


@pytest.mark.asyncio
async def test_the_named_residue_stays_what_d3_accepted() -> None:
    """D3 accepts one uncovered response — the `500` of `ServerErrorMiddleware`, which sits
    outside every user middleware — on the grounds that its body is a compile-time constant
    with no byte of client input in it.

    That grounds holds only while `debug` is off. With `debug` set, starlette answers the same
    `500` with an HTML traceback built from the request and the exception, so the one response
    that escapes the stamp would start carrying client-derived bytes and the accepted residue
    would silently stop being the one D3 accepted.

    Nothing else in the suite pins this, so it is pinned here: wiring `FastAPI(debug=...)` in
    `create_app()` has to fail this test and force a revisit of D3 rather than pass quietly.
    """
    assert create_app().debug is False


# --- 2. the enumeration (R2) ---


async def _responses_without_nosniff(app: FastAPI) -> list[str]:
    """Every mounted surface driven once, reported when it answers without the header.

    Deliberately WITHOUT an allowlist of any kind. The status code is irrelevant here — a
    `401`, a `404`, a `422` and a `200` all have to carry the header — so unlike the
    authorisation guard there is nothing legitimate to exempt, and a route added later is
    covered without touching this file.

    Anything the walk hands back that cannot be driven (a websocket, a mount) comes back
    named as `UNINSPECTABLE` rather than skipped: silently dropping surface would be a
    guard passing on a subset it never declared.
    """
    found, other = flatten_routes(app)
    naked: list[str] = []

    async with _client(app) as client:
        for path, route in found:
            naked.extend(await _drive(client, path, route.methods or {"GET"}))
        for path, route in other:
            methods = getattr(route, "methods", None)
            if isinstance(route, Route) and methods:
                naked.extend(await _drive(client, path, methods))
            else:
                naked.append(f"UNINSPECTABLE {type(route).__name__} {path}")

    return sorted(naked)


async def _drive(client: AsyncClient, path: str, methods) -> list[str]:
    """One request per verb, with no credentials and no body.

    HEAD is skipped: starlette and FastAPI add it implicitly next to GET, so it is never a
    verb anybody chose — the same normalisation `test_route_authorization.py` makes.
    """
    concrete = _concrete(path)
    missing: list[str] = []
    for method in sorted(verb for verb in methods if verb != "HEAD"):
        response = await client.request(method, concrete)
        if response.headers.get(HEADER, "").lower() != NOSNIFF:
            missing.append(f"{method} {path}")
    return missing


def _concrete(path: str) -> str:
    return "/".join(
        _A_UUID if segment.startswith("{") and segment.endswith("}") else segment
        for segment in path.split("/")
    )


@pytest.mark.asyncio
async def test_the_enumeration_actually_reaches_the_mounted_routes(wired_app) -> None:
    """Anti-vacuity, and it is not decorative: `route_walk.py` records that this project
    shipped two guards which passed while inspecting an empty list."""
    found, _ = flatten_routes(wired_app)
    paths = {path for path, _ in found}

    assert {"/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/cleaning-tasks"} <= paths


@pytest.mark.asyncio
async def test_no_mounted_surface_answers_without_the_header(wired_app) -> None:
    naked = await _responses_without_nosniff(wired_app)

    assert naked == [], (
        f"these responses came back without `{HEADER}: {NOSNIFF}`: {naked}. The header is "
        "stamped by `NoSniffMiddleware` for the whole application, so this failing means "
        "either the middleware is unmounted or something answers outside the stack."
    )


@pytest.mark.asyncio
async def test_the_check_catches_an_app_that_forgets_the_middleware() -> None:
    """The mechanism in red (rule 13(c)). Since the header is global there is no *route*
    that can lose it — what can be built is an application without the middleware."""
    naked_app = FastAPI()

    @naked_app.get("/forgot-the-header")
    async def forgotten() -> dict[str, bool]:
        return {"ok": True}

    # The four documentation routes FastAPI mounts by itself are in the list too, and that
    # is the point rather than noise: they are plain starlette `Route`s, so an enumeration
    # that only looked at `APIRoute`s would report this app clean apart from one line.
    assert await _responses_without_nosniff(naked_app) == [
        "GET /docs",
        "GET /docs/oauth2-redirect",
        "GET /forgot-the-header",
        "GET /openapi.json",
        "GET /redoc",
    ]


@pytest.mark.asyncio
async def test_the_check_catches_the_middlewares_in_the_wrong_order() -> None:
    """D2 in red: mounted first, `NoSniffMiddleware` is INNERMOST and never sees the `413`.

    Without this test, "it is mounted last, and that is the mechanism" is a sentence in a
    comment. With it, swapping the two calls in `app/main.py` is a failing suite.
    """
    limit = 32

    def _app(nosniff_first: bool) -> FastAPI:
        app = FastAPI()

        @app.post("/api/v1/thing")
        async def thing() -> dict[str, bool]:  # pragma: no cover - body never gets in
            return {"ok": True}

        def _add_nosniff() -> None:
            app.add_middleware(NoSniffMiddleware)

        def _add_body_ceiling() -> None:
            app.add_middleware(
                MaxBodySizeMiddleware,
                path_prefixes=("/api/v1",),
                max_bytes_provider=lambda _path: limit,
            )

        if nosniff_first:
            _add_nosniff()
            _add_body_ceiling()
        else:
            _add_body_ceiling()
            _add_nosniff()
        return app

    async def _oversized(app: FastAPI):
        async with _client(app) as client:
            return await client.post("/api/v1/thing", content=b"x" * (limit + 1))

    wrong = await _oversized(_app(nosniff_first=True))
    right = await _oversized(_app(nosniff_first=False))

    assert wrong.status_code == 413
    assert HEADER not in wrong.headers, (
        "the wrong order was expected to leave the 413 naked; if this passes, the mounting "
        "order stopped being the mechanism and D2 needs rewriting"
    )
    assert right.status_code == 413
    assert right.headers[HEADER] == NOSNIFF


@pytest.mark.asyncio
async def test_the_check_catches_surface_it_cannot_inspect() -> None:
    """R2.4: a websocket and a mount are real surface the walk cannot drive. Skipping them
    would be a guard reporting green over something it never looked at."""
    from starlette.applications import Starlette

    app = FastAPI()
    app.add_middleware(NoSniffMiddleware)

    @app.get("/ordinary")
    async def ordinary() -> dict[str, bool]:
        return {"ok": True}

    @app.websocket("/ws")
    async def socket(websocket) -> None:  # pragma: no cover - never connected to
        await websocket.accept()

    app.mount("/static", Starlette())

    naked = await _responses_without_nosniff(app)

    # Exactly the two, and nothing else: the ordinary route and FastAPI's own documentation
    # routes are stamped, so the report is not simply everything failing at once.
    assert naked == ["UNINSPECTABLE APIWebSocketRoute /ws", "UNINSPECTABLE Mount /static"]
