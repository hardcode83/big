"""The outbound registry, and the two channels deliberately missing from it (R6.2, R6.3, R6.5).

The absence tests are the important half. R6.3 forbids falling back to a console adapter for
`AIRBNB_MSG`/`BOOKING_MSG`, and D14 records why a `NoOpAdapter` for them was rejected: it
would show an operator a delivered message the guest never received. **Both halves are
asserted** — that the registry has no key, *and* that the caller gets an error — because a
`NoOpAdapter` added later would satisfy the second while breaking the first, which is the
failure mode task 5.7 names.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.messaging.domain.enums import ConversationChannel, MessageSenderType
from app.messaging.domain.value_objects import (
    ChannelErrorCode,
    ChannelSendResult,
    contact_kind_for,
)
from app.messaging.infrastructure.channels import (
    DelegatingOutboundAdapter,
    InboundOnlyAdapter,
    PanelOutboundAdapter,
    PortalOutboundAdapter,
    outbound_registry,
)
from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.results import NotificationErrorCode, NotificationResult
from app.notifications.infrastructure.adapters import (
    ConsoleEmailAdapter,
    MockWhatsAppAdapter,
    WhatsAppCloudAdapter,
)
from tests.messaging.fakes import FakeMessageRepository
from tests.messaging.test_repositories import build_message

CONVERSATION_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TENANT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
REPLY = "We have received your message and we are reviewing it. We will reply here as soon as possible."


def registry(messages: FakeMessageRepository | None = None):
    """`outbound_registry` needs a `MessageRepository` since `whatsapp-cloud-adapter` R2.4,
    D2 — a fresh empty `FakeMessageRepository` by default, which is enough for every test in
    this file that is not itself about the session window (that behaviour has its own section
    below, and the query itself is `test_repositories.py`'s to prove against real Postgres)."""
    return outbound_registry(messages or FakeMessageRepository())


async def send(
    adapter,
    *,
    channel: ConversationChannel,
    recipient: str | None = "guest@example.com",
    tenant_id: uuid.UUID = TENANT_ID,
    phone_number_id: str | None = None,
):
    return await adapter.send(
        channel=channel,
        conversation_id=CONVERSATION_ID,
        recipient_contact=recipient,
        content=REPLY,
        language="en",
        tenant_id=tenant_id,
        phone_number_id=phone_number_id,
    )


# --- What the registry contains (R6.2) ---------------------------------------------------


def test_the_registry_serves_the_five_channels_this_deployment_supports() -> None:
    """R6.2 named four — `MANUAL`, `WHATSAPP`, `EMAIL` and `PHONE_TRANSCRIPT`; `PORTAL`
    is the fifth, added by `guest-portal-messaging` R3.2."""
    assert set(registry()) == {
        ConversationChannel.MANUAL,
        ConversationChannel.WHATSAPP,
        ConversationChannel.EMAIL,
        ConversationChannel.PHONE_TRANSCRIPT,
        ConversationChannel.PORTAL,
    }


def test_the_two_ota_channels_are_absent_from_the_registry() -> None:
    """**The mechanism of R6.3.** There is no key with which to fall back to a console
    adapter in silence, so the caller has nothing to do but raise.

    Asserted separately from the error the use case raises, because a `NoOpAdapter` added
    later would pass that test and fail this one — which is exactly the substitution D14
    rejected.
    """
    built = registry()

    assert ConversationChannel.AIRBNB_MSG not in built
    assert ConversationChannel.BOOKING_MSG not in built


def test_every_channel_is_either_served_or_knowingly_unserved() -> None:
    """No third case: a channel added to the enum without a decision shows up here."""
    served = set(registry())
    unserved = {ConversationChannel.AIRBNB_MSG, ConversationChannel.BOOKING_MSG}

    assert served | unserved == set(ConversationChannel)
    assert not served & unserved


def test_the_email_and_whatsapp_entries_delegate_to_the_notifications_adapters() -> None:
    """Delegating rather than duplicating is what inherits their discipline of logging
    neither body nor recipient — see the module docstring of
    `app/notifications/infrastructure/adapters.py`."""
    built = registry()

    email = built[ConversationChannel.EMAIL]
    whatsapp = built[ConversationChannel.WHATSAPP]

    assert isinstance(email, DelegatingOutboundAdapter)
    assert isinstance(email._delegate, ConsoleEmailAdapter)
    assert isinstance(whatsapp, DelegatingOutboundAdapter)
    assert isinstance(whatsapp._delegate, MockWhatsAppAdapter)


# --- What each adapter does --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_panel_adapter_reports_success_because_the_row_is_the_delivery() -> None:
    """D14, precedent `InAppNotificationAdapter`. It is a true statement only because
    `GET /conversations/{id}/messages` exists (R7.1); if that endpoint goes, so does this."""
    result = await send(PanelOutboundAdapter(), channel=ConversationChannel.MANUAL)

    assert result == ChannelSendResult.ok()


@pytest.mark.asyncio
async def test_a_phone_transcript_has_no_outbound_direction() -> None:
    """Registered rather than omitted: it is a channel this change *supports*, it just carries
    messages inwards. Saying so with a named code beats a missing key, which reads as "we
    forgot"."""
    result = await send(InboundOnlyAdapter(), channel=ConversationChannel.PHONE_TRANSCRIPT)

    assert result.delivered is False
    assert result.error_code is ChannelErrorCode.CHANNEL_INBOUND_ONLY


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [ConversationChannel.EMAIL, ConversationChannel.WHATSAPP])
async def test_a_delegated_channel_delivers(channel: ConversationChannel) -> None:
    result = await send(registry()[channel], channel=channel)

    assert result == ChannelSendResult.ok()


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient", [None, "", "   "])
@pytest.mark.parametrize("channel", [ConversationChannel.EMAIL, ConversationChannel.WHATSAPP])
async def test_a_delegated_channel_without_an_address_fails_by_value(
    channel: ConversationChannel, recipient: str | None
) -> None:
    """R6.5: a failure is a value, never an exception. An exception would abort the
    transaction of R4.7 and take the guest's own message down with it."""
    result = await send(registry()[channel], channel=channel, recipient=recipient)

    assert result.delivered is False
    assert result.error_code is ChannelErrorCode.INVALID_RECIPIENT


