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

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.crypto import SecretDecryptionError, decrypt
from app.core.unit_of_work import UnitOfWork
from app.integrations.application.use_cases import (
    WEBHOOK_SOURCE,
    SyncReservationsFromPmsUseCase,
)
from app.integrations.domain.entities import (
    PROVIDER_UNAVAILABLE,
    UNATTRIBUTED,
    UNMAPPABLE,
    QueuedWebhookEvent,
    WebhookEndpoint,
    WebhookEvent,
    WebhookEventFailure,
    webhook_retry_delay,
)
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.errors import WebhookAuthenticationError
from app.integrations.domain.ports import PropertyStateAdvancer
from app.integrations.domain.repositories import (
    WebhookEndpointRepository,
    WebhookEventRepository,
)
from app.integrations.domain.webhook_auth import hash_webhook_token, secrets_match
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.timeline.domain.enums import TimelineActorType

logger = logging.getLogger(__name__)

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

    async def authenticate(
        self,
        *,
        provider: str,
        token: str,
        get_header: Callable[[str], str | None],
    ) -> WebhookEndpoint:
        """The endpoint this request proved it holds, or `WebhookAuthenticationError`.

        **Separate from `record` because the body must not be touched to answer this** (R1.7:
        "rechazar la petición ANTES de leer el cuerpo completo cuando la autenticación falla"), and
        because the delivery counter must only be charged to a caller that authenticated — see the
        router. The security panel of section 2 found both: the body was parsed first, and anyone
        holding only the route token could spend a tenant's whole per-minute budget.

        `get_header` rather than a headers mapping: the endpoint stores the header's *name*, so
        this needs to look up one it only learns at runtime, and a callable keeps the lookup
        case-insensitive on the router's side without a framework type crossing the layer boundary.

        The order is the one D5 fixes — provider, token, secret — and it is not arbitrary. Each
        step is cheaper than the next: parsing an enum costs nothing, the token lookup is one
        indexed hit, and only then is a Fernet decryption spent. A caller that fails the first
        never reaches the third. Everything here reads the route and the headers only.
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

        return endpoint

    async def record(
        self,
        *,
        endpoint: WebhookEndpoint,
        payload: dict[str, Any],
        now: datetime,
    ) -> uuid.UUID:
        """Queue an ALREADY AUTHENTICATED notice, and return its id.

        Takes the endpoint rather than the token: by the time this runs the caller has proved it
        holds both secrets, and re-resolving would be a second lookup answering a question already
        answered. It also makes it impossible to record against an endpoint nobody authenticated.
        """
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

    async def execute(
        self,
        *,
        provider: str,
        token: str,
        get_header: Callable[[str], str | None],
        payload: dict[str, Any],
        now: datetime,
    ) -> uuid.UUID:
        """Authenticate and queue, in one call.

        The whole operation, for callers that have the body in hand already — which is every test
        of R1 and would be the router too, were it not for the two things that have to happen
        *between* the halves: charging the delivery counter only to an authenticated caller, and
        not reading the body until then. Kept so the receiving rule can be exercised end to end
        without reproducing the router's ordering in every test.
        """
        endpoint = await self.authenticate(
            provider=provider, token=token, get_header=get_header
        )
        return await self.record(endpoint=endpoint, payload=payload, now=now)

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


DEFAULT_BATCH_SIZE = 500
"""How many notices one execution may take on.

It bounds the DATABASE work of a tick, not the outbound calls — those are bounded by the
grouping of D10 and stay at one per destination however large this is. A ceiling exists so a
backlog drains over several ticks instead of one execution holding a transaction open across
thousands of rows; 500 is comfortably above the cadence's expected arrival rate, so in ordinary
operation the batch is the whole queue.
"""

RE_READ_LOOKBACK = timedelta(hours=1)
"""How far BEFORE the oldest notice in the group the re-read window starts.

`ASSUMPTION`, and the reason it cannot be zero: a notice announces a change that already
happened, so its `received_at` is strictly *after* the modification it reports. Anchoring
`since` on the notice itself would ask the provider for everything changed since a moment after
the change — excluding the very reservation the notice exists to point at.

The margin has to cover the provider's delivery latency, and **that latency is unmeasured**:
`sdd/roadmap/beds24-webhook-cutover-measurement.md` names it as one of the three things its
measurement exists to establish. An hour is generous against any plausible delivery delay and
cheap against the cost that matters — the number of outbound CALLS is fixed by D10 and does not
move with the window. Revisit when the measurement lands.
"""


@dataclass
class WebhookProcessingReport:
    """What one execution of `process_webhook_events` did, in terms an operator can act on."""

    selected: int = 0
    processed: int = 0
    failed: int = 0
    unattributed: int = 0
    tenants: int = 0
    skipped_locked: bool = False
    """The previous run is still going, so this one did nothing (`celery-jobs` R4.2).

    The same field name `TenantRunReport` uses, deliberately: an operator reading worker logs
    should not have to learn a second word for the same event because a different job produced
    the line.
    """


@dataclass
class TenantWebhookOutcome:
    """One tenant's slice of a run. Returned so the batch report can add it up."""

    processed: int = 0
    failed: int = 0


