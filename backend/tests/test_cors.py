"""CORS posture for dev and prod (`auth-session-persistence` R7, design D1).

Hits the anonymous, DB-free `/health` route so this file needs no database fixture —
CORSMiddleware processes the response headers of an ordinary (non-preflight) request the
same way it does a preflight one, and that is enough to observe R7.1.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Scope

from app.main import create_app

pytestmark = pytest.mark.asyncio

ALLOWED_ORIGIN = "http://localhost:3000"
DISALLOWED_ORIGIN = "https://evil.example.com"
# `PORT_OFFSET`-style dev origin (`sdd/project.md:96-100`): proves the regex allows an
# arbitrary dev port, not just the literal default 3000.
PORT_OFFSET_ORIGIN = "http://localhost:3037"
# A suffix/subdomain trick on the allowed prod hostname: if the regex were a substring
# match instead of anchored/`fullmatch`, this origin would wrongly be reflected too.
SUFFIX_TRICK_ORIGIN = "https://autohostai.digitalsec.work.evil.com"


@pytest.fixture
def api_transport():
    return ASGITransport(app=create_app())


async def test_allowlisted_origin_gets_credentials_and_reflected_origin(api_transport):
    async with AsyncClient(transport=api_transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    # R7.1: the exact origin is reflected, never `*` — a static `allow_origins` list would
    # force `*` semantics once `allow_credentials=True`, which browsers reject.
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


async def test_non_allowlisted_origin_gets_no_allow_origin_header(api_transport):
    """A non-allowlisted `Origin` never gets `Access-Control-Allow-Origin` reflected back.

    That is the header a browser's CORS check actually keys on: without a matching
    `Access-Control-Allow-Origin`, the response is opaque to page script regardless of any
    other CORS header present — `Access-Control-Allow-Credentials` included, which
    Starlette's `CORSMiddleware` sets unconditionally on every "simple" response once
    `allow_credentials=True`, allowed origin or not (its own `send()` applies
    `simple_headers` before checking `is_allowed_origin`). Asserting it is absent here
    would pin an implementation detail with no security meaning, not R7.1.
    """
    async with AsyncClient(transport=api_transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"Origin": DISALLOWED_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_prod_origin_is_also_allowlisted(api_transport):
    async with AsyncClient(transport=api_transport, base_url="http://test") as client:
        response = await client.get(
            "/health", headers={"Origin": "https://autohostai.digitalsec.work"}
        )

    assert response.headers.get("access-control-allow-origin") == (
        "https://autohostai.digitalsec.work"
    )
    assert response.headers.get("access-control-allow-credentials") == "true"


async def test_port_offset_style_dev_origin_is_reflected(api_transport):
    """`make up PORT_OFFSET=<n>` (`sdd/project.md:96-100`) shifts the frontend's dev port on
    every worktree; the regex has to allow any port on `localhost`, not just 3000."""
    async with AsyncClient(transport=api_transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"Origin": PORT_OFFSET_ORIGIN})

    assert response.headers.get("access-control-allow-origin") == PORT_OFFSET_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


async def test_suffix_trick_on_allowed_hostname_is_rejected(api_transport):
    """A subdomain/suffix trick on the allowed prod hostname must NOT match: the regex has
    to be anchored (`$`) and matched with `re.fullmatch` (Starlette's `CORSMiddleware`
    default), not treated as a substring."""
    async with AsyncClient(transport=api_transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"Origin": SUFFIX_TRICK_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_oversized_cross_origin_body_gets_413_with_cors_headers():
    """Concrete proof of the mounting-order fix (`main.py`'s CORS-mount comment, **corrected
    2026-09-04**): `MaxBodySizeMiddleware._refuse()` answers a `413` via the raw ASGI `send`
    without ever calling `self._app(...)`, so only a CORSMiddleware mounted OUTERMOST — not
    innermost — gets a chance to decorate that self-generated response with
    `Access-Control-Allow-*` headers. Without the fix this response carries none.

    Drives the ASGI app directly (bypassing `httpx`) with a declared `Content-Length` above
    `settings.request_max_bytes`, on an anonymous `/api/v1/auth/login` route: the
    middleware's `Content-Length` shortcut refuses the request before reading any body and
    before any router/DB code runs, so no oversized payload is actually sent and no database
    fixture is needed — same rationale as this file's `/health`-only tests.
    """
    app = create_app()
    sent: list[Message] = []

    async def receive() -> Message:  # pragma: no cover - the shortcut never calls this
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "root_path": "",
        "path": "/api/v1/auth/login",
        "raw_path": b"/api/v1/auth/login",
        "query_string": b"",
        "headers": [
            (b"origin", ALLOWED_ORIGIN.encode()),
            (b"content-type", b"application/json"),
            # Comfortably above `settings.request_max_bytes` (1 MiB default) so the
            # declared-`Content-Length` shortcut in `MaxBodySizeMiddleware.__call__` fires.
            (b"content-length", str(5 * 1024 * 1024).encode()),
        ],
        "client": ("203.0.113.9", 4242),
        "server": ("testserver", 80),
    }

    await app(scope, receive, send)

    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 413
    headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    assert headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert headers.get("access-control-allow-credentials") == "true"
