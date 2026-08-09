"""Channel adapters of PRD §14's MVP table (`access-notifications` design D5).

| Channel | Adapter | What it does |
|---|---|---|
| `EMAIL` | `ConsoleEmailAdapter` | logs a delivery record; SMTP arrives with `hardening-release` |
| `CONSOLE` | `ConsoleEmailAdapter` | same adapter, explicit channel |
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

import logging

from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.ports import NotificationAdapter
from app.notifications.domain.results import NotificationErrorCode, NotificationResult

logger = logging.getLogger(__name__)


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


def adapter_registry() -> dict[NotificationChannel, NotificationAdapter]:
    """The channels this deployment can deliver on.

    A plain dict, built eagerly, rather than dynamic import by channel name: the mapping is
    then visible to mypy and to `tests/notifications/test_adapters.py`, and a channel with
    no adapter is a *missing key* — which R4.5 turns into `SKIPPED` — instead of an
    `ImportError` at delivery time.

    `PUSH` is absent on purpose. PRD §14 lists it as "adapter placeholder (futuro)", and a
    placeholder that reports success would mark rows `SENT` that nothing ever received.
    """
    console = ConsoleEmailAdapter()
    return {
        NotificationChannel.EMAIL: console,
        NotificationChannel.CONSOLE: console,
        NotificationChannel.WHATSAPP: MockWhatsAppAdapter(),
        NotificationChannel.IN_APP: InAppNotificationAdapter(),
    }