TenantBatchRunner = Callable[
    [uuid.UUID, list[QueuedWebhookEvent], datetime],
    Awaitable[TenantWebhookOutcome | None],
]
"""Runs one tenant's notices inside a session marked for that tenant (R5.5, D11).

Injected rather than imported, for the reason every session concern is: opening one is
`infrastructure/`'s job, and `app/scheduler/runner.py` already owns the "one marked session per
tenant, never re-marked" pattern this reuses.

`None` means that tenant's whole transaction failed and was rolled back — the runner's own
failure boundary. The batch use case then owes those notices a retry, recorded on ITS session,
because the tenant's is gone.
"""


class ProcessWebhookEventsUseCase:
    """Drain the queue: read the batch unmarked, split it by tenant, delegate (R5.1, R5.4, R5.5).

    **Reads from a session that was never marked, and that is a correctness requirement rather
    than a convention** (D11): `webhook_events.tenant_id` is nullable, and a marked session's
    global filter hides the `NULL` rows without erroring — the rows this use case exists to
    exhaust.

    It does no re-reading and no ingesting itself. Everything that touches a tenant's data
    happens on that tenant's own marked session, one tenant at a time, which is where
    `ProcessTenantWebhookEventsUseCase` runs.
    """

    def __init__(
        self,
        *,
        queue: WebhookEventRepository,
        run_for_tenant: TenantBatchRunner,
        uow: UnitOfWork,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._queue = queue
        self._run_for_tenant = run_for_tenant
        self._uow = uow
        self._batch_size = batch_size

    async def execute(self, *, now: datetime) -> WebhookProcessingReport:
        batch = await self._queue.select_pending(now=now, limit=self._batch_size)
        report = WebhookProcessingReport(selected=len(batch))
        if not batch:
            return report

        by_tenant: dict[uuid.UUID, list[QueuedWebhookEvent]] = {}
        unattributed: list[QueuedWebhookEvent] = []
        for event in batch:
            if event.tenant_id is None:
                unattributed.append(event)
            else:
                by_tenant.setdefault(event.tenant_id, []).append(event)

        if unattributed:
            # D11's honest branch. R1's authentication is what makes this unreachable — the
            # token is what resolves the tenant — but §7.26 allows the row, so the code says
            # what happens to one rather than pretending it cannot exist. The whole retry
            # budget goes at once because no amount of retrying invents a tenant: the notice
            # stays visible for diagnosis and is never selected again.
            await self._queue.exhaust(
                [event.id for event in unattributed],
                failure=WebhookEventFailure(code=UNATTRIBUTED, field="tenant_id"),
            )
            await self._uow.commit()
            report.unattributed = len(unattributed)
            report.failed += len(unattributed)
            logger.warning(
                "webhooks.unattributed_notices_exhausted",
                extra={"count": len(unattributed)},
            )

        for tenant_id, events in by_tenant.items():
            report.tenants += 1
            outcome = await self._run_for_tenant(tenant_id, events, now)
            if outcome is None:
                # That tenant's transaction rolled back, so nothing it might have written to
                # the queue survived either. The retry is recorded here, on a session that is
                # still alive — otherwise a tenant whose run died would keep being selected
                # with `attempts` frozen at its old value, which is a poisoned notice with no
                # ceiling (R5.3).
                await _schedule_retry(
                    self._queue,
                    events,
                    failure=WebhookEventFailure(code=PROVIDER_UNAVAILABLE),
                    now=now,
                )
                await self._uow.commit()
                report.failed += len(events)
                continue
            report.processed += outcome.processed
            report.failed += outcome.failed
        return report


class ProcessTenantWebhookEventsUseCase:
    """One tenant's notices, on a session already marked for that tenant (R5.2, R5.6, R6.1-R6.4).

    **The body of the notice is never consulted** (D13). What a notice contributes is its
    `provider`, and what that buys is a *destination*: every notice naming the same provider is
    served by ONE re-read (D10), so N notices between two ticks cost one outbound call and the
    call count is bounded by the cadence rather than by how many requests a stranger sent us.
    `QueuedWebhookEvent` carries no payload at all, so this is structural.

    **The re-read is `SyncReservationsFromPmsUseCase`, unchanged in substance** (D14). That is
    where `ReservationIngestor` is fed as the single upsert route (R5.2), where the per-provider
    isolation lives, and where the credential-read audit already implements the granularity that
    the second named exception of rule 9 authorises. Writing a second one here would be a second
    implementation of a rule that has exactly one formulation.
    """

    def __init__(
        self,
        *,
        queue: WebhookEventRepository,
        sync: SyncReservationsFromPmsUseCase,
        advance: PropertyStateAdvancer,
        uow: UnitOfWork,
    ) -> None:
        self._queue = queue
        self._sync = sync
        self._advance = advance
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        events: Sequence[QueuedWebhookEvent],
        now: datetime,
    ) -> TenantWebhookOutcome:
        known, unknown = _by_provider(events)
        outcome = TenantWebhookOutcome()

        if unknown:
            # `webhook_events.provider` is a free-form column (§7.26 types it VARCHAR because
            # the set of providers is open), so a value no adapter can serve is a data state,
            # not a bug. It fails ALONE — this is the per-event isolation of R5.4 at its most
            # literal — and it is retried rather than exhausted, because the provider it names
            # may be one this system learns tomorrow.
            await _schedule_retry(
                self._queue,
                unknown,
                failure=WebhookEventFailure(code=PROVIDER_UNAVAILABLE, field="provider"),
                now=now,
            )
            outcome.failed += len(unknown)

        if known:
            await self._reread(tenant_id=tenant_id, known=known, now=now, outcome=outcome)

        await self._uow.commit()
        return outcome

    async def _reread(
        self,
        *,
        tenant_id: uuid.UUID,
        known: dict[PMSProvider, list[QueuedWebhookEvent]],
        now: datetime,
        outcome: TenantWebhookOutcome,
    ) -> None:
        since = (
            min(event.received_at for group in known.values() for event in group)
            - RE_READ_LOOKBACK
        )
        try:
            report = await self._sync.execute(
                tenant_id=tenant_id,
                since=since,
                now=now,
                # ONLY the providers this batch named. Without it a notice from one provider
                # would spend another's quota on every tick, which is the opposite of what
                # rule 12(d) asks for.
                providers=set(known),
                actor_type=TimelineActorType.WEBHOOK,
                source=WEBHOOK_SOURCE,
            )
        except AmbiguousPropertyExternalIdError:
            # Two properties of one provider share a `pms_external_id`. The re-read happened;
            # what failed is resolving its result onto a home, which is what `UNMAPPABLE`
            # names. Retried rather than exhausted because a person can fix the duplicate.
            await _schedule_retry(
                self._queue,
                [event for group in known.values() for event in group],
                failure=WebhookEventFailure(
                    code=UNMAPPABLE, field="property.pms_external_id"
                ),
                now=now,
            )
            outcome.failed += sum(len(group) for group in known.values())
            return

        failed_providers = {value.upper() for value in report.provider_failures}
        landed: list[QueuedWebhookEvent] = []
        for provider, group in known.items():
            if provider.value.upper() in failed_providers:
                await _schedule_retry(
                    self._queue,
                    group,
                    failure=WebhookEventFailure(code=PROVIDER_UNAVAILABLE),
                    now=now,
                )
                outcome.failed += len(group)
            else:
                landed.extend(group)

        if not landed:
            return

        # R5.6 and D12: the transition is performed by the use case that already owns it,
        # unmodified, so it carries actor `SYSTEM` and writes its `PropertyStateTransition`
        # and its `TimelineEvent` in one transaction. This change introduces no new transition
        # actor; the causality lives one step earlier, on the ingest's own `TimelineEvent`,
        # which the re-read above wrote with actor `WEBHOOK`.
        #
        # Once per tenant, not once per notice: the use case re-evaluates the whole portfolio
        # against the trigger, so calling it again per notice would repeat the same query for
        # an answer that cannot have changed.
        await self._advance.execute(
            tenant_id=tenant_id,
            trigger=PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN,
            now=now,
        )
        await self._queue.mark_processed([event.id for event in landed], now=now)
        outcome.processed += len(landed)


