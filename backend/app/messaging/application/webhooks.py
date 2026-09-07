"""Receiving one authenticated WhatsApp delivery (`whatsapp-cloud-adapter` R3.2-R3.5, R4.1).

**The decision lives here, not in the router**, exactly as `app/integrations/application/
webhooks.py` says for the PMS receiver and for the same reason: `steering/backend.md` puts it
plainly — "la lógica nunca vive en el router". Which secret the signature is checked against,
what a message-less body means, which tenant a `phone_number_id` resolves to, and what gets
persisted are all business rules. The router's share is transport: the two rate limits, the
status codes, and the empty body.

**`authenticate` and `record` are split for the same reason its PMS sibling splits them**, and
with one difference that matters. There, authentication never touches the body at all, so the
route can refuse before reading it. Here the body **is** the credential — Meta signs the raw
bytes with `X-Hub-Signature-256` (design D3a) — so `authenticate` necessarily consumes it. The
part of that discipline which transfers is the part that counts: `authenticate` reads no
repository, writes nothing, and cannot, because it is handed none of the collaborators that
could. R3.3's "sin escribir nada" is then a property of the call graph rather than of a caller
remembering to roll back.

**Everything that fails authentication fails identically** (R3.3). One exception class, no
reason on it, raised from one place — a missing header, a malformed one, a wrong key and a body
altered after signing are four facts and one answer. `MetaInboundAdapter.verify_signature` is
what collapses them: it returns `False` on all five of its refusing paths and never raises.

**The one case that is deliberately NOT indistinguishable** is R3.3's own amendment: a validly
signed delivery naming a `phone_number_id` no tenant has provisioned. That is an operator
halfway through setting a number up, not an adversary — nobody without the App secret can
produce one — so it is recorded where an operator can see it (the same criterion as R4.3) and
simply never dispatched, instead of being dropped or answered like a forgery.
"""

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.core.unit_of_work import UnitOfWork
from app.messaging.domain.entities import InboundWhatsAppEvent
from app.messaging.domain.exceptions import (
    NoInboundMessageError,
    WhatsAppWebhookAuthenticationError,
)
from app.messaging.domain.ports import WhatsAppInboundProviderAdapter
from app.messaging.domain.repositories import (
    WhatsAppInboundEventRepository,
    WhatsAppPhoneNumberRepository,
)

logger = logging.getLogger(__name__)


class WhatsAppDeliveryOutcome(Enum):
    """What one authenticated delivery turned out to be.

    A closed set rather than a bool, because the four outcomes are genuinely different facts
    and only one of them dispatches. The router answers `202` to all four — Meta redelivers on
    any non-2xx, so anything else would turn an ordinary delivery receipt into an infinite
    retry loop — but the tests, and the operator's log, need to tell them apart.

    Not in `domain/enums.py`: this names the shape of one use case's return value, not a value
    any entity or column holds.
    """

    #: Persisted, and `process_inbound_whatsapp_message` was dispatched for it.
    QUEUED = "QUEUED"
    #: A `provider_message_id` already recorded — the provider redelivered (R3.5). Nothing
    #: was written a second time and nothing was dispatched.
    DUPLICATE = "DUPLICATE"
    #: The body carried no message for us: a `value.statuses` receipt, an empty
    #: `entry`/`changes`/`messages`, or a non-text message (section 4's `parse` contract).
    #: Not an error, and nothing to do.
    NO_MESSAGE = "NO_MESSAGE"
    #: Validly signed, but its `phone_number_id` belongs to no tenant (R3.3 as amended).
    #: Recorded for the operator, never dispatched.
    UNPROVISIONED_NUMBER = "UNPROVISIONED_NUMBER"


@dataclass(frozen=True)
class WhatsAppDeliveryReceipt:
    """The outcome, plus the event id when there is one.

    The id is what the caller's tests assert against and what the log line names; it is `None`
    for `NO_MESSAGE`, where no row exists at all.
    """

    outcome: WhatsAppDeliveryOutcome
    event_id: uuid.UUID | None = None


