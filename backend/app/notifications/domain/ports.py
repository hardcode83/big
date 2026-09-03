"""The delivery port of PRD §14 (`access-notifications` design D3, D5).

`app/notifications/domain/repositories.py` states that sending "is not here and will not
be" — this is where it landed. The split it describes is the whole architecture of this
module: a writer queues a row in `PENDING`, and delivery is a separate pass that owns
`status`.

**`async`, unlike the PRD's signature.** PRD §14 declares `def send(...)`, but every layer
of this backend is `async` and a real SMTP or HTTP adapter would block the event loop for
the duration of a network round trip — inside a Celery worker that is drenching a batch,
that serialises the batch. Arguments and semantics are the PRD's; only the colour of the
function changed, and it is stated here rather than discovered later.
"""

from datetime import datetime
from typing import Protocol

from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.results import NotificationResult


class NotificationAdapter(Protocol):
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
        """Deliver one notification, and **never raise for a delivery failure**.

        A provider that refuses, times out or rejects the address is an expected outcome,
        not an exception: it comes back as `NotificationResult.failure(...)` so the caller
        can record `attempts` and `last_error` and try again next tick. Reserve exceptions
        for programming errors.

        This is also where rule 11 of `sdd/steering/security.md` is enforced by
        construction: whatever the provider said comes back as a `NotificationErrorCode`,
        so the text it embedded — routinely the very message that failed to send — has
        nowhere to travel. See `results.py`.

        `subject` and `body` are nullable because the column is
        (`notification_logs.subject`/`body` are both optional): a channel that needs them
        and receives `None` answers `INVALID_RECIPIENT`-style with its own code rather than
        inventing content.

        `last_inbound_at` and `template_id` exist for WhatsApp's 24h session window
        (`whatsapp-cloud-adapter` design D2, R2.1-R2.4). Both default to `None` so every
        adapter that predates the window (`ConsoleEmailAdapter`, `InAppNotificationAdapter`)
        is unaffected — they simply never receive anything but the default. An adapter that
        does not implement a session window (every channel but `WHATSAPP` today) ignores
        both. **`last_inbound_at=None` means "no known inbound message" and is treated as
        OUTSIDE the window, not as licence to send free text** — a caller with no timestamp
        to offer must either not claim one or pass `template_id` instead; see
        `WhatsAppCloudAdapter.send` for the resolved semantics.

        `phone_number_id` exists because AutoHostAI's WhatsApp integration is one phone
        number per tenant, not one global platform number (`whatsapp-cloud-adapter` design
        D1 addendum, D4's `business_phone_number` addendum): a reply has to leave from the
        same number the guest wrote to. Defaults to `None`, meaning "use the adapter's own
        constructor-configured number" — the platform default used for proactive
        notifications that have no guest conversation (and therefore no per-guest number)
        behind them. An adapter without a per-call notion of origin number ignores it.
        """
        ...