def _by_provider(
    events: Sequence[QueuedWebhookEvent],
) -> tuple[dict[PMSProvider, list[QueuedWebhookEvent]], list[QueuedWebhookEvent]]:
    """Split the notices into the ones naming a provider we can serve, and the rest.

    Parsed exactly as the receiving path parses the route's `{provider}`, so a notice recorded
    through the front door always resolves here.
    """
    known: dict[PMSProvider, list[QueuedWebhookEvent]] = {}
    unknown: list[QueuedWebhookEvent] = []
    for event in events:
        try:
            provider = PMSProvider(event.provider.strip().upper())
        except ValueError:
            unknown.append(event)
            continue
        known.setdefault(provider, []).append(event)
    return known, unknown


async def _schedule_retry(
    queue: WebhookEventRepository,
    events: Sequence[QueuedWebhookEvent],
    *,
    failure: WebhookEventFailure,
    now: datetime,
) -> None:
    """Charge one attempt to each notice and set its own next slot (R5.3).

    Grouped by CURRENT `attempts` rather than issued per notice: the backoff is a function of
    how many times that particular notice has already failed, so two notices in the same group
    with different histories must not be given the same slot. In practice this is one or two
    statements, because a group's notices usually share a history.
    """
    by_attempts: dict[int, list[uuid.UUID]] = {}
    for event in events:
        by_attempts.setdefault(event.attempts, []).append(event.id)
    for attempts, event_ids in by_attempts.items():
        await queue.record_failure(
            event_ids,
            failure=failure,
            next_attempt_at=now + webhook_retry_delay(attempts + 1),
        )


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
