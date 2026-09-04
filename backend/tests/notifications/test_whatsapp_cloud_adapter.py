"""`WhatsAppCloudAdapter` — the real `WHATSAPP_PROVIDER=meta` adapter and its 24h session
window (`whatsapp-cloud-adapter` design D1/D2, R1.1, R1.4, R1.5, R2.1-R2.3).

Offline by construction: every test drives the adapter through an `httpx.MockTransport`, the
same pattern `tests/integrations/test_beds24_client.py` uses for its provider client —
`steering/testing.md` requires the HTTP boundary mocked, never a real network call.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.results import NotificationErrorCode
from app.notifications.infrastructure.adapters import (
    MockWhatsAppAdapter,
    WhatsAppCloudAdapter,
    adapter_registry,
)

ACCESS_TOKEN = "test-access-token"
PHONE_NUMBER_ID = "1234567890"


def _adapter(handler) -> WhatsAppCloudAdapter:
    return WhatsAppCloudAdapter(
        access_token=ACCESS_TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        transport=httpx.MockTransport(handler),
    )


def _capturing_handler(captured: list[dict]):
    """Records the payload of every request and answers with a Graph API success envelope."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
        assert request.url.path == f"/v21.0/{PHONE_NUMBER_ID}/messages"
        import json

        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.abc123"}]})

    return handler


def _unreachable_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError("no HTTP request should have been made")


# --- R2.1/R2.2: the 24h window ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_within_window_sends_free_text() -> None:
    captured: list[dict] = []
    adapter = _adapter(_capturing_handler(captured))
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="Your room is ready.",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert result.delivered is True
    assert result.error_code is None
    assert captured == [
        {
            "messaging_product": "whatsapp",
            "to": "34600111222",
            "type": "text",
            "text": {"body": "Your room is ready."},
        }
    ]


@pytest.mark.asyncio
async def test_just_under_the_24h_boundary_is_still_within_window() -> None:
    # Not exactly `timedelta(hours=24)`: the adapter reads its own `datetime.now(UTC)`
    # inside `send`, a few milliseconds after this line runs, so an exact-24h timestamp is
    # flaky by construction — it would age past the boundary between the two clock reads.
    # A one-minute margin absorbs that without weakening what R2.2 actually requires.
    captured: list[dict] = []
    adapter = _adapter(_capturing_handler(captured))
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="Still in time.",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC) - timedelta(hours=23, minutes=59),
    )
    assert result.delivered is True
    assert captured[0]["type"] == "text"


@pytest.mark.asyncio
async def test_just_over_the_24h_boundary_is_outside_window() -> None:
    adapter = _adapter(_unreachable_handler)
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="Too late.",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC) - timedelta(hours=24, minutes=1),
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.OUTSIDE_SESSION_WINDOW


@pytest.mark.asyncio
async def test_outside_window_with_template_id_sends_a_template() -> None:
    captured: list[dict] = []
    adapter = _adapter(_capturing_handler(captured))
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="ignored for a template send",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC) - timedelta(hours=25),
        template_id="booking_confirmation",
    )
    assert result.delivered is True
    assert captured == [
        {
            "messaging_product": "whatsapp",
            "to": "34600111222",
            "type": "template",
            "template": {
                "name": "booking_confirmation",
                "language": {"code": "es"},
            },
        }
    ]


@pytest.mark.asyncio
async def test_outside_window_without_template_id_fails_closed_without_a_network_call() -> None:
    """R2.1/R2.3: no template applicable -> `OUTSIDE_SESSION_WINDOW`, never a silent send."""
    adapter = _adapter(_unreachable_handler)
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="This must never reach Meta.",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC) - timedelta(hours=25),
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.OUTSIDE_SESSION_WINDOW


@pytest.mark.asyncio
async def test_no_last_inbound_at_and_no_template_id_fails_closed() -> None:
    """The resolved reading of design D2: `last_inbound_at is None` is OUTSIDE the window,
    never an implicit "send free text anyway" (R2.3, R2.4). This is the shape every
    notifications-side WhatsApp send takes, since `_deliver` never passes `last_inbound_at`.
    """
    adapter = _adapter(_unreachable_handler)
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="A proactive notification with no session and no template.",
        channel=NotificationChannel.WHATSAPP,
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.OUTSIDE_SESSION_WINDOW


@pytest.mark.asyncio
async def test_no_last_inbound_at_but_a_template_id_sends_a_template() -> None:
    captured: list[dict] = []
    adapter = _adapter(_capturing_handler(captured))
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="ignored",
        channel=NotificationChannel.WHATSAPP,
        template_id="booking_confirmation",
    )
    assert result.delivered is True
    assert captured[0]["type"] == "template"


# --- R1.4: blank recipient and unclassifiable provider errors --------------------------------


@pytest.mark.asyncio
async def test_blank_recipient_is_a_failure_not_an_exception_and_makes_no_request() -> None:
    adapter = _adapter(_unreachable_handler)
    result = await adapter.send(
        recipient_contact="   ",
        subject=None,
        body="b",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC),
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.INVALID_RECIPIENT


