"""The receiving endpoint over HTTP (`reservations-webhooks` R1.1, R1.7, R3.1, R3.2; D4, D5).

What is asserted here is the **transport** half only — status codes, the uniform `404`, the empty
`202`, and the two rate limits. The authentication rule itself is asserted in
`test_webhook_receipt.py` against the use case, without FastAPI, which is the split D5 requires.

The throttle is overridden with a permissive double in most tests: the limits have their own file
(`test_webhook_throttle.py`) and letting the real Redis counters leak between tests here would
make failures depend on execution order.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.auth.api.dependencies import get_client_ip
from app.core.crypto import encrypt
from app.core.db import get_db_session
from app.integrations.api.dependencies import get_webhook_throttle
from app.integrations.domain.entities import WebhookEndpoint
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.webhook_auth import (
    generate_webhook_token,
    hash_webhook_token,
)
from app.integrations.infrastructure.repositories import (
    SqlAlchemyWebhookEndpointRepository,
)
from app.main import create_app

HEADER_NAME = "X-Beds24-Secret"
SECRET = "paste-me-into-the-panel"
BODY = {"event": "booking.modified", "bookingId": "42"}


class _AllowAll:
    """Every request permitted, nothing counted."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    async def probe_allowed(self, client_ip: str) -> bool:
        return True

    async def delivery_allowed(self, token_hash: str) -> bool:
        return True

    async def record_failed_attempt(self, client_ip: str) -> None:
        self.failures.append(client_ip)


class _RefuseDeliveries(_AllowAll):
    async def delivery_allowed(self, token_hash: str) -> bool:
        return False


class _RefuseProbes(_AllowAll):
    async def probe_allowed(self, client_ip: str) -> bool:
        return False


@pytest.fixture
def throttle() -> _AllowAll:
    return _AllowAll()


@pytest.fixture
def client_factory(db_session, throttle):
    def build(override=None):
        app = create_app()

        async def _session_override():
            yield db_session

        app.dependency_overrides[get_db_session] = _session_override
        app.dependency_overrides[get_webhook_throttle] = lambda: override or throttle
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return build


async def _provision(db_session, tenant) -> str:
    token = generate_webhook_token()
    await SqlAlchemyWebhookEndpointRepository(db_session).upsert(
        tenant.id,
        WebhookEndpoint(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            provider=PMSProvider.BEDS24,
            token_hash=hash_webhook_token(token),
            header_name=HEADER_NAME,
            header_secret=encrypt(SECRET),
        ),
    )
    await db_session.flush()
    return token


def _url(token: str, provider: str = "beds24") -> str:
    return f"/api/v1/webhooks/{provider}/{token}"


# --- The accepted notice (R1.1) ---


@pytest.mark.asyncio
async def test_a_valid_notice_is_accepted_with_an_empty_202(
    db_session, tenant_a, client_factory
) -> None:
    token = await _provision(db_session, tenant_a)

    async with client_factory() as client:
        response = await client.post(_url(token), json=BODY, headers={HEADER_NAME: SECRET})

    assert response.status_code == 202
    # "sin cuerpo de negocio" (R1.1): anything echoed back is a signal an anonymous caller reads.
    assert response.content == b""

    queued = (
        await db_session.execute(
            text("SELECT count(*) FROM webhook_events WHERE tenant_id = :t"),
            {"t": str(tenant_a.id)},
        )
    ).scalar_one()
    assert queued == 1


# --- Every failure is the same 404 (D4) ---


@pytest.mark.asyncio
async def test_the_four_failures_are_byte_for_byte_identical(
    db_session, tenant_a, client_factory
) -> None:
    """Not just "all 404" — the same status AND the same body.

    A `404` whose message differs by a word is still an oracle, and the four raises live in
    different branches, so nothing but comparing the rendered responses catches a drift.
    """
    good = await _provision(db_session, tenant_a)

    async with client_factory() as client:
        answers = [
            await client.post(
                _url(generate_webhook_token()), json=BODY, headers={HEADER_NAME: SECRET}
            ),
            await client.post(
                _url(good, provider="octorate"), json=BODY, headers={HEADER_NAME: SECRET}
            ),
            await client.post(_url(good), json=BODY),
            await client.post(_url(good), json=BODY, headers={HEADER_NAME: "wrong"}),
        ]

    assert {response.status_code for response in answers} == {404}
    assert len({response.text for response in answers}) == 1
    assert answers[0].json()["error"]["code"] == "NOT_FOUND"

    stored = (
        await db_session.execute(text("SELECT count(*) FROM webhook_events"))
    ).scalar_one()
    assert stored == 0


@pytest.mark.asyncio
async def test_a_failure_never_answers_401(db_session, tenant_a, client_factory) -> None:
    """D4 rejects `401` with `WWW-Authenticate`: correct in HTTP, an oracle in practice."""
    async with client_factory() as client:
        response = await client.post(
            _url(generate_webhook_token()), json=BODY, headers={HEADER_NAME: SECRET}
        )

    assert response.status_code != 401
    assert "www-authenticate" not in {key.lower() for key in response.headers}