@pytest.mark.asyncio
async def test_no_adapter_raises_for_a_delivery_failure() -> None:
    """The property R6.5 depends on, asserted across the whole registry at once."""
    for channel, adapter in registry().items():
        result = await send(adapter, channel=channel, recipient=None)

        assert isinstance(result, ChannelSendResult)


# --- What must never reach a log (R6.5, rule 11) -----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [ConversationChannel.EMAIL, ConversationChannel.WHATSAPP])
async def test_nothing_logs_the_reply_or_the_address(
    channel: ConversationChannel, caplog
) -> None:
    """Inherited from the `notifications` adapters, and worth pinning here because this change
    is what starts sending *guest-facing* content through them.

    An application log is not a sink rule 11 covers — no retention policy, no tenant scoping,
    no audit — so the body and the recipient must not appear in one.
    """
    recipient = "guest.private@example.com"
    with caplog.at_level(logging.DEBUG):
        await send(registry()[channel], channel=channel, recipient=recipient)

    emitted = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert recipient not in emitted
    assert REPLY not in emitted


@pytest.mark.asyncio
async def test_a_delegated_failure_translates_into_this_modules_vocabulary() -> None:
    """`messaging` has its own `ChannelErrorCode` because the two enums answer different
    questions — one is about a notification row, the other about a reply to a guest — and
    `CHANNEL_INBOUND_ONLY` exists only here."""
    adapter = DelegatingOutboundAdapter(
        ConsoleEmailAdapter(), NotificationChannel.EMAIL, FakeMessageRepository()
    )

    result = await send(adapter, channel=ConversationChannel.EMAIL, recipient="")

    assert result.error_code in set(ChannelErrorCode)


# --- `PORTAL` (`guest-portal-messaging` R3.1, R3.2) ---------------------------------------


def test_the_portal_entry_is_a_literal_key_of_its_own_class() -> None:
    """R3.2: registered literally, never dispatched dynamically. And a class distinct from
    `PanelOutboundAdapter` — D1: two promises, two endpoints, two classes."""
    adapter = registry()[ConversationChannel.PORTAL]

    assert isinstance(adapter, PortalOutboundAdapter)
    assert not isinstance(adapter, PanelOutboundAdapter)
    assert PortalOutboundAdapter is not PanelOutboundAdapter


@pytest.mark.asyncio
async def test_the_portal_adapter_reports_delivery_because_the_guest_reads_the_row() -> None:
    """Its truth condition is `GET /api/v1/guest/messages/{token}`, not the panel's."""
    result = await send(PortalOutboundAdapter(), channel=ConversationChannel.PORTAL, recipient=None)

    assert result == ChannelSendResult.ok()


def test_the_portal_channel_addresses_nobody() -> None:
    """D1: no entry in `contact_kind_for`. The guest comes back to the page on their own."""
    assert contact_kind_for(ConversationChannel.PORTAL) is None


