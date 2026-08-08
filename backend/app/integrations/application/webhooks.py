"""Receiving an unsigned webhook (`reservations-webhooks` R1, R3.4, R4; design D1, D4, D5, D7).

**The decision lives here, not in the router** (D5). `steering/backend.md` says "la lógica nunca
vive en el router", and rule 12(a)-(b) is a business rule, not transport: which token resolves
which tenant, whether the presented header matches, and what gets persisted. The router's share is
the parts that really are transport — the rate limits, the body ceiling, and turning this module's
one exception into a status code.

The concrete gain is testability. Every acceptance criterion of R1 is checked in
`tests/integrations/test_webhook_receipt.py` without FastAPI in the way, so "an unknown token, an
unknown provider, a missing header and a wrong header are indistinguishable" is asserted against
the function that decides it rather than through HTTP, where a router change could quietly make
four answers into two.

**Everything that fails, fails identically** (D4). There is one exception class, it carries no
reason, and it is raised at four different points. That is what keeps the endpoint from becoming
an oracle that confirms a token exists — see `WebhookAuthenticationError`.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.core.crypto import SecretDecryptionError, decrypt
from app.core.unit_of_work import UnitOfWork
from app.integrations.domain.entities import WebhookEvent
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.errors import WebhookAuthenticationError
from app.integrations.domain.repositories import (
    WebhookEndpointRepository,
    WebhookEventRepository,
)
from app.integrations.domain.webhook_auth import hash_webhook_token, secrets_match

CardDataScrubber = Callable[[Any], Any]
"""The card-data discard of rule 13(a), injected rather than imported.

D7 says the body is scrubbed here, before the `WebhookEvent` is built, **reusing**
`scrub_card_data` rather than growing a second scrubber — and that part is not negotiable: two
copies of a security function diverge at the first unilateral fix, which is the argument
`card_data.py`'s own docstring makes.

But that function lives in `infrastructure/`, and
`tests/test_layering.py::test_application_modules_reach_infrastructure_only_through_ports`
forbids this layer from importing a concrete adapter. Injecting it satisfies both: the use case
depends on the shape, `api/dependencies.py` supplies the one implementation. The alternative —
moving `card_data.py` into `domain/`, where a pure policy function arguably belongs — would churn
two other changes' modules for a benefit this one does not need.
"""

UNKNOWN_EVENT_TYPE = "unknown"
"""What is recorded when the body does not say what happened.

