"""R3.2 and R1.7 on the receiving route, satisfied by REUSE (`reservations-webhooks` D5).

**No production code backs this file, and that is the finding it records.** The first draft of
D5 described a body ceiling to build inside the endpoint, after authentication. Both halves were
wrong: `MaxBodySizeMiddleware` (`app/core/http_limits.py`, change `api-ingress-routing` D11)
already exists, already covers all of `/api/v1/`, and runs **before routing** — which is strictly
better than what the design asked for, because "before routing" implies "before authentication",
"before a dependency" and "before a database session".

So what is left for this change is the evidence, on its own route:

* an oversized body is refused with `413` and the PRD §23 envelope;
* **without a valid token**, which is the whole point — R1.7 asks that an unauthenticated caller's
  large body never be materialised, and a ceiling that ran after authentication would have to read
  the body to find out it should not have;
* leaving **no row** in `webhook_events`.

The tests deliberately use a route token that authenticates nothing. They pass today, before the
receiving router of task 2.5 exists, and that is not a weakness of the test — it is the property
being asserted. The ceiling precedes the route itself, so an oversized body is refused even where
there is nothing to route to. When 2.5 lands they keep passing unchanged, which is what makes them
a regression guard rather than a description.

**One half of D5's claim cannot be tested until 2.5, and the reason is worth writing down** —
measured here rather than assumed, since D5 asserted the whole of it. `MaxBodySizeMiddleware` has
two paths: a declared `Content-Length` over the limit is refused immediately, while an absent,
negative or non-numeric one falls through to counting the stream. The counter only advances when
something **reads** the body, and Starlette answers `404` for an unmatched route without ever
calling `receive()`. So a lying `Content-Length` against a route that does not exist yields `404`,
not `413` — harmless (an unread body is not materialised, which is what R1.7 protects), but it
means the stream-counting half is only observable once there is a route to read. Its test belongs
to task 2.5 and is written there.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.main import create_app

TOO_LARGE = 413

# Shaped like the real thing and valid for nothing: `secrets.token_urlsafe(32)` output is what a
# genuine token looks like, and this one was never minted, so no row can match its hash.
UNAUTHENTICATED_ROUTE = f"/api/v1/webhooks/beds24/{uuid.uuid4().hex}{uuid.uuid4().hex}"


async def _post(body: bytes):
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            UNAUTHENTICATED_ROUTE, content=body, headers={"content-type": "application/json"}
        )


@pytest.mark.asyncio
async def test_an_oversized_webhook_body_is_refused_with_the_envelope() -> None:
    response = await _post(b"x" * (settings.request_max_bytes + 1))

    assert response.status_code == TOO_LARGE
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_the_refusal_needs_no_valid_token(db_session) -> None:
    """R1.7: rejected BEFORE the body is read, so authentication never enters into it.

    If this ever came back as `404` — design D4's answer for a token that authenticates nothing —
    the body would have been consumed to reach the routing layer first, and the amplifier D11
    closes would be open again on this route.
    """
    response = await _post(b"x" * (settings.request_max_bytes + 1))

    assert response.status_code == TOO_LARGE

    stored = (
        await db_session.execute(text("SELECT count(*) FROM webhook_events"))
    ).scalar_one()
    assert stored == 0


@pytest.mark.asyncio
async def test_the_ceiling_is_the_shared_one_and_not_a_third_knob() -> None:
    """D5: no `webhook_max_body_bytes`.

    A third dial beside `REQUEST_MAX_BYTES` and `CSV_IMPORT_MAX_BYTES` would be one nobody tunes
    and a second home for the same fact. If a provider ever proves to send larger bodies, the
    repair is another branch in the per-path provider of `app/main.py`.
    """
    assert not hasattr(settings, "webhook_max_body_bytes")
