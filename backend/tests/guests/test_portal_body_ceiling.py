"""R2.4 on the guest portal, satisfied by REUSE (design D7).

**No production code backs this file, and that is the finding it records** — the same one
`tests/integrations/test_webhook_body_ceiling.py` recorded for the webhook receiver.
`MaxBodySizeMiddleware` (`app/core/http_limits.py`) already covers all of `/api/v1/`, already
applies `settings.request_max_bytes` to any path with no wider branch of its own, and runs
**before routing** — which is strictly better than a check inside the endpoint, because
"before routing" implies "before the authoriser", "before the throttle" and "before a database
session". D7 says so and asks for no new middleware and no new setting; what is left for this
change is the evidence on its own routes.

**Why the portal needs that evidence separately from the webhooks.** The receiver is reached
by a provider we onboarded; the portal's routes are reached by anyone with the URL, and the
token in the path is the entire credential. So an oversized body here is the cheapest possible
anonymous memory amplifier — the measured one behind `api-ingress-routing` D11 took the
container from 195 MiB to 1.016 GiB with a single `POST`. The ceiling is what makes the surface
safe to expose, so it is pinned where the surface lives.

The stream-counting half **is** observable here, unlike in the webhook file. That file could
only test the declared-`Content-Length` path, because Starlette answers `404` for an unmatched
route without ever calling `receive()`, and at the time there was no route to match. There is
one now: `POST /api/v1/guest/checkin/{token}` reads its body to build `SubmitCheckinRequest`,
so a chunked upload with no `Content-Length` at all reaches the counter and is aborted mid
flight. That is the `ClientDisconnect` half of task 6.7.
"""

import uuid
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.audit.infrastructure.models import AuditLogModel
from app.core.config import settings
from app.core.db import get_db_session
from app.guests.api.portal_dependencies import get_guest_portal_throttle
from app.guests.domain.enums import GuestDocumentStatus
from app.main import create_app
from tests.auth.conftest import tenant_a  # noqa: F401
from tests.guests.test_portal_api import CHECKIN, _AllowAll, _stay, _token

TOO_LARGE = 413

#: Two hex uuids, so it is shaped like a real token and authenticates nothing.
UNAUTHENTICATED = f"/api/v1/guest/checkin/{uuid.uuid4().hex}{uuid.uuid4().hex}"


def _oversized() -> bytes:
    return b"x" * (settings.request_max_bytes + 1)


async def _chunks() -> AsyncIterator[bytes]:
    """An oversized body with **no** `Content-Length`, so only the counter can stop it."""
    for _ in range(9):
        yield b"x" * (settings.request_max_bytes // 8)


def _client(db_session=None) -> AsyncClient:
    """A client on the real middleware stack, with the throttle faked out.

    The fake is not about this file's subject — the ceiling runs before the throttle is
    consulted, so it would be reached either way. It is here because `get_redis()` caches one
    client in a module global (`app/core/redis.py`), and a test that builds it inside its own
    event loop leaves that loop's client behind for whatever runs next. Measured: without this
    override, `tests/guests` poisons the global and
    `tests/integrations/test_webhook_receiver_api.py::test_the_router_drives_the_real_throttle`
    dies with "Event loop is closed" — an order-dependent failure in a file this change never
    touched. Noted as a candidate in `proposal.md`; the local repair is not to reach for the
    real Redis from a route test that does not need it.
    """
    app = create_app()
    app.dependency_overrides[get_guest_portal_throttle] = _AllowAll
    if db_session is not None:

        async def _session_override():
            yield db_session

        app.dependency_overrides[get_db_session] = _session_override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_an_oversized_portal_body_is_refused_with_the_envelope() -> None:
    async with _client() as client:
        response = await client.post(
            UNAUTHENTICATED,
            content=_oversized(),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == TOO_LARGE
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_the_refusal_needs_no_valid_token(db_session) -> None:
    """R2.4: refused before the body is read, so authorisation never enters into it.

    If this ever came back as the portal's constant `404`, the body would have been consumed
    in order to reach the router at all — and the amplifier would be open on the one surface
    of this system that anybody can reach.
    """
    async with _client(db_session) as client:
        response = await client.post(
            UNAUTHENTICATED,
            content=_oversized(),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == TOO_LARGE
    assert (await db_session.execute(select(AuditLogModel))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_truncated_stream_is_refused_before_anything_is_written(
    db_session, tenant_a
) -> None:
    """The counting half of the ceiling, against a token that would otherwise succeed.

    A chunked upload declares no `Content-Length`, so the first check cannot fire; the
    counter aborts the stream past the limit and the middleware answers `413`. Two things
    make this more than a status assertion: the token is **live**, so a body that got through
    would have been parsed and acted upon, and the `413` is not the `422` a malformed body
    would earn — which is what shows the body was never parsed at all.
    """
    reservation, guest = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    async with _client(db_session) as client:
        response = await client.post(
            f"/api/v1/guest/checkin/{token}",
            content=_chunks(),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == TOO_LARGE
    await db_session.refresh(guest)
    assert guest.document_number_encrypted is None
    assert guest.document_status is GuestDocumentStatus.NOT_PROVIDED
    assert (await db_session.execute(select(AuditLogModel))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_body_within_the_ceiling_still_reaches_the_route(db_session, tenant_a) -> None:
    """The other side of the boundary, so the three tests above cannot pass by refusing
    everything. A real check-in is a few hundred bytes; the ceiling is 1 MiB."""
    reservation, _ = await _stay(db_session, tenant_a)
    token = await _token(db_session, tenant_a, reservation)

    async with _client(db_session) as client:
        response = await client.post(f"/api/v1/guest/checkin/{token}", json=CHECKIN)

    assert response.status_code != TOO_LARGE


@pytest.mark.asyncio
async def test_the_ceiling_is_the_shared_one_and_not_a_fourth_knob() -> None:
    """D7: no `guest_portal_max_body_bytes`.

    A dial beside `REQUEST_MAX_BYTES`, `JSON_BODY_MAX_BYTES` and `CSV_IMPORT_MAX_BYTES` would
    be one nobody tunes and a fourth home for the same fact. The portal's bodies are six small
    fields and a short free-text description; if that ever stops being true, the repair is
    another branch in the per-path provider of `app/main.py`.
    """
    assert not hasattr(settings, "guest_portal_max_body_bytes")


def test_no_portal_module_reimplements_the_ceiling() -> None:
    """D7 again, structurally: the router's docstring claims the middleware does this job.

    A `request_max_bytes` read inside `api/` would mean the claim had quietly stopped being
    true — and the check would run after the body was already in memory, which is the exact
    failure `app/core/http_limits.py` exists to prevent. Naming the middleware in prose is
    the opposite of that and is why the check is on the import, not on the word.
    """
    from pathlib import Path

    portal = Path(__file__).resolve().parents[2] / "app" / "guests" / "api"
    for module in ("portal_router.py", "portal_schemas.py", "portal_dependencies.py"):
        source = (portal / module).read_text(encoding="utf-8")
        assert "settings.request_max_bytes" not in source
        assert "from app.core.http_limits import" not in source
