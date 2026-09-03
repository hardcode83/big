"""Channel adapters of PRD §14's MVP table (`access-notifications` design D5), plus the real
WhatsApp Cloud API adapter that `whatsapp-cloud-adapter` (design D1) adds in its place.

| Channel | Adapter | What it does |
|---|---|---|
| `EMAIL` | `ConsoleEmailAdapter` | logs a delivery record; SMTP arrives with `hardening-release` |
| `CONSOLE` | `ConsoleEmailAdapter` | same adapter, explicit channel |
| `WHATSAPP` | `WhatsAppCloudAdapter` (real) or `MockWhatsAppAdapter` (`WHATSAPP_PROVIDER=mock`) | Meta Cloud API, or a mock preserving the old MVP behaviour |
| `IN_APP` | `InAppNotificationAdapter` | no-op: the row **is** the delivery |
| `PUSH` | — | deliberately unregistered; R4.5 sends it to `SKIPPED` |

**Nothing here logs `subject`, `body` or `recipient_contact`.** The first two are the one
carrier rule 11 of `sdd/steering/security.md` lets an access code through in masked form,
and an application log is not a sink that contract covers — it has no retention policy, no
tenant scoping and no audit.

The **address** went the same way, and it is worth saying why, because an earlier version
logged it and the security panel of sections 1-2 had to point it out: every argument the
paragraph above makes against logging the body applies unchanged to the recipient. Today
that field holds a staff email; from R2 onwards it holds the **guest's**, because the access
instructions of PRD §15 go out on these channels. A log line per delivery is then a
per-tenant directory of guest contact details, assembled by the one component that had just
finished refusing to log the message itself.

What is left is what an operator debugging delivery actually needs: which row, which channel,
and how big the message was.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.ports import NotificationAdapter
from app.notifications.domain.results import NotificationErrorCode, NotificationResult

logger = logging.getLogger(__name__)

# A named constant, not a literal spliced into the URL each call (task 1.3): the version
# Meta expects in the path segment of every Graph API request this adapter makes.
WHATSAPP_GRAPH_API_VERSION = "v21.0"
WHATSAPP_GRAPH_API_BASE_URL = "https://graph.facebook.com"

# Meta's window: a business may free-text a user for 24h after that user's last message: msg.
# https://developers.facebook.com/docs/whatsapp/pricing#conversations (customer service window).
WHATSAPP_SESSION_WINDOW = timedelta(hours=24)

# Meta's template send requires a `language.code` (BCP-47) and nothing richer than a
# `template_id` is in scope for this section — real per-template language selection is left
# for whoever wires actual approved templates (see `## Implementation Notes` at the bottom of
# `tasks.md`).
WHATSAPP_DEFAULT_TEMPLATE_LANGUAGE_CODE = "es"

WHATSAPP_REQUEST_TIMEOUT_SECONDS = 10.0


class ConsoleEmailAdapter:
    """PRD §14: `ConsoleEmailAdapter` in dev, SMTP in prod.

    The SMTP half is out of scope here (`hardening-release` owns settings and integrations),
    and this is not a placeholder pretending to be one: it reports a real, verifiable
    outcome — the row is addressable and the delivery record exists in the log.
    """

    async def send(
        self,
        *,
        recipient_contact: str,
        subject: str | None,
        body: str | None,
        channel: NotificationChannel,
        last_inbound_at: datetime | None = None,
        template_id: str | None = None,
        phone_number_id: str | None = None,
    ) -> NotificationResult:
        if not recipient_contact.strip():
            return NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)
        logger.info(
            "notifications.console_email_delivered",
            extra={
                "channel": channel.value,
                # Lengths, not content, and no address — see the module docstring. The row
                # this belongs to is logged by the dispatcher, which is the layer that knows
                # its id and its tenant.
                "subject_length": len(subject or ""),
                "body_length": len(body or ""),
            },
        )
        return NotificationResult.ok()


class MockWhatsAppAdapter:
    """`WHATSAPP_PROVIDER=mock`: the MVP behaviour, preserved for a deployment with no WhatsApp
    Business account (`whatsapp-cloud-adapter` design D1, R1.5).

    Until `whatsapp-cloud-adapter`, this docstring claimed rule 8 of
    `sdd/steering/security.md` "already reserved" the WhatsApp variable names — it did not:
    no such names existed anywhere in `app/core/config.py` or `.env.example`. They are real
    now (`WHATSAPP_PROVIDER`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
    `WHATSAPP_APP_SECRET`), and `WhatsAppCloudAdapter` below is what reads the credential
    ones. This class reads none of them: `mock` mode never touches Meta.

    Substitutable with `WhatsAppCloudAdapter` by contract (`steering/backend-architecture.md`,
    Liskov): same return type, same failure-by-value discipline, same precondition — a blank
    recipient is a failure, not an exception. It also accepts the same `last_inbound_at`,
    `template_id` and `phone_number_id` keywords the port now carries, and ignores all three:
    R1.5 is "preserve today's behaviour", not "simulate the session window or per-tenant
    number", so every send that clears the blank-recipient check still succeeds.
    """

    async def send(
        self,
        *,
        recipient_contact: str,
        subject: str | None,
        body: str | None,
        channel: NotificationChannel,
        last_inbound_at: datetime | None = None,
        template_id: str | None = None,
        phone_number_id: str | None = None,
    ) -> NotificationResult:
        if not recipient_contact.strip():
            return NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)
        logger.info(
            "notifications.mock_whatsapp_delivered",
            extra={"channel": channel.value, "body_length": len(body or "")},
        )
        return NotificationResult.ok()


class WhatsAppCloudAdapter:
    """The real `WHATSAPP` adapter: Meta's WhatsApp Cloud API (`whatsapp-cloud-adapter`
    design D1/D2, R1.1, R1.4, R2.1-R2.3).

    One Graph API call per `send`, `POST /{version}/{phone_number_id}/messages`, Bearer
    auth. Substitutable with `MockWhatsAppAdapter` by contract
    (`steering/backend-architecture.md`, Liskov): same return type, no exception ever
    escapes `send`, and a blank recipient is a failure, not an exception — checked before any
    network call.

    **The 24h session window is decided here, not by the caller** (design D2): Meta silently
    drops a free-text send outside the window, so this adapter must refuse it itself rather
    than let that happen invisibly.

    - Inside the window (`last_inbound_at` is set and no more than `WHATSAPP_SESSION_WINDOW`
      old): `text` message, `body` sent verbatim.
    - Outside it — **including `last_inbound_at is None`**, which this adapter treats as "no
      known inbound message" and therefore OUTSIDE, never as an invitation to send free text
      anyway. `app/notifications/application/use_cases.py`'s `_deliver` never passes
      `last_inbound_at` at all, so every notifications-side WhatsApp send lands here by
      construction (R2.3) — a proactive notification needs a `template_id` or it fails
      loudly instead of the provider dropping it silently.
    - With a `template_id` and outside the window: `template` message, `language.code`
      hardcoded to `WHATSAPP_DEFAULT_TEMPLATE_LANGUAGE_CODE` — real per-template language
      selection is out of scope here (see `tasks.md`'s Implementation Notes).
    - With neither: `NotificationResult.failure(NotificationErrorCode.OUTSIDE_SESSION_WINDOW)`,
      no network call at all.

    **`phone_number_id`, per call, overrides the constructor's number** (design D1 addendum,
    D4's `business_phone_number` addendum): AutoHostAI provisions one WhatsApp number per
    tenant, so a guest's reply must leave from the same number the guest wrote to. When the
    caller passes one, it replaces `self._phone_number_id` for that one Graph API call only —
    the constructor's value, and every other adapter state, is untouched. When omitted or
    `None`, behaviour is exactly what it was before this kwarg existed: the constructor's
    `phone_number_id` is used, which is the platform default for proactive notifications with
    no guest conversation (and therefore no per-guest number) behind them.

    Nothing the provider says reaches the return value or a log line with `recipient`/`body`
    attached — same sink discipline as every other adapter in this module (rule 11 of
    `sdd/steering/security.md`, module docstring above). A non-2xx Graph API response becomes
    `ADAPTER_ERROR`; a timeout or connection failure becomes `TIMEOUT`. Both are logged with
    the HTTP status (or exception class name) only.
    """

    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not access_token.strip() or not phone_number_id.strip():
            # A configuration mistake caught before any request exists, the same way
            # `Beds24Client.__init__` refuses an empty refresh token — `adapter_registry()`
            # only reaches this branch when `WHATSAPP_PROVIDER=meta`, and `config.py`'s own
            # validators already fail the app at boot before this constructor runs, so this
            # is defence in depth, not the primary guard.
            raise ValueError(
                "WhatsAppCloudAdapter requires a non-blank access token and phone number id"
            )
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        # Same shape as `Beds24Client._transport`/`ChannexClient`: `None` in production means
        # `httpx.AsyncClient` opens a real connection, and the test suite supplies an
        # `httpx.MockTransport` so `tests/notifications/` never touches the network
        # (`steering/testing.md` — mock at the adapter boundary, real Graph API shape,
        # offline).
        self._transport = transport

    async def send(
        self,
        *,
        recipient_contact: str,
        subject: str | None,
        body: str | None,
        channel: NotificationChannel,
        last_inbound_at: datetime | None = None,
        template_id: str | None = None,
        phone_number_id: str | None = None,
    ) -> NotificationResult:
        if not recipient_contact.strip():
            return NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)

        effective_phone_number_id = phone_number_id or self._phone_number_id

        within_window = (
            last_inbound_at is not None
            and (datetime.now(UTC) - last_inbound_at) <= WHATSAPP_SESSION_WINDOW
        )

        if within_window:
            payload: dict[str, object] = {
                "messaging_product": "whatsapp",
                "to": recipient_contact,
                "type": "text",
                "text": {"body": body or ""},
            }
        elif template_id:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient_contact,
                "type": "template",
                "template": {
                    "name": template_id,
                    "language": {"code": WHATSAPP_DEFAULT_TEMPLATE_LANGUAGE_CODE},
                },
            }
        else:
            return NotificationResult.failure(NotificationErrorCode.OUTSIDE_SESSION_WINDOW)

        url = (
            f"{WHATSAPP_GRAPH_API_BASE_URL}/{WHATSAPP_GRAPH_API_VERSION}/"
            f"{effective_phone_number_id}/messages"
        )
        try:
            async with httpx.AsyncClient(
                timeout=WHATSAPP_REQUEST_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
        except httpx.TimeoutException:
            logger.warning(
                "notifications.whatsapp_cloud_send_timeout", extra={"channel": channel.value}
            )
            return NotificationResult.failure(NotificationErrorCode.TIMEOUT)
        except httpx.HTTPError as error:
            # Everything else httpx can raise for a request that never got a response at all
            # (DNS, connection refused, TLS) — never let it escape `send` (port contract).
            logger.warning(
                "notifications.whatsapp_cloud_send_failed",
                extra={"channel": channel.value, "error_type": type(error).__name__},
            )
            return NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR)

        if response.status_code // 100 != 2:
            # Graph API's error body has `error.code`/`error.message`, and per this module's
            # own rule (docstring above, rule 11): never put provider text — or the recipient —
            # into the log or the result. The status code is enough for an operator to look
            # this up in Meta's own error reference.
            logger.warning(
                "notifications.whatsapp_cloud_send_rejected",
                extra={"channel": channel.value, "status_code": response.status_code},
            )
            return NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR)

        return NotificationResult.ok()


class InAppNotificationAdapter:
    """The in-app channel, where **the row is the delivery** (design D5).

    There is nothing to send: PRD §14 defines in-app as "Notification entity + API polling",
    so what makes the notification reach its recipient is the row existing and
    `GET /api/v1/notifications` returning it. Marking it `SENT` is therefore a true
    statement — and it is only true because that endpoint exists (design D6). If the
    endpoint ever goes away, this adapter is a lie and must go with it.

    Still refuses a row with no recipient: `recipient_user_id` is what the read endpoint
    filters by, and a row nobody can be shown is not delivered.
    """

    async def send(
        self,
        *,
        recipient_contact: str,
        subject: str | None,
        body: str | None,
        channel: NotificationChannel,
        last_inbound_at: datetime | None = None,
        template_id: str | None = None,
        phone_number_id: str | None = None,
    ) -> NotificationResult:
        if not recipient_contact.strip():
            return NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)
        return NotificationResult.ok()


def adapter_registry() -> dict[NotificationChannel, NotificationAdapter]:
    """The channels this deployment can deliver on.

    A plain dict, built eagerly, rather than dynamic import by channel name: the mapping is
    then visible to mypy and to `tests/notifications/test_adapters.py`, and a channel with
    no adapter is a *missing key* — which R4.5 turns into `SKIPPED` — instead of an
    `ImportError` at delivery time.

    `PUSH` is absent on purpose. PRD §14 lists it as "adapter placeholder (futuro)", and a
    placeholder that reports success would mark rows `SENT` that nothing ever received.
    `tests/notifications/test_adapters.py` pins `PUSH not in registry` directly; this
    function is untouched by `notification-channel-routing` (R6.2), so the AST guard of
    `test_channel_literals.py` does not require it to name every enum member the way the
    resolver and dispatcher do.

    `WHATSAPP` reads `settings.whatsapp_provider` directly rather than taking it as an
    argument (`whatsapp-cloud-adapter` design D1, R1.1, R1.5): this function stays
    no-argument, which is the call `scheduler/tasks.py` and `auth/api/dependencies.py` (its
    three current callers) already make, and none of them needs to change.
    """
    console = ConsoleEmailAdapter()
    whatsapp: NotificationAdapter
    if settings.whatsapp_provider == "meta":
        whatsapp = WhatsAppCloudAdapter(
            access_token=settings.whatsapp_access_token or "",
            phone_number_id=settings.whatsapp_phone_number_id or "",
        )
    else:
        whatsapp = MockWhatsAppAdapter()
    return {
        NotificationChannel.EMAIL: console,
        NotificationChannel.CONSOLE: console,
        NotificationChannel.WHATSAPP: whatsapp,
        NotificationChannel.IN_APP: InAppNotificationAdapter(),
    }
