"""Whether `resolve_cookie_secure` derives `Secure` from the request's scheme alone.

Covers the run panel's `sdd-qa` finding on `auth-session-persistence` section 1: no test
exercised `resolve_cookie_secure` directly.

**Scope, after the 2026-09-04 correction to design D2**: the function now reads
`request.url.scheme` only — the manual `X-Forwarded-Proto` header read was removed because
uvicorn's `ProxyHeadersMiddleware` already rewrites `scope["scheme"]` under the same
`--forwarded-allow-ips` trust gate it uses for `scope["client"]` (see
`test_client_ip.py`'s own header, which documents the same gate for `get_client_ip`). So
there is nothing left in this helper for a forwarded-header test to exercise: whether a
given peer's `X-Forwarded-Proto` is honoured is uvicorn's decision, made before this
function ever runs, and it is exercised through the middleware in `test_client_ip.py` and
`test_client_ip_throttle_chain.py`, not here. These two direct cases are the whole
contract of `resolve_cookie_secure` as it stands today.
"""

from starlette.requests import Request

from app.auth.api.dependencies import resolve_cookie_secure


def _scope(scheme: str) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "scheme": scheme,
        "server": ("testserver", 80),
        "query_string": b"",
        "client": ("203.0.113.9", 4242),
    }


async def _receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


def test_direct_https_request_is_secure() -> None:
    request = Request(_scope("https"), _receive)
    assert resolve_cookie_secure(request) is True


def test_plain_http_request_with_no_forwarded_header_is_not_secure() -> None:
    request = Request(_scope("http"), _receive)
    assert resolve_cookie_secure(request) is False
