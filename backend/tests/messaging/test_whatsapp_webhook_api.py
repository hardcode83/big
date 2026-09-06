"""The anonymous WhatsApp receiver and Meta's handshake, over HTTP (R3.1, R3.3, R3.4, D3a).

The transport half only — status codes, the uniform `403`, the empty `202`, the plain-text
challenge and the two rate limits. The authentication rule itself, the tenant resolution and
the deduplication are asserted against the use case in `test_whatsapp_webhook_receipt.py`,
without FastAPI, which is the split `steering/backend.md` requires ("la lógica nunca vive en
el router").

The throttle is overridden with a permissive double everywhere except in the two tests that
are about the limits: letting the real Redis counters leak between tests would make failures
depend on execution order, which is the trade `tests/integrations/test_webhook_receiver_api.py`
records for the same reason.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.api.dependencies import get_client_ip
from app.core.config import settings
from app.core.db import get_db_session
from app.integrations.api.dependencies import get_webhook_throttle
from app.main import create_app
from app.messaging.api.dependencies import (
    get_whatsapp_inbound_dispatcher,
    whatsapp_signing_secret,
)
from app.messaging.infrastructure.models import (
    WhatsAppInboundEventModel,
    WhatsAppPhoneNumberModel,
)
from app.messaging.infrastructure.whatsapp_providers import SIGNATURE_HEADER
from tests.messaging.conftest import seed_property, seed_tenant
from tests.messaging.test_whatsapp_inbound_provider import (
    APP_SECRET,
    PHONE_NUMBER_ID,
    headers_for,
    raw,
    webhook_payload,
)

WEBHOOK_URL = "/api/v1/webhooks/whatsapp"
VERIFY_TOKEN = "a-token-the-operator-invented"


class _AllowAll:
    """Every request permitted, nothing counted."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.delivery_keys: list[str] = []

    async def probe_allowed(self, client_ip: str) -> bool:
        return True

    async def delivery_allowed(self, key: str) -> bool:
        self.delivery_keys.append(key)
        return True

    async def record_failed_attempt(self, client_ip: str) -> None:
        self.failures.append(client_ip)


class _RefuseDeliveries(_AllowAll):
    async def delivery_allowed(self, key: str) -> bool:
        self.delivery_keys.append(key)
        return False


class _RefuseProbes(_AllowAll):
    async def probe_allowed(self, client_ip: str) -> bool:
        return False


class _Dispatcher:
    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    def __call__(self, event_id: uuid.UUID) -> None:
        self.calls.append(event_id)


@pytest.fixture
def throttle() -> _AllowAll:
    return _AllowAll()


