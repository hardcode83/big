"""Where an automatic reply actually goes (R6.2, R6.3; design D14).

| `ConversationChannel` | Adapter | What it does |
|---|---|---|
| `MANUAL` | `PanelOutboundAdapter` | no-op: the row **is** the delivery |
| `PORTAL` | `PortalOutboundAdapter` | no-op: the row **is** the delivery, read by the guest |
| `WHATSAPP` | delegates to `MockWhatsAppAdapter` | the mock `access-notifications` governs |
| `EMAIL` | delegates to `ConsoleEmailAdapter` | ditto |
| `PHONE_TRANSCRIPT` | `InboundOnlyAdapter` | returns `CHANNEL_INBOUND_ONLY` |
| `AIRBNB_MSG`, `BOOKING_MSG` | — | **absent on purpose** (R6.3) |

**Delegating to the `notifications` adapters rather than duplicating them** inherits their
discipline for free: they log neither `subject`, nor `body`, nor `recipient_contact` — only
lengths — which is exactly what rule 11 of `sdd/steering/security.md` wants for this content.
Writing two console adapters would have meant writing that discipline twice and keeping it
true in both.

**The two OTA channels are absent, and that absence is the mechanism of R6.3**: there is no
key in the registry with which to fall back to a console adapter in silence, so
`PMSChannelUnavailableError` is the only thing that can happen. A `NoOpAdapter` for them was
rejected in D14 — it is precisely the "caer en silencio a consola" the requirement names, and
it would show an operator a delivered message the guest never received. Those two channels
arrive with `beds24-messaging-adapter`, through `PMSMessagingPort`, which this change leaves
method-less (R6.4).
"""

import uuid

from app.messaging.domain.enums import ConversationChannel
from app.messaging.domain.ports import OutboundMessagePort
from app.messaging.domain.value_objects import ChannelErrorCode, ChannelSendResult
from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.results import NotificationResult
from app.notifications.infrastructure.adapters import (
    ConsoleEmailAdapter,
    MockWhatsAppAdapter,
)

#: How a `NotificationResult` from a delegated adapter becomes a `ChannelSendResult`.
#: A mapping and not a chain of `if`s, so an error code added to `NotificationErrorCode`
#: later fails loudly in `_translate` instead of silently inheriting somebody else's meaning.
#: Only the codes a `notifications` adapter can actually return are here; the rest belong to
#: its dispatcher, not to a single send.
_ERROR_TRANSLATION = {
    "INVALID_RECIPIENT": ChannelErrorCode.INVALID_RECIPIENT,
    "ADAPTER_ERROR": ChannelErrorCode.ADAPTER_UNAVAILABLE,
    "TIMEOUT": ChannelErrorCode.ADAPTER_UNAVAILABLE,
    "NO_ADAPTER_FOR_CHANNEL": ChannelErrorCode.ADAPTER_UNAVAILABLE,
    "MAX_ATTEMPTS_EXCEEDED": ChannelErrorCode.ADAPTER_UNAVAILABLE,
}


def _translate(result: NotificationResult) -> ChannelSendResult:
    """Two vocabularies, one crossing point.

    `messaging` has its own `ChannelErrorCode` rather than importing `NotificationErrorCode`
    because the two answer different questions — one is about a notification row, the other
    about a reply to a guest — and `CHANNEL_INBOUND_ONLY` exists only here. The translation
    lives in this one function so no adapter below has to know both.
    """
    if result.delivered:
        return ChannelSendResult.ok()
    code = _ERROR_TRANSLATION.get(
        result.error_code.value if result.error_code else "", ChannelErrorCode.ADAPTER_UNAVAILABLE
    )
    return ChannelSendResult.failure(code)


class PanelOutboundAdapter:
    """`MANUAL`: the row **is** the delivery (D14, precedent `InAppNotificationAdapter`).

    There is nothing to send. A conversation on the `MANUAL` channel is one an operator reads
    in the panel, so what makes the reply reach anybody is the `messages` row existing and
    `GET /conversations/{id}/messages` returning it. Reporting success is therefore a true
    statement — and it is only true because that endpoint exists (R7.1). If it ever goes away,
    this adapter is a lie and must go with it.
    """

    async def send(
        self,
        *,
        channel: ConversationChannel,
        conversation_id: uuid.UUID,
        recipient_contact: str | None,
        content: str,
        language: str,
    ) -> ChannelSendResult:
        return ChannelSendResult.ok()