# --- A body that is not what it claims ---


@pytest.mark.asyncio
async def test_malformed_json_from_an_unauthenticated_caller_is_still_a_404(
    db_session, tenant_a, client_factory
) -> None:
    """A `422` here would confirm the caller got past the route token."""
    async with client_factory() as client:
        response = await client.post(
            _url(generate_webhook_token()),
            content=b"{not json at all",
            headers={HEADER_NAME: SECRET, "content-type": "application/json"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_malformed_json_from_an_authenticated_caller_is_recorded_not_dropped(
    db_session, tenant_a, client_factory
) -> None:
    """A real notice with a broken body stays visible for diagnosis.

    Dropping it would lose the one signal that a provider changed its format.
    """
    token = await _provision(db_session, tenant_a)

    async with client_factory() as client:
        response = await client.post(
            _url(token),
            content=b"{not json at all",
            headers={HEADER_NAME: SECRET, "content-type": "application/json"},
        )

    assert response.status_code == 202
    stored = (
        await db_session.execute(text("SELECT payload FROM webhook_events"))
    ).scalar_one()
    assert stored == {}


# --- The two limits, and which one counts what (R3.1, R3.4, D6) ---


@pytest.mark.asyncio
async def test_a_throttled_delivery_is_429_and_writes_nothing(
    db_session, tenant_a, client_factory
) -> None:
    token = await _provision(db_session, tenant_a)

    async with client_factory(_RefuseDeliveries()) as client:
        response = await client.post(_url(token), json=BODY, headers={HEADER_NAME: SECRET})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    stored = (
        await db_session.execute(text("SELECT count(*) FROM webhook_events"))
    ).scalar_one()
    assert stored == 0


@pytest.mark.asyncio
async def test_a_throttled_prober_is_refused_before_any_lookup(
    db_session, tenant_a, client_factory
) -> None:
    """The probe limit has to bite before the work a guesser is trying to provoke."""
    token = await _provision(db_session, tenant_a)

    async with client_factory(_RefuseProbes()) as client:
        response = await client.post(_url(token), json=BODY, headers={HEADER_NAME: SECRET})

    assert response.status_code == 429


@pytest.mark.asyncio
async def test_only_a_failed_attempt_is_counted_against_the_ip(
    db_session, tenant_a, client_factory, throttle
) -> None:
    """**The test D6 exists for**, at the transport level.

    A successful delivery must not touch the probe counter — otherwise a provider's ordinary
    traffic, which arrives from a handful of addresses on behalf of many tenants, would exhaust
    the strict per-IP limit and take every one of those tenants down at once.
    """
    token = await _provision(db_session, tenant_a)

    async with client_factory() as client:
        await client.post(_url(token), json=BODY, headers={HEADER_NAME: SECRET})
        assert throttle.failures == []

        await client.post(_url(token), json=BODY, headers={HEADER_NAME: "wrong"})

    assert len(throttle.failures) == 1


# --- The order of the checks IS the defence (security panel, section 2) ---


class _CountingThrottle(_AllowAll):
    """Records what was charged, so the ORDER of the charges can be asserted."""

    def __init__(self) -> None:
        super().__init__()
        self.deliveries: list[str] = []

    async def delivery_allowed(self, token_hash: str) -> bool:
        self.deliveries.append(token_hash)
        return True


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_cannot_spend_the_tenants_delivery_budget(
    db_session, tenant_a, client_factory
) -> None:
    """**The HIGH finding of the section-2 security panel.**

    The per-token counter used to be charged before authentication, so anyone holding only the
    route token — half of the pair, and the half that travels in a URL — could burn a tenant's 120
    deliveries a minute and keep its real integration on `429` indefinitely. That inverts D6: the
    per-token limit exists to contain a provider's runaway traffic, not to be a weapon pointed at
    the tenant from outside.

    Three ways of failing, none of which may touch the tenant's budget.
    """
    token = await _provision(db_session, tenant_a)
    counting = _CountingThrottle()

    async with client_factory(counting) as client:
        await client.post(_url(token), json=BODY, headers={HEADER_NAME: "wrong"})
        await client.post(_url(generate_webhook_token()), json=BODY, headers={HEADER_NAME: SECRET})
        await client.post(_url(token), json=BODY)

    assert counting.deliveries == []
    assert len(counting.failures) == 3


@pytest.mark.asyncio
async def test_an_authenticated_delivery_is_charged_to_the_tenant(
    db_session, tenant_a, client_factory
) -> None:
    """The other half: a real delivery must still be counted, keyed by the STORED hash."""
    token = await _provision(db_session, tenant_a)
    counting = _CountingThrottle()

    async with client_factory(counting) as client:
        response = await client.post(_url(token), json=BODY, headers={HEADER_NAME: SECRET})

    assert response.status_code == 202
    assert counting.deliveries == [hash_webhook_token(token)]
    assert counting.failures == []


@pytest.mark.asyncio
async def test_the_body_is_not_read_before_authentication(
    db_session, tenant_a, client_factory
) -> None:
    """R1.7 verbatim: "rechazar la petición ANTES de leer el cuerpo completo cuando la
    autenticación falla, de forma que un cuerpo grande de un llamante no autenticado no se
    materialice en memoria".

    Asserted by sending a body that **cannot be parsed at all** together with bad credentials: if
    the request is refused with the ordinary `404` rather than anything the parser would produce,
    the body was never needed. A stream that raises on read is the only way to observe "was it
    read?" from outside, short of measuring memory.
    """
    await _provision(db_session, tenant_a)
    read = False

    async def exploding_body():
        nonlocal read
        read = True
        yield b'{"a":'

    async with client_factory() as client:
        response = await client.post(
            _url(generate_webhook_token()),
            content=exploding_body(),
            headers={HEADER_NAME: SECRET, "content-type": "application/json"},
        )

    assert response.status_code == 404
    assert read is False, "the body was consumed before authentication decided"


# --- The real throttle, through the real router (QA panel, section 2) ---


@pytest.mark.asyncio
async def test_the_router_drives_the_real_throttle(db_session, tenant_a) -> None:
    """Every other test here overrides the throttle with a hand-written double.

    Nothing forces those doubles to match `RedisWebhookThrottle`, so renaming a method on the real
    class would leave this whole file green while the deployed endpoint raised `AttributeError` on
    every request. This one test runs the router against the real adapter and the real Redis of
    the compose stack, which is what turns the doubles above from a blind spot into a convenience.
    """
    token = await _provision(db_session, tenant_a)
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    # A UNIQUE client IP, and this is what keeps the test honest rather than merely passing.
    # `ASGITransport` reports every request as `127.0.0.1`, so the failed call below charges the
    # real, shared key `webhook:probe:127.0.0.1` — which never expires between runs within its
    # 60-second window. The QA panel reproduced the consequence: run this test ~15 times in a
    # minute and it starts failing with `429`, because it exhausts the very budget it is not
    # trying to test. `tests/integrations/test_webhook_throttle.py` already solved this with
    # `unique_ip`; the drift-detection value here is in the throttle's *methods* being real, not
    # in which address they are keyed by.
    app.dependency_overrides[get_client_ip] = lambda: f"198.51.100.{uuid.uuid4().int % 200}-{uuid.uuid4().hex[:8]}"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(_url(token), json=BODY, headers={HEADER_NAME: SECRET})
        refused = await client.post(
            _url(generate_webhook_token()), json=BODY, headers={HEADER_NAME: SECRET}
        )

    assert accepted.status_code == 202
    assert refused.status_code == 404


# --- The body ceiling, the half that needs a route to read it (task 2.2) ---


@pytest.mark.asyncio
async def test_a_lying_content_length_is_caught_by_counting_the_stream(
    db_session, tenant_a, client_factory
) -> None:
    """Deferred from 2.2 until a route existed, and now it does.

    `MaxBodySizeMiddleware` refuses a declared `Content-Length` over the ceiling outright; when the
    header is absent, negative or non-numeric it falls back to counting the bytes as they are
    read. That fallback only advances when something reads the body, so it was unobservable while
    this route did not exist. `Content-Length` is a client assertion and this endpoint's clients
    are anonymous, so the fallback is the half that matters here.
    """
    from app.core.config import settings

    token = await _provision(db_session, tenant_a)

    async with client_factory() as client:
        response = await client.post(
            _url(token),
            content=b"x" * (settings.request_max_bytes + 1),
            headers={
                HEADER_NAME: SECRET,
                "content-type": "application/json",
                "content-length": "-1",
            },
        )

    assert response.status_code == 413
    stored = (
        await db_session.execute(text("SELECT count(*) FROM webhook_events"))
    ).scalar_one()
    assert stored == 0


@pytest.mark.asyncio
async def test_an_unknown_token_with_a_lying_content_length_is_a_404_not_a_413(
    db_session, tenant_a, client_factory
) -> None:
    """The sibling the QA panel asked for, and the answer changed with the reordering.

    Authentication now happens before the body is touched, so an unauthenticated caller never
    reaches the parse at all: it gets the uniform `404` of D4, not a `413`. That is the better
    answer on both counts — no body is read (R1.7), and the size of an anonymous caller's body
    tells it nothing about whether its token was real.

    The body must be **genuinely oversized**, not merely present: with a small one this test would
    pass under the old parse-before-auth ordering too, since the byte-counting fallback only fires
    once the ceiling is crossed. The QA panel caught exactly that — the first version used 4 KB and
    discriminated nothing.
    """
    from app.core.config import settings

    await _provision(db_session, tenant_a)

    async with client_factory() as client:
        response = await client.post(
            _url(generate_webhook_token()),
            content=b"x" * (settings.request_max_bytes + 1),
            headers={
                HEADER_NAME: SECRET,
                "content-type": "application/json",
                "content-length": "-1",
            },
        )

    assert response.status_code == 404
    stored = (
        await db_session.execute(text("SELECT count(*) FROM webhook_events"))
    ).scalar_one()
    assert stored == 0