# --- `WHATSAPP`'s session window: `last_inbound_at`/`template_id` (`whatsapp-cloud-adapter`
# --- R1.2, R2.4, R5.3, design D2) ---------------------------------------------------------

_UNSET = object()


@dataclass
class SpyDelegate:
    """A fake `NotificationAdapter` that records exactly which kwargs
    `DelegatingOutboundAdapter` passed it, rather than asserting on a real provider's HTTP
    shape — that belongs to `tests/notifications/test_whatsapp_cloud_adapter.py`.

    `last_inbound_at`/`template_id`/`phone_number_id` default to the `_UNSET` sentinel rather
    than `None`, so a test can tell "the kwarg was never passed" (`EMAIL`'s branch, since
    `ConsoleEmailAdapter` does not declare it) apart from "the kwarg was passed as `None`"
    (`WHATSAPP`'s branch when the guest never wrote, or no `phone_number_id` was supplied).
    """

    result: NotificationResult = field(default_factory=NotificationResult.ok)
    calls: list[dict] = field(default_factory=list)

    async def send(
        self,
        *,
        recipient_contact,
        subject,
        body,
        channel,
        last_inbound_at=_UNSET,
        template_id=_UNSET,
        phone_number_id=_UNSET,
    ) -> NotificationResult:
        self.calls.append(
            {
                "last_inbound_at": last_inbound_at,
                "template_id": template_id,
                "phone_number_id": phone_number_id,
            }
        )
        return self.result


@pytest.mark.asyncio
async def test_whatsapp_resolves_last_inbound_at_from_the_guests_own_last_message() -> None:
    """R2.4/D2's mechanism: the adapter does not trust the caller, it queries
    `MessageRepository.last_guest_message_at` itself."""
    guest_time = datetime.now(UTC) - timedelta(hours=1)
    messages = FakeMessageRepository()
    messages.rows.append(
        build_message(
            CONVERSATION_ID, sender_type=MessageSenderType.GUEST, created_at=guest_time
        )
    )
    spy = SpyDelegate()
    adapter = DelegatingOutboundAdapter(spy, NotificationChannel.WHATSAPP, messages)

    await send(adapter, channel=ConversationChannel.WHATSAPP)

    assert spy.calls == [
        {"last_inbound_at": guest_time, "template_id": None, "phone_number_id": None}
    ]


@pytest.mark.asyncio
async def test_whatsapp_with_no_guest_message_ever_passes_none() -> None:
    """D2's binding semantics: `last_inbound_at is None` is OUTSIDE the window, not an
    invitation to send free text — the same reading section 1 gave the notifications side."""
    spy = SpyDelegate()
    adapter = DelegatingOutboundAdapter(spy, NotificationChannel.WHATSAPP, FakeMessageRepository())

    await send(adapter, channel=ConversationChannel.WHATSAPP)

    assert spy.calls == [{"last_inbound_at": None, "template_id": None, "phone_number_id": None}]


@pytest.mark.asyncio
async def test_email_never_receives_last_inbound_at_or_template_id() -> None:
    """`ConsoleEmailAdapter.send` was deliberately left untouched by section 1 — it does not
    declare these kwargs at all, so passing them would be a `TypeError`, not a harmless
    no-op (the mistake this test would have caught). Includes `phone_number_id` (task 2.6):
    `EMAIL` has no per-tenant number either."""
    spy = SpyDelegate()
    adapter = DelegatingOutboundAdapter(spy, NotificationChannel.EMAIL, FakeMessageRepository())

    await send(adapter, channel=ConversationChannel.EMAIL, phone_number_id="1234567890")

    assert spy.calls == [
        {"last_inbound_at": _UNSET, "template_id": _UNSET, "phone_number_id": _UNSET}
    ]


@pytest.mark.asyncio
async def test_whatsapp_forwards_the_callers_phone_number_id_to_the_delegate() -> None:
    """`whatsapp-cloud-adapter` task 2.6, design D1: unlike `last_inbound_at`,
    `DelegatingOutboundAdapter` cannot resolve `phone_number_id` itself — it only ever sees
    `conversation_id`, not the `Conversation` entity — so it must forward exactly what the
    caller (the use case, which has `Conversation.business_phone_number`) passed in."""
    spy = SpyDelegate()
    adapter = DelegatingOutboundAdapter(spy, NotificationChannel.WHATSAPP, FakeMessageRepository())

    await send(adapter, channel=ConversationChannel.WHATSAPP, phone_number_id="1234567890")

    assert spy.calls == [
        {"last_inbound_at": None, "template_id": None, "phone_number_id": "1234567890"}
    ]