class ReceiveWhatsAppWebhookUseCase:
    """Authenticate a Meta delivery, then record and dispatch it. Two steps, in that order.

    `dispatch` is a plain callable rather than a port with a class behind it, and it is
    supplied by the composition root (`app/messaging/api/dependencies.py`) for the reason
    `ReceiveWebhookUseCase` is handed `scrub`: `application/` may not import a concrete
    adapter (`tests/test_layering.py`), and Celery is a concrete adapter — it may only be
    imported by `app/worker.py` and `app/scheduler/**`, which the same test enforces. So the
    task is injected as a function, and this module never learns that a broker exists.

    That injection is also what makes "queued **after** the commit" structural rather than
    remembered: `dispatch` is called on the line after `uow.commit()`, in one place, and a
    worker that picked the id up before the transaction landed would read no row.
    """

    def __init__(
        self,
        *,
        provider: WhatsAppInboundProviderAdapter,
        secret: str,
        phone_numbers: WhatsAppPhoneNumberRepository,
        events: WhatsAppInboundEventRepository,
        dispatch: Callable[[uuid.UUID], None],
        uow: UnitOfWork,
    ) -> None:
        self._provider = provider
        self._secret = secret
        self._phone_numbers = phone_numbers
        self._events = events
        self._dispatch = dispatch
        self._uow = uow

    def authenticate(self, *, raw_body: bytes, headers: Mapping[str, str], url: str) -> None:
        """Raise `WhatsAppWebhookAuthenticationError` unless Meta's signature verifies (R3.2).

        **Synchronous on purpose.** It is an HMAC over bytes already in memory — no I/O, no
        session, no await — and marking it `async` would suggest there is a round trip here
        that a reviewer should worry about ordering against.

        `secret` comes from the wiring, which is where `settings.whatsapp_provider` selects
        (task 7.1): under any provider but `meta` it is `""`, and section 4's adapter answers
        `False` for a blank key, so a deployment with no WhatsApp refuses every delivery.

        `raw_body` must be the **exact** bytes that arrived. Re-serialising a parsed body
        changes key order and separators and therefore invalidates a perfectly valid
        signature; section 4's notes pin this, and it is why this method takes `bytes` and the
        router calls `await request.body()` rather than `.json()`.

        `url` is passed through to the port because the port declares it. Meta's signature
        covers the body alone, and the adapter ignores it by contract.
        """
        if not self._provider.verify_signature(
            raw_body=raw_body, headers=headers, secret=self._secret, url=url
        ):
            raise WhatsAppWebhookAuthenticationError()

    async def record(
        self, *, raw_body: bytes, headers: Mapping[str, str], now: datetime
    ) -> WhatsAppDeliveryReceipt:
        """Interpret an **already authenticated** body, persist it, and dispatch its work.

        Called only after `authenticate` returned, and it does not re-check: a second check
        would be a second place the secret is read and a second answer to invent when they
        disagree. The ordering is the router's one obligation and its test pins it.

        `now` is not written to the row — `received_at` is Meta's own instant and
        `created_at` is the database's — but it is threaded through so nothing here reads the
        process clock, the standing rule for every use case in this codebase.
        """
        try:
            message = self._provider.parse(raw_body=raw_body, headers=headers)
        except NoInboundMessageError:
            # Ordinary, high-volume traffic and not a fault: Meta posts delivery and read
            # receipts to this very URL (`value.statuses`), and a non-text message has no
            # `text.body` for this change's pipeline to classify. Nothing is written, and the
            # router answers `202` — anything else and every receipt of our own outbound
            # replies would retry for ever and spend the route's rate-limit budget on us.
            logger.info("messaging.whatsapp_webhook_nothing_to_do")
            return WhatsAppDeliveryReceipt(outcome=WhatsAppDeliveryOutcome.NO_MESSAGE)

        # R4.1: the tenant is resolved from the delivery metadata Meta attaches, against the
        # provisioning table — never from the route (there is none, R3.1) and never from a
        # field the sender controls. This is the only lookup in the method, and
        # `business_phone_number` is the only field of `message` it is given.
        association = await self._phone_numbers.find_by_phone_number_id(
            message.business_phone_number
        )

        event = InboundWhatsAppEvent(
            id=uuid.uuid4(),
            tenant_id=None if association is None else association.tenant_id,
            default_property_id=(
                None if association is None else association.default_property_id
            ),
            message=message,
        )
        inserted = await self._events.add(event)
        await self._uow.commit()

        if not inserted:
            # R3.5: the provider redelivered something already accepted. The row that exists
            # is the first delivery's, and its task was dispatched then; dispatching again
            # here would be the duplicate the unique index just prevented.
            logger.info(
                "messaging.whatsapp_webhook_duplicate_delivery",
                # No phone number and no message text — rule 11 of `steering/security.md`,
                # and this line is written on a route the open internet can reach.
                extra={"phone_number_id": message.business_phone_number},
            )
            return WhatsAppDeliveryReceipt(outcome=WhatsAppDeliveryOutcome.DUPLICATE)

        if not event.is_resolved:
            # R3.3 as amended: signed correctly, but nobody has provisioned this number. Not
            # adversarial — producing this requires the App secret — so it is recorded and
            # made loud rather than dropped or answered like a forgery. `warning` and not
            # `info`: there is an operator action behind it (associate the number, section 6),
            # and until they take it every message to that number sits here unanswered.
            logger.warning(
                "messaging.whatsapp_webhook_unprovisioned_number",
                extra={
                    "phone_number_id": message.business_phone_number,
                    "event_id": str(event.id),
                },
            )
            return WhatsAppDeliveryReceipt(
                outcome=WhatsAppDeliveryOutcome.UNPROVISIONED_NUMBER, event_id=event.id
            )

        # AFTER the commit, and the order is the requirement (design D7, task 7.5): the worker
        # is a different process on a different connection, so an id handed over before the
        # transaction landed is an id that resolves to no row.
        self._dispatch(event.id)
        return WhatsAppDeliveryReceipt(
            outcome=WhatsAppDeliveryOutcome.QUEUED, event_id=event.id
        )
