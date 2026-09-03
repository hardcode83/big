"""Channel adapters of PRD §14's MVP table (`access-notifications` design D5).

| Channel | Adapter | What it does |
|---|---|---|
| `EMAIL` | `SMTPEmailAdapter` when `settings.smtp_host` is set, else `ConsoleEmailAdapter` | real relay delivery, or a logged record when no relay is configured (`smtp-delivery-adapter` D1) |
| `CONSOLE` | same as `EMAIL` | same adapter, explicit channel |
| `WHATSAPP` | `MockWhatsAppAdapter` | PRD §14 names it a mock for the MVP |
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

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings
from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.exceptions import SMTPConfigurationError
from app.notifications.domain.ports import NotificationAdapter
from app.notifications.domain.results import NotificationErrorCode, NotificationResult

logger = logging.getLogger(__name__)

#: Bounded so a hung relay cannot stall a scheduler tick indefinitely (R3.2).
SMTP_TIMEOUT_SECONDS = 10.0


class ConsoleEmailAdapter:
    """PRD §14: `ConsoleEmailAdapter` for a deployment with no SMTP relay configured.

    `adapter_registry()` selects this over `SMTPEmailAdapter` when `settings.smtp_host` is
    empty (R2.1, `smtp-delivery-adapter` D1) — not a placeholder pretending to send mail: it
    reports a real, verifiable outcome, the row is addressable and the delivery record
    exists in the log.
    """

    async def send(
        self,
        *,
        recipient_contact: str,
        subject: str | None,
        body: str | None,
        channel: NotificationChannel,
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


class SMTPEmailAdapter:
    """A real relay for `EMAIL`/`CONSOLE`, selected by `adapter_registry()` when
    `settings.smtp_host` is set (R1.1, `smtp-delivery-adapter` D1).

    **`ok()` means the relay accepted the message (2xx on `RCPT`/`DATA`), not that it
    reached a mailbox** (R4.1). Nothing here tracks bounces, spam complaints or read
    receipts — that is out of scope (R4.2); a future webhook-driven change would be a
    separate adapter or a separate mechanism, not more state on this one.

    Same contract as `ConsoleEmailAdapter`/`MockWhatsAppAdapter`: a blank recipient fails
    without contacting the relay (R1.2), and it never logs `recipient_contact`, `subject`
    or `body` (R1.4) — the module docstring's reasoning against logging a guest's contact
    details applies unchanged here.

    Built from the process-wide `Settings` singleton rather than constructor arguments
    (design D1): `adapter_registry()` builds a fresh dict per call with deployment-wide,
    not per-tenant, config, so there is no cached-instance/cross-tenant state to protect
    against — see D1's rejected alternative for why constructor injection was not chosen.

    The blocking `smtplib` call runs in a thread (`asyncio.to_thread`, design D3) so a slow
    relay never blocks the event loop; no third-party SMTP client.
    """

    async def send(
        self,
        *,
        recipient_contact: str,
        subject: str | None,
        body: str | None,
        channel: NotificationChannel,
    ) -> NotificationResult:
        if not recipient_contact.strip():
            return NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)
        try:
            message = EmailMessage()
            message["Subject"] = subject or ""
            message["From"] = settings.smtp_from_email
            message["To"] = recipient_contact
            message.set_content(body or "")
            await asyncio.to_thread(self._send_sync, message)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused):
            # D4: the relay refused the address, not us — the one case worth telling
            # apart from the coarse catch-all below.
            return NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)
        except TimeoutError:
            # `socket.timeout` is `TimeoutError` since Python 3.10 — this is the client's
            # own bounded `timeout=`, not a relay-reported code (D4, R3.2).
            return NotificationResult.failure(NotificationErrorCode.TIMEOUT)
        except Exception:
            # D4: every other failure — auth, connect, disconnect, protocol errors, and a
            # malformed header (`EmailMessage` rejects CR/LF in a header value before any
            # network call) — the deliberately coarse catch-all `NotificationErrorCode`
            # already declares. Never re-raised: the port's contract forbids it (`ports.py`).
            return NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR)
        return NotificationResult.ok()

    def _send_sync(self, message: EmailMessage) -> None:
        """The blocking half, run through `asyncio.to_thread` by `send` (D3).

        Never logs `message` — it carries `recipient_contact`/`subject`/`body` (R1.4).
        """
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
        ) as client:
            if settings.smtp_use_tls:
                client.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)


class MockWhatsAppAdapter:
    """PRD §14: `MockWhatsAppAdapter` for the MVP, marked `EXTERNAL_DEPENDENCY`.

    EXTERNAL_DEPENDENCY: the real one needs a WhatsApp Business account and its credentials
    (rule 8 of `sdd/steering/security.md` already reserves the variable names).

    Substitutable with the real adapter by contract (`steering/backend-architecture.md`,
    Liskov): same return type, same failure-by-value discipline, same precondition — a
    blank recipient is a failure, not an exception.
    """

    async def send(
        self,
        *,
        recipient_contact: str,
        subject: str | None,
        body: str | None,
        channel: NotificationChannel,
    ) -> NotificationResult:
        if not recipient_contact.strip():
            return NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)
        logger.info(
            "notifications.mock_whatsapp_delivered",
            extra={"channel": channel.value, "body_length": len(body or "")},
        )
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
    ) -> NotificationResult:
        if not recipient_contact.strip():
            return NotificationResult.failure(NotificationErrorCode.INVALID_RECIPIENT)
        return NotificationResult.ok()


def _email_adapter() -> NotificationAdapter:
    """`EMAIL`/`CONSOLE` selection (R2.1, R2.2; design D1, D2).

    No relay configured → `ConsoleEmailAdapter`, unchanged. `smtp_host` set → every other
    SMTP field must be non-empty too, or this raises `SMTPConfigurationError` naming the
    first one that is not — a partial config fails loud, here, at the point something is
    about to use it, never silently at import (rule 8 of `steering/security.md`).

    `smtp_use_tls` is checked last and separately from the four "empty" checks above: it is
    never empty (it is a `bool` with a default), but `False` combined with the credentials
    every other branch just proved are set is its own unsafe configuration — `client.login`
    (`_send_sync`) is unconditional on username being set, not on TLS, so `smtp_use_tls=False`
    would put `SMTP_PASSWORD` and every recipient's mail on the wire in cleartext. Refusing it
    here keeps that state unrepresentable rather than trusting an operator not to disable TLS
    on a relay that requires auth (found by the security panel of sections 1-4).
    """
    if not settings.smtp_host:
        return ConsoleEmailAdapter()
    required_fields = (
        ("smtp_port", settings.smtp_port),
        ("smtp_from_email", settings.smtp_from_email),
        ("smtp_username", settings.smtp_username),
        ("smtp_password", settings.smtp_password),
    )
    for field_name, value in required_fields:
        if not value:
            raise SMTPConfigurationError(field_name)
    if not settings.smtp_use_tls:
        raise SMTPConfigurationError("smtp_use_tls")
    return SMTPEmailAdapter()


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

    Called fresh on every use (`auth/api/dependencies.py`, `scheduler/tasks.py`) rather than
    cached, so `_email_adapter()`'s `SMTPConfigurationError` — raised, not caught here — is
    an unhandled exception on every call site until the config is fixed (design D2, R2.2):
    deliberately loud, not a background log line nobody reads.
    """
    email = _email_adapter()
    return {
        NotificationChannel.EMAIL: email,
        NotificationChannel.CONSOLE: email,
        NotificationChannel.WHATSAPP: MockWhatsAppAdapter(),
        NotificationChannel.IN_APP: InAppNotificationAdapter(),
    }