@pytest.mark.asyncio
async def test_a_delegated_outside_session_window_failure_translates_by_name() -> None:
    """R2.3/R2.4: `OUTSIDE_SESSION_WINDOW` is translated 1:1, not folded into
    `ADAPTER_UNAVAILABLE` the way an unclassified failure is."""
    spy = SpyDelegate(
        result=NotificationResult.failure(NotificationErrorCode.OUTSIDE_SESSION_WINDOW)
    )
    adapter = DelegatingOutboundAdapter(spy, NotificationChannel.WHATSAPP, FakeMessageRepository())

    result = await send(adapter, channel=ConversationChannel.WHATSAPP)

    assert result.delivered is False
    assert result.error_code is ChannelErrorCode.OUTSIDE_SESSION_WINDOW


def _mock_transport(captured: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.abc123"}]})

    return httpx.MockTransport(handler)


def _unreachable_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP request should have been made — outside the window")

    return httpx.MockTransport(handler)


def _url_capturing_transport(captured: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json={"messages": [{"id": "wamid.abc123"}]})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_a_guest_message_under_24h_old_sends_in_free_text() -> None:
    """R5.3: the AI's reply to a `WHATSAPP` conversation the guest wrote in less than 24h
    ago goes out as free text — end to end through `DelegatingOutboundAdapter` and the real
    `WhatsAppCloudAdapter` (over a mock transport, never the network)."""
    messages = FakeMessageRepository()
    messages.rows.append(
        build_message(
            CONVERSATION_ID,
            sender_type=MessageSenderType.GUEST,
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    captured: list[dict] = []
    delegate = WhatsAppCloudAdapter(
        access_token="test-token",
        phone_number_id="1234567890",
        transport=_mock_transport(captured),
    )
    adapter = DelegatingOutboundAdapter(delegate, NotificationChannel.WHATSAPP, messages)

    result = await send(adapter, channel=ConversationChannel.WHATSAPP, recipient="34600111222")

    assert result == ChannelSendResult.ok()
    assert captured[0]["type"] == "text"


@pytest.mark.asyncio
async def test_a_guest_message_over_24h_old_stays_outside_window_even_with_a_recent_manager_reply() -> None:
    """The case that motivated task 2.3: `Conversation.last_message_at` would have been
    touched by the manager's reply a minute ago and read as "inside window". Only the
    guest's own last message counts (D2), so this conversation is still outside it and — with
    no `template_id` — fails rather than silently reopening the window."""
    messages = FakeMessageRepository()
    messages.rows.append(
        build_message(
            CONVERSATION_ID,
            sender_type=MessageSenderType.GUEST,
            created_at=datetime.now(UTC) - timedelta(hours=25),
        )
    )
    messages.rows.append(
        build_message(
            CONVERSATION_ID,
            sender_type=MessageSenderType.MANAGER,
            created_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    delegate = WhatsAppCloudAdapter(
        access_token="test-token",
        phone_number_id="1234567890",
        transport=_unreachable_transport(),
    )
    adapter = DelegatingOutboundAdapter(delegate, NotificationChannel.WHATSAPP, messages)

    result = await send(adapter, channel=ConversationChannel.WHATSAPP, recipient="34600111222")

    assert result.delivered is False
    assert result.error_code is ChannelErrorCode.OUTSIDE_SESSION_WINDOW


@pytest.mark.asyncio
async def test_a_reply_leaves_from_the_conversations_business_phone_number_not_the_adapters_construction_default() -> None:
    """`whatsapp-cloud-adapter` task 2.6, design D1: end to end through
    `DelegatingOutboundAdapter` and the real `WhatsAppCloudAdapter`, the Graph API call must
    use the `phone_number_id` the caller supplied (`Conversation.business_phone_number`), not
    the one `WhatsAppCloudAdapter` was constructed with — that one is only the platform
    default for a proactive notification with no guest conversation behind it."""
    messages = FakeMessageRepository()
    messages.rows.append(
        build_message(
            CONVERSATION_ID,
            sender_type=MessageSenderType.GUEST,
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    captured_urls: list[str] = []
    delegate = WhatsAppCloudAdapter(
        access_token="test-token",
        phone_number_id="platform-default-number",
        transport=_url_capturing_transport(captured_urls),
    )
    adapter = DelegatingOutboundAdapter(delegate, NotificationChannel.WHATSAPP, messages)

    result = await send(
        adapter,
        channel=ConversationChannel.WHATSAPP,
        recipient="34600111222",
        phone_number_id="conversations-own-number",
    )

    assert result == ChannelSendResult.ok()
    assert "conversations-own-number" in captured_urls[0]
    assert "platform-default-number" not in captured_urls[0]
