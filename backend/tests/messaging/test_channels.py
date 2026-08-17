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

import pytest

from app.messaging.domain.enums import ConversationChannel
from app.messaging.domain.value_objects import ChannelErrorCode, ChannelSendResult
from app.messaging.infrastructure.channels import (
    DelegatingOutboundAdapter,
    InboundOnlyAdapter,
    PanelOutboundAdapter,
    outbound_registry,
)
from app.notifications.domain.enums import NotificationChannel
from app.notifications.infrastructure.adapters import (
    ConsoleEmailAdapter,
    MockWhatsAppAdapter,
)

CONVERSATION_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
REPLY = "We have received your message and we are reviewing it. We will reply here as soon as possible."


async def send(adapter, *, channel: ConversationChannel, recipient: str | None = "guest@example.com"):
    return await adapter.send(
        channel=channel,
        conversation_id=CONVERSATION_ID,
        recipient_contact=recipient,
        content=REPLY,
        language="en",
    )


# --- What the registry contains (R6.2) ---------------------------------------------------


def test_the_registry_serves_the_four_channels_this_change_supports() -> None:
    """R6.2 names them: `MANUAL`, `WHATSAPP`, `EMAIL` and `PHONE_TRANSCRIPT`."""
    assert set(outbound_registry()) == {
        ConversationChannel.MANUAL,
        ConversationChannel.WHATSAPP,
        ConversationChannel.EMAIL,
        ConversationChannel.PHONE_TRANSCRIPT,
    }


def test_the_two_ota_channels_are_absent_from_the_registry() -> None:
    """**The mechanism of R6.3.** There is no key with which to fall back to a console
    adapter in silence, so the caller has nothing to do but raise.

    Asserted separately from the error the use case raises, because a `NoOpAdapter` added
    later would pass that test and fail this one — which is exactly the substitution D14
    rejected.
    """
    registry = outbound_registry()

    assert ConversationChannel.AIRBNB_MSG not in registry
    assert ConversationChannel.BOOKING_MSG not in registry


def test_every_channel_is_either_served_or_knowingly_unserved() -> None:
    """No third case: a channel added to the enum without a decision shows up here."""
    served = set(outbound_registry())
    unserved = {ConversationChannel.AIRBNB_MSG, ConversationChannel.BOOKING_MSG}

    assert served | unserved == set(ConversationChannel)
    assert not served & unserved


def test_the_email_and_whatsapp_entries_delegate_to_the_notifications_adapters() -> None:
    """Delegating rather than duplicating is what inherits their discipline of logging
    neither body nor recipient — see the module docstring of
    `app/notifications/infrastructure/adapters.py`."""
    registry = outbound_registry()

    email = registry[ConversationChannel.EMAIL]
    whatsapp = registry[ConversationChannel.WHATSAPP]

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
    result = await send(outbound_registry()[channel], channel=channel)

    assert result == ChannelSendResult.ok()


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient", [None, "", "   "])
@pytest.mark.parametrize("channel", [ConversationChannel.EMAIL, ConversationChannel.WHATSAPP])
async def test_a_delegated_channel_without_an_address_fails_by_value(
    channel: ConversationChannel, recipient: str | None
) -> None:
    """R6.5: a failure is a value, never an exception. An exception would abort the
    transaction of R4.7 and take the guest's own message down with it."""
    result = await send(outbound_registry()[channel], channel=channel, recipient=recipient)

    assert result.delivered is False
    assert result.error_code is ChannelErrorCode.INVALID_RECIPIENT


@pytest.mark.asyncio
async def test_no_adapter_raises_for_a_delivery_failure() -> None:
    """The property R6.5 depends on, asserted across the whole registry at once."""
    for channel, adapter in outbound_registry().items():
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
        await send(outbound_registry()[channel], channel=channel, recipient=recipient)

    emitted = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert recipient not in emitted
    assert REPLY not in emitted


@pytest.mark.asyncio
async def test_a_delegated_failure_translates_into_this_modules_vocabulary() -> None:
    """`messaging` has its own `ChannelErrorCode` because the two enums answer different
    questions — one is about a notification row, the other about a reply to a guest — and
    `CHANNEL_INBOUND_ONLY` exists only here."""
    adapter = DelegatingOutboundAdapter(ConsoleEmailAdapter(), NotificationChannel.EMAIL)

    result = await send(adapter, channel=ConversationChannel.EMAIL, recipient="")

    assert result.error_code in set(ChannelErrorCode)