@pytest.fixture
def dispatcher() -> _Dispatcher:
    return _Dispatcher()


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that has configured Meta, for the whole file.

    `whatsapp_signing_secret` is overridden per client below rather than through `settings`
    for the tests that need a different secret; this fixture is what makes the `GET`
    handshake's token real and keeps `whatsapp_provider` out of the picture.
    """
    monkeypatch.setattr(settings, "whatsapp_provider", "meta")
    monkeypatch.setattr(settings, "whatsapp_app_secret", APP_SECRET)
    monkeypatch.setattr(settings, "whatsapp_webhook_verify_token", VERIFY_TOKEN)


@pytest.fixture
def client_factory(db_session, throttle, dispatcher):
    def build(*, override=None, secret: str | None = None):
        app = create_app()

        async def _session_override():
            yield db_session

        app.dependency_overrides[get_db_session] = _session_override
        app.dependency_overrides[get_webhook_throttle] = lambda: override or throttle
        app.dependency_overrides[get_whatsapp_inbound_dispatcher] = lambda: dispatcher
        if secret is not None:
            app.dependency_overrides[whatsapp_signing_secret] = lambda: secret
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return build


@pytest_asyncio.fixture
async def provisioned(db_session):
    tenant = await seed_tenant(db_session, "TenantWhatsAppApi")
    prop = await seed_property(db_session, tenant, "WA-API")
    db_session.add(
        WhatsAppPhoneNumberModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            phone_number_id=PHONE_NUMBER_ID,
            default_property_id=prop.id,
        )
    )
    await db_session.commit()
    return tenant, prop


async def _rows(db_session) -> list[WhatsAppInboundEventModel]:
    from sqlalchemy import select

    return list((await db_session.execute(select(WhatsAppInboundEventModel))).scalars())


def _signed(body: bytes, secret: str = APP_SECRET) -> dict[str, str]:
    return headers_for(body, secret)


# --- The accepted delivery (R3.4) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_signed_delivery_is_accepted_with_an_empty_202(
    db_session, provisioned, client_factory, dispatcher
) -> None:
    body = raw(webhook_payload())

    async with client_factory() as client:
        response = await client.post(WEBHOOK_URL, content=body, headers=_signed(body))

    assert response.status_code == 202
    # Nothing echoed back: an anonymous caller reads anything in the body as a signal.
    assert response.content == b""
    assert len(await _rows(db_session)) == 1
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_a_status_receipt_is_also_a_202_so_meta_stops_redelivering(
    db_session, client_factory, dispatcher
) -> None:
    """Meta posts delivery and read receipts to this very URL, and retries any non-2xx."""
    body = raw({"entry": [{"changes": [{"value": {"statuses": []}}]}]})

    async with client_factory() as client:
        response = await client.post(WEBHOOK_URL, content=body, headers=_signed(body))

    assert response.status_code == 202
    assert await _rows(db_session) == []
    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_an_unprovisioned_number_is_still_a_202(
    db_session, client_factory, dispatcher
) -> None:
    """R3.3 as amended: recorded for the operator, and Meta is told not to retry.

    A `404` here would make the guest's message retry for as long as it took an operator to
    associate the number, and then arrive as a flood.
    """
    body = raw(webhook_payload())

    async with client_factory() as client:
        response = await client.post(WEBHOOK_URL, content=body, headers=_signed(body))

    assert response.status_code == 202
    (row,) = await _rows(db_session)
    assert row.tenant_id is None
    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_a_redelivery_is_a_202_and_writes_nothing_more(
    db_session, provisioned, client_factory, dispatcher
) -> None:
    body = raw(webhook_payload())

    async with client_factory() as client:
        first = await client.post(WEBHOOK_URL, content=body, headers=_signed(body))
        second = await client.post(WEBHOOK_URL, content=body, headers=_signed(body))

    assert (first.status_code, second.status_code) == (202, 202)
    assert len(await _rows(db_session)) == 1
    assert len(dispatcher.calls) == 1


# --- R3.3: one refusal, whatever went wrong -----------------------------------------------


@pytest.mark.parametrize(
    ("case", "headers_of"),
    [
        ("no signature header", lambda body: {}),
        ("a malformed header", lambda body: {SIGNATURE_HEADER: "garbage"}),
        ("the wrong secret", lambda body: headers_for(body, "not-the-app-secret")),
        ("a body altered after signing", lambda body: headers_for(body + b"x", APP_SECRET)),
    ],
)
@pytest.mark.asyncio
async def test_every_signature_failure_is_the_same_403_with_the_same_body(
    db_session, provisioned, client_factory, dispatcher, throttle, case, headers_of
) -> None:
    """R3.3, over HTTP: the status, the envelope and the absence of a row all match."""
    body = raw(webhook_payload())

    async with client_factory() as client:
        response = await client.post(WEBHOOK_URL, content=body, headers=headers_of(body))

    assert response.status_code == 403, case
    assert response.json() == {
        "error": {"code": "FORBIDDEN", "message": "Forbidden", "details": {}}
    }, case
    assert await _rows(db_session) == [], case
    assert dispatcher.calls == [], case
    # And only a failure is charged to the per-IP budget (R3.4).
    assert throttle.failures, case
    assert throttle.delivery_keys == [], case


@pytest.mark.asyncio
async def test_the_four_refusals_are_byte_identical_to_each_other(
    db_session, provisioned, client_factory
) -> None:
    """Asserted as one set rather than four separate equalities.

    The parametrised test above would still pass if two cases answered two different `403`
    bodies, as long as each matched its own expectation. This is the assertion that they are
    the *same* answer — which is what R3.3 actually asks for.
    """
    body = raw(webhook_payload())
    variants = [
        {},
        {SIGNATURE_HEADER: "garbage"},
        headers_for(body, "not-the-app-secret"),
        headers_for(body + b"x", APP_SECRET),
    ]

    async with client_factory() as client:
        answers = {
            (r.status_code, r.content)
            for r in [
                await client.post(WEBHOOK_URL, content=body, headers=h) for h in variants
            ]
        }

    assert len(answers) == 1


@pytest.mark.asyncio
async def test_a_deployment_with_no_secret_refuses_everything(
    db_session, provisioned, client_factory
) -> None:
    """`mock` mode, through the wiring: `whatsapp_signing_secret` answers `""` (task 7.1)."""
    body = raw(webhook_payload())

    async with client_factory(secret="") as client:
        response = await client.post(WEBHOOK_URL, content=body, headers=_signed(body, ""))

    assert response.status_code == 403
    assert await _rows(db_session) == []


# --- R3.4: the two limits ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_per_ip_probe_budget_refuses_before_any_work(
    db_session, provisioned, client_factory
) -> None:
    """Checked first, before the body is even read: it is what makes forging cost something."""
    body = raw(webhook_payload())
    refusing = _RefuseProbes()

    async with client_factory(override=refusing) as client:
        response = await client.post(WEBHOOK_URL, content=body, headers=_signed(body))

    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "RATE_LIMITED", "message": "Too many requests", "details": {}}
    }
    assert await _rows(db_session) == []
    # Nothing was charged to the delivery budget: the request never got past the probe.
    assert refusing.delivery_keys == []


@pytest.mark.asyncio
async def test_the_delivery_budget_refuses_an_authenticated_flood(
    db_session, provisioned, client_factory, dispatcher
) -> None:
    body = raw(webhook_payload())
    refusing = _RefuseDeliveries()

    async with client_factory(override=refusing) as client:
        response = await client.post(WEBHOOK_URL, content=body, headers=_signed(body))

    assert response.status_code == 429
    assert await _rows(db_session) == []
    assert dispatcher.calls == []


@pytest.mark.asyncio
async def test_the_delivery_budget_is_keyed_on_the_one_subscription(
    db_session, provisioned, client_factory, throttle
) -> None:
    """The judgment call of task 7.3, pinned by value so it is a decision and not a drift.

    There is no per-tenant credential on this route — one Meta App, one subscription, one
    shared secret — and the only per-tenant identity is inside the body, i.e. after the work
    this budget bounds. Keying on a constant is what makes the budget the subscription's.
    """
    from app.messaging.api.whatsapp_webhook_router import WHATSAPP_DELIVERY_BUDGET_KEY

    body = raw(webhook_payload())

    async with client_factory() as client:
        await client.post(WEBHOOK_URL, content=body, headers=_signed(body))

    assert throttle.delivery_keys == [WHATSAPP_DELIVERY_BUDGET_KEY]
    # Not the guest's number, not the business number, not the client IP: none of those is
    # known when the check runs, and two of them are attacker-influenced.
    assert PHONE_NUMBER_ID not in WHATSAPP_DELIVERY_BUDGET_KEY


@pytest.mark.asyncio
async def test_the_body_ceiling_is_the_global_middlewares_and_needs_no_code_here(
    db_session, provisioned, client_factory
) -> None:
    """R3.4's size cap: `MaxBodySizeMiddleware` covers all of `/api/v1/` before routing.

    Asserted here rather than assumed, because "already covered globally" is exactly the kind
    of claim that stops being true when a route is mounted somewhere unexpected — and this
    one is on a router of its own.
    """
    from app.core.http_limits import JSON_BODY_MAX_BYTES

    oversized = (
        b'{"entry":[{"changes":[{"value":{"padding":"'
        + b"x" * (JSON_BODY_MAX_BYTES + 1)
        + b'"}}]}]}'
    )

    async with client_factory() as client:
        response = await client.post(
            WEBHOOK_URL, content=oversized, headers=_signed(oversized)
        )

    assert response.status_code == 413
    assert await _rows(db_session) == []


# --- D3a: Meta's verification handshake ----------------------------------------------------


@pytest.mark.asyncio
async def test_the_right_verify_token_gets_the_challenge_back_as_plain_text(
    client_factory,
) -> None:
    """Meta compares the body byte for byte, so JSON quoting would fail the subscription."""
    async with client_factory() as client:
        response = await client.get(
            WEBHOOK_URL,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "1158201444",
            },
        )

    assert response.status_code == 200
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    ("case", "params"),
    [
        (
            "a wrong token",
            {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "x"},
        ),
        ("no token at all", {"hub.mode": "subscribe", "hub.challenge": "x"}),
        ("an empty token", {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "x"}),
        (
            "no challenge to echo",
            {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN},
        ),
        (
            "a mode Meta never sends",
            {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "x"},
        ),
        ("no query parameters at all", {}),
    ],
)
@pytest.mark.asyncio
async def test_every_handshake_refusal_is_an_empty_403(client_factory, case, params) -> None:
    """One answer for all of them, including the absent-parameter cases.

    Those are the reason all three query parameters are optional in the signature: a required
    one would make FastAPI answer `422`, which tells a caller that it got the token right and
    something else wrong.
    """
    async with client_factory() as client:
        response = await client.get(WEBHOOK_URL, params=params)

    assert response.status_code == 403, case
    assert response.content == b"", case


@pytest.mark.asyncio
async def test_an_unconfigured_verify_token_matches_no_query_parameter(
    client_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment that never set the variable must not be opened by an empty parameter."""
    monkeypatch.setattr(settings, "whatsapp_webhook_verify_token", None)

    async with client_factory() as client:
        blank = await client.get(
            WEBHOOK_URL,
            params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "x"},
        )

    assert blank.status_code == 403
    assert blank.content == b""


@pytest.mark.asyncio
async def test_the_handshake_and_the_receiver_share_one_fixed_path(client_factory) -> None:
    """R3.1 as amended: one route for the whole platform, no per-tenant segment.

    Pinned because the original design had a per-tenant token in this URL, and a stray
    segment would be invisible in the tests above — each of which builds its own URL.
    """
    from app.main import create_app as _create_app
    from tests.route_walk import flatten_routes

    found, _ = flatten_routes(_create_app())
    whatsapp = {
        (verb, path)
        for path, route in found
        for verb in (route.methods or set())
        if path.startswith("/api/v1/webhooks/whatsapp") and verb != "HEAD"
    }

    assert whatsapp == {("GET", WEBHOOK_URL), ("POST", WEBHOOK_URL)}