`ASSUMPTION`: the notice's own vocabulary is not settled for either provider. Channex documents an
`event` field; nothing has been measured for Beds24, whose webhooks
(`specs/pms-beds24-spike.md`) only fire for channel bookings and could not be observed without
connected channels. `event_type` is `NOT NULL` in §7.26, so a notice with no recognisable type is
recorded as this rather than refused — refusing would discard a real notice over a label, and the
body is not the source of truth anyway (D13): it says *look*, and the re-read says *what*.
"""

_EVENT_TYPE_KEYS = ("event", "event_type", "type", "action")
_EVENT_TYPE_MAX_LENGTH = 200  # `webhook_events.event_type` is String(200).


class ReceiveWebhookUseCase:
    """Authenticate one incoming notice and queue it (R1.1-R1.8, R4.1).

    Deliberately does **no** outbound call and no re-read: rule 12(d) requires the API traffic to
    be decoupled from the request volume, so this path only writes a row. The re-read is the job's,
    coalesced across the batch (D10).
    """

    def __init__(
        self,
        *,
        endpoints: WebhookEndpointRepository,
        events: WebhookEventRepository,
        scrub: CardDataScrubber,
        uow: UnitOfWork,
    ) -> None:
        self._endpoints = endpoints
        self._events = events
        # REQUIRED, with no default. A default of "do nothing" would make the PCI obligation of
        # rule 13(a) opt-in, and the one caller that forgot would persist a CVV while every test
        # here kept passing — the same argument that made `audit` a required argument of
        # `SyncReservationsFromPmsUseCase` after a panel found it defaulting to `None`.
        self._scrub = scrub
        self._uow = uow

    async def execute(
        self,
        *,
        provider: str,
        token: str,
        get_header: Callable[[str], str | None],
        payload: dict[str, Any],
        now: datetime,
    ) -> uuid.UUID:
        """The id of the queued event, or `WebhookAuthenticationError`.

        `get_header` rather than a headers mapping: the endpoint stores the header's *name*, so
        this needs to look up one it only learns at runtime, and a callable keeps the lookup
        case-insensitive on the router's side without a framework type crossing the layer boundary.

        The order is the one D5 fixes — provider, token, secret — and it is not arbitrary. Each
        step is cheaper than the next: parsing an enum costs nothing, the token lookup is one
        indexed hit, and only then is a Fernet decryption spent. A caller that fails the first
        never reaches the third.
        """
        endpoint = await self._resolve(provider, token)

        try:
            expected = decrypt(endpoint.header_secret)
        except SecretDecryptionError as error:
            # A row that cannot be decrypted authenticates nobody. It must look exactly like a
            # token that does not exist: surfacing it would tell an anonymous caller that this
            # particular route is real and its row is broken, which is the oracle D4 closes.
            raise WebhookAuthenticationError from error

        if not secrets_match(expected, get_header(endpoint.header_name)):
            # Covers the missing header and the wrong one alike (R1.3): `secrets_match` reads
            # `None` as a failure rather than raising, so both arrive here as the same `False`.
            raise WebhookAuthenticationError

        event = WebhookEvent(
            id=uuid.uuid4(),
            tenant_id=endpoint.tenant_id,
            provider=endpoint.provider.value,
            event_type=_event_type(payload),
            # **Scrubbed before it is stored, never after** (R4.1, rule 13(a), D7). Card data is
            # discarded rather than encrypted or masked, because PCI DSS forbids retaining the CVV
            # at all. The scrubbed value is what the entity is built from, so there is no moment
            # at which an unscrubbed payload exists on an object headed for the database.
            payload=self._scrub(payload),
            received_at=now,
            processed=False,
        )
        await self._events.add(event)
        await self._uow.commit()
        return event.id

    async def _resolve(self, provider: str, token: str):
        """Route token → endpoint, or the one indistinguishable failure (R1.2, R1.6, D4)."""
        try:
            known_provider = PMSProvider(provider.strip().upper())
        except ValueError as error:
            # An unsupported `{provider}` answers exactly as an unknown token does (R1.6). A
            # distinguishable answer here would let a caller enumerate which providers exist —
            # cheap information, but it is the first half of a two-part guess.
            raise WebhookAuthenticationError from error

        try:
            endpoint = await self._endpoints.find_by_token_hash(
                known_provider, hash_webhook_token(token)
            )
        except SecretDecryptionError as error:
            # The lookup itself can fail on a damaged row: `_to_endpoint` refuses to build an
            # entity whose stored secret is not Fernet ciphertext, whose `token_hash` is not a
            # digest, or whose `header_name` is blank — and it does so BEFORE this use case gets
            # anywhere near its own `decrypt`. Without this branch that surfaced as a `500` to an
            # anonymous caller, which says "this exact route is real and its material is broken":
            # the oracle D4 exists to close, reached through the repository rather than the
            # comparison. Found by the test below, not by reading.
            raise WebhookAuthenticationError from error

        if endpoint is None:
            raise WebhookAuthenticationError
        return endpoint


def _event_type(payload: dict[str, Any]) -> str:
    """A short label for what the notice claims happened, for diagnosis only.

    Never used to decide anything: D13 makes the body an advisory, so this string exists so an
    operator can read the queue, not so the job can branch on it. That is why an unrecognised
    shape is `UNKNOWN_EVENT_TYPE` instead of an error.

    Truncated to the column width rather than allowed to fail the insert: the value comes from an
    anonymous caller, and a 10 KB `event` string must not be able to abort the transaction that
    is recording the notice.
    """
    for key in _EVENT_TYPE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_EVENT_TYPE_MAX_LENGTH]
    return UNKNOWN_EVENT_TYPE