class PortalOutboundAdapter:
    """`PORTAL`: the row **is** the delivery, and the reader is the guest.

    A class of its own rather than a second key pointing at `PanelOutboundAdapter`, because
    each of the two names the endpoint that makes its promise true and they are different
    endpoints. What makes this reply reach anybody is the `messages` row existing and
    `GET /api/v1/guest/messages/{token}` returning it. If that endpoint ever goes away, this
    adapter is a lie and must go with it.

    It has no entry in `contact_kind_for`: the portal addresses nobody, the guest comes back
    to the page on their own.
    """

    async def send(
        self,
        *,
        channel: ConversationChannel,
        conversation_id: uuid.UUID,
        recipient_contact: str | None,
        content: str,
        language: str,
    ) -> ChannelSendResult:
        return ChannelSendResult.ok()


class InboundOnlyAdapter:
    """`PHONE_TRANSCRIPT`: messages come in, nothing goes out (R6.2, D14).

    Registered rather than omitted, and the difference from the two OTA channels is the point:
    a phone transcript is a channel this change **supports** — an operator types what the guest
    said on the phone — it just has no outbound direction. Saying so with a named code is
    better than a missing key, which would read as "we forgot".
    """

    async def send(
        self,
        *,
        channel: ConversationChannel,
        conversation_id: uuid.UUID,
        recipient_contact: str | None,
        content: str,
        language: str,
    ) -> ChannelSendResult:
        return ChannelSendResult.failure(ChannelErrorCode.CHANNEL_INBOUND_ONLY)


class DelegatingOutboundAdapter:
    """`WHATSAPP` and `EMAIL`, through the adapters `access-notifications` already governs.

    It carries `content` into the delegate's `body` and leaves `subject` unset: a chat message
    has no subject, and inventing one would put a string of ours into
    `notification_logs.subject`'s shape for no reader.
    """

    def __init__(
        self, delegate: ConsoleEmailAdapter | MockWhatsAppAdapter, channel: NotificationChannel
    ) -> None:
        self._delegate = delegate
        self._channel = channel

    async def send(
        self,
        *,
        channel: ConversationChannel,
        conversation_id: uuid.UUID,
        recipient_contact: str | None,
        content: str,
        language: str,
    ) -> ChannelSendResult:
        if recipient_contact is None or not recipient_contact.strip():
            # Checked here rather than handed to the delegate as `""`: the delegate would
            # reach the same verdict, but only by accident of it also refusing blanks.
            return ChannelSendResult.failure(ChannelErrorCode.INVALID_RECIPIENT)
        result = await self._delegate.send(
            recipient_contact=recipient_contact,
            subject=None,
            body=content,
            channel=self._channel,
        )
        return _translate(result)


def outbound_registry() -> dict[ConversationChannel, OutboundMessagePort]:
    """The channels this deployment can reply on.

    A plain dict built eagerly, rather than dynamic dispatch by channel name: the mapping is
    then visible to a reader and to `tests/messaging/test_channels.py`, and a channel with no
    adapter is a **missing key** — which the use case turns into
    `PMSChannelUnavailableError` — instead of an `ImportError` at delivery time. Same device
    as `notifications.adapter_registry`.

    `AIRBNB_MSG` and `BOOKING_MSG` are absent on purpose; see the module docstring.
    """
    return {
        ConversationChannel.MANUAL: PanelOutboundAdapter(),
        ConversationChannel.PORTAL: PortalOutboundAdapter(),
        ConversationChannel.WHATSAPP: DelegatingOutboundAdapter(
            MockWhatsAppAdapter(), NotificationChannel.WHATSAPP
        ),
        ConversationChannel.EMAIL: DelegatingOutboundAdapter(
            ConsoleEmailAdapter(), NotificationChannel.EMAIL
        ),
        ConversationChannel.PHONE_TRANSCRIPT: InboundOnlyAdapter(),
    }
