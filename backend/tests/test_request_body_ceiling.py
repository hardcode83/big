"""The body ceiling as the REAL application wires it (change `api-ingress-routing`, D11).

`test_http_limits.py` covers `MaxBodySizeMiddleware` as a unit, with a synthetic per-path
provider. That is necessary and it was not sufficient: a security review measured that
reverting `app/main.py` to the old narrow `path_prefixes=("/api/v1/integrations/",)` broke
**nothing** — 50 tests still passed — which would silently restore the anonymous memory
amplifier D11 exists to close, while `spec-deltas.md` asserts to the living spec that the
ceiling covers all of `/api/v1/`.

So these tests drive `create_app()` and assert the wiring, not the mechanism:
  * an anonymous NON-`integrations` endpoint refuses a body over `REQUEST_MAX_BYTES`;
  * `/api/v1/integrations/` still accepts bodies far above that, on its own larger ceiling;
  * and the refusal happens BEFORE authentication, which is the property that makes it a
    mitigation rather than a courtesy — FastAPI reads the body before dependencies run.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import create_app

# Anonymous and outside `/api/v1/integrations/`: the shape the amplifier used.
ANONYMOUS_ENDPOINT = "/api/v1/auth/login"
UPLOAD_ENDPOINT = "/api/v1/integrations/pms/import-csv"

TOO_LARGE = 413


async def _post(path: str, body: bytes, content_type: str = "application/json"):
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            path, content=body, headers={"content-type": content_type}
        )


@pytest.mark.asyncio
async def test_an_oversized_body_on_an_anonymous_endpoint_is_refused() -> None:
    response = await _post(
        ANONYMOUS_ENDPOINT, b"x" * (settings.request_max_bytes + 1)
    )

    assert response.status_code == TOO_LARGE
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_the_refusal_precedes_authentication() -> None:
    """What makes it a mitigation: no credential is needed to be refused, and no body is
    read. If this ever returned 401 or 422 instead, the body was consumed first."""
    response = await _post(
        "/api/v1/users", b"x" * (settings.request_max_bytes + 1)
    )

    assert response.status_code == TOO_LARGE


@pytest.mark.asyncio
async def test_a_body_within_the_ceiling_reaches_the_endpoint() -> None:
    """Control: the ceiling must not be refusing everything. A 401/422 here means the
    request got past the middleware and into the application."""
    response = await _post(ANONYMOUS_ENDPOINT, b'{"email":"a@b.c","password":"x"}')

    assert response.status_code != TOO_LARGE


@pytest.mark.asyncio
async def test_the_upload_prefix_keeps_its_own_larger_ceiling() -> None:
    """The per-path half of D11: a body far above the general ceiling is NOT refused on the
    upload prefix, because `CSV_IMPORT_MAX_BYTES` governs there.

    This is the assertion that fails if someone collapses the two limits into one.
    """
    assert settings.csv_import_max_bytes > settings.request_max_bytes

    response = await _post(
        UPLOAD_ENDPOINT, b"x" * (settings.request_max_bytes + 1), "text/csv"
    )

    assert response.status_code != TOO_LARGE


@pytest.mark.asyncio
async def test_the_upload_prefix_still_has_a_ceiling() -> None:
    response = await _post(
        UPLOAD_ENDPOINT, b"x" * (settings.csv_import_max_bytes + 1), "text/csv"
    )

    assert response.status_code == TOO_LARGE


@pytest.mark.asyncio
async def test_the_ceiling_covers_more_than_the_upload_prefix() -> None:
    """The regression guard, stated as the thing that must stay true.

    A reviewer demonstrated that narrowing `path_prefixes` back to the upload path alone
    left every test green. This one would fail.
    """
    app = create_app()
    covered = [
        prefix
        for middleware in app.user_middleware
        for prefix in getattr(middleware, "kwargs", {}).get("path_prefixes", ())
    ]

    assert covered, "no body-size middleware is wired at all"
    assert "/api/v1/" in covered or "/api/v1" in covered, (
        f"the body ceiling covers only {covered}; it must cover all of /api/v1/"
    )