@pytest.mark.asyncio
async def test_timeout_never_propagates_and_maps_to_timeout_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Graph API took too long")

    adapter = _adapter(handler)
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="b",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC),
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.TIMEOUT


@pytest.mark.asyncio
async def test_connection_error_never_propagates_and_maps_to_adapter_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    adapter = _adapter(handler)
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="b",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC),
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.ADAPTER_ERROR


@pytest.mark.asyncio
async def test_non_2xx_response_never_propagates_and_maps_to_adapter_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Invalid OAuth access token", "code": 190}},
        )

    adapter = _adapter(handler)
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="b",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC),
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.ADAPTER_ERROR


@pytest.mark.asyncio
async def test_provider_error_text_never_reaches_the_result_or_a_log_line(caplog) -> None:
    """Rule 11: whatever Meta says in its error JSON has nowhere to travel."""
    secret_looking_error = "Invalid OAuth access token AAABBBCCCsecret for +34600111222"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": secret_looking_error}})

    adapter = _adapter(handler)
    with caplog.at_level(logging.DEBUG):
        result = await adapter.send(
            recipient_contact="34600111222",
            subject=None,
            body="the guest's door code is 4821",
            channel=NotificationChannel.WHATSAPP,
            last_inbound_at=datetime.now(UTC),
        )
    assert result.delivered is False
    emitted = "\n".join(
        record.getMessage() + " " + " ".join(str(value) for value in record.__dict__.values())
        for record in caplog.records
    )
    assert secret_looking_error not in emitted
    assert "the guest's door code is 4821" not in emitted
    assert "34600111222" not in emitted


# --- Task 1.7 (design D1 addendum, D4's `business_phone_number` addendum): a per-call
# `phone_number_id` overrides the constructor's default -------------------------------------

OTHER_PHONE_NUMBER_ID = "9998887776"

@pytest.mark.asyncio
async def test_explicit_phone_number_id_is_used_in_the_graph_api_url_instead_of_the_constructors() -> (
    None
):
    """A reply must leave from the same number the guest wrote to, not the platform default."""
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(request.url.path)
        return httpx.Response(200, json={"messages": [{"id": "wamid.abc123"}]})

    adapter = _adapter(handler)
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="from the tenant's own number",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC) - timedelta(hours=1),
        phone_number_id=OTHER_PHONE_NUMBER_ID,
    )
    assert result.delivered is True
    assert captured_urls == [f"/v21.0/{OTHER_PHONE_NUMBER_ID}/messages"]

@pytest.mark.asyncio
async def test_omitted_phone_number_id_still_falls_back_to_the_constructors_default() -> None:
    """Regression check: existing callers that never pass `phone_number_id` are unaffected."""
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(request.url.path)
        return httpx.Response(200, json={"messages": [{"id": "wamid.abc123"}]})

    adapter = _adapter(handler)
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="from the platform default",
        channel=NotificationChannel.WHATSAPP,
        last_inbound_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert result.delivered is True
    assert captured_urls == [f"/v21.0/{PHONE_NUMBER_ID}/messages"]

# --- R1.5: `WHATSAPP_PROVIDER=mock` preserves today's behaviour ------------------------------


@pytest.mark.asyncio
async def test_mock_adapter_ignores_the_window_and_always_succeeds() -> None:
    """R1.5: `mock` mode is not a smaller Meta client — it never rejects on window grounds."""
    adapter = MockWhatsAppAdapter()
    result = await adapter.send(
        recipient_contact="34600111222",
        subject=None,
        body="free text with no last_inbound_at and no template_id",
        channel=NotificationChannel.WHATSAPP,
    )
    assert result.delivered is True
    assert result.error_code is None


@pytest.mark.asyncio
async def test_mock_adapter_still_rejects_a_blank_recipient() -> None:
    adapter = MockWhatsAppAdapter()
    result = await adapter.send(
        recipient_contact="   ",
        subject=None,
        body="b",
        channel=NotificationChannel.WHATSAPP,
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.INVALID_RECIPIENT


def test_adapter_registry_selects_mock_by_default_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.notifications.infrastructure.adapters.settings.whatsapp_provider", "mock"
    )
    registry = adapter_registry()
    assert isinstance(registry[NotificationChannel.WHATSAPP], MockWhatsAppAdapter)


def test_adapter_registry_selects_the_real_adapter_for_meta(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.notifications.infrastructure.adapters.settings.whatsapp_provider", "meta"
    )
    monkeypatch.setattr(
        "app.notifications.infrastructure.adapters.settings.whatsapp_access_token",
        ACCESS_TOKEN,
    )
    monkeypatch.setattr(
        "app.notifications.infrastructure.adapters.settings.whatsapp_phone_number_id",
        PHONE_NUMBER_ID,
    )
    registry = adapter_registry()
    assert isinstance(registry[NotificationChannel.WHATSAPP], WhatsAppCloudAdapter)
