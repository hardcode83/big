"""Draining the webhook queue into reservations (R5.1-R5.7, R6.1-R6.4, D10-D14).

Integration against real Postgres, because what is being proven is mostly about rows: which
notices a run selects, which it marks, and what the ingest left behind. The one collaborator
that is faked is the PMS itself — a test that reached a provider would not be a test.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import (
    WEBHOOK_SOURCE,
    SyncReservationsFromPmsUseCase,
)
from app.integrations.application.webhooks import (
    ProcessTenantWebhookEventsUseCase,
    ProcessWebhookEventsUseCase,
    TenantWebhookOutcome,
)
from app.integrations.domain.entities import (
    MAX_WEBHOOK_ATTEMPTS,
    QueuedWebhookEvent,
)
from app.integrations.application.webhooks import RE_READ_LOOKBACK
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.errors import PmsUnavailableError
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError
from app.integrations.infrastructure.mock_pms import SEED_PROPERTY_CODE, MockPMSAdapter
from app.integrations.infrastructure.models import WebhookEventModel
from app.integrations.infrastructure.repositories import SqlAlchemyWebhookEventRepository
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.domain.enums import TimelineActorType
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


class _Factory:
    """A `PMSAdapterFactory` over a per-provider map, recording every resolution.

    `calls` is what the coalescing assertions read: one entry per `reservations_for`, which is
    one entry per outbound conversation with a provider.
    """

    def __init__(self, adapters: dict[PMSProvider, object]) -> None:
        self._adapters = adapters
        self.calls: list[PMSProvider] = []

    def supports_messaging(self, provider) -> bool:
        return False

    def provider_for(self, property):
        return property.pms_provider or PMSProvider.MOCK

    async def reservations_for(self, property, *, read_log):
        provider = self.provider_for(property)
        self.calls.append(provider)
        outcome = self._adapters[provider]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def messaging_for(self, property):
        raise AssertionError("the webhook job must never resolve messaging")


class _CountingAdvancer:
    """Stands in for `AdvancePropertyStatesUseCase` (D12: it is invoked, never modified)."""

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, object]] = []

    async def execute(self, *, tenant_id, trigger, now):
        self.calls.append((tenant_id, trigger))
        return None


def _tenant_use_case(
    db_session: AsyncSession, factory: _Factory, advance: _CountingAdvancer
) -> ProcessTenantWebhookEventsUseCase:
    return ProcessTenantWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        sync=SyncReservationsFromPmsUseCase(
            factory=factory,
            reservations=SqlAlchemyReservationRepository(db_session),
            properties=SqlAlchemyPropertyRepository(db_session),
            guests=SqlAlchemyGuestRepository(db_session),
            timeline=SqlAlchemyTimelineEventRepository(db_session),
            uow=SqlAlchemyUnitOfWork(db_session),
            audit=SqlAlchemyAuditLogRepository(db_session),
        ),
        advance=advance,
        uow=SqlAlchemyUnitOfWork(db_session),
    )


async def _notice(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    provider: str = "MOCK",
    received_at: datetime = NOW,
    attempts: int = 0,
) -> QueuedWebhookEvent:
    event = WebhookEventModel(
        tenant_id=tenant_id,
        provider=provider,
        event_type="booking.modified",
        payload={"reservation_id": "the job must not read this"},
        received_at=received_at,
        attempts=attempts,
    )
    session.add(event)
    await session.flush()
    return QueuedWebhookEvent(
        id=event.id,
        tenant_id=tenant_id,
        provider=provider,
        received_at=received_at,
        attempts=attempts,
    )


async def _beds24_property(session: AsyncSession, tenant_id: uuid.UUID) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant_id,
        name="Beds24 flat",
        internal_code="B24-1",
        pms_external_id="PMS-B24",
        pms_provider=PMSProvider.BEDS24,
    )
    session.add(prop)
    await session.flush()
    return prop


# --- The re-read turns notices into reservations (R5.1, R5.2, R6.1) --------------------------


@pytest.mark.asyncio
async def test_a_notice_becomes_reservations_through_the_ingestor(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """R5.2: `ReservationIngestor` is the single upsert route, reached by re-reading (R6.1)."""
    notice = await _notice(db_session, tenant_id=tenant_a.id)
    factory = _Factory({PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False)})

    outcome = await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=[notice], now=NOW
    )

    assert outcome == TenantWebhookOutcome(processed=1, failed=0)
    ingested = (
        await db_session.execute(
            select(ReservationModel.external_pms_id).where(
                ReservationModel.tenant_id == tenant_a.id
            )
        )
    ).scalars().all()
    assert ingested, "the re-read produced no reservation at all"
    row = await db_session.get(WebhookEventModel, notice.id)
    await db_session.refresh(row)
    assert row.processed is True
    assert row.processed_at == NOW


@pytest.mark.asyncio
async def test_the_ingest_timeline_event_carries_the_webhook_as_its_cause(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """R5.6's first half and D12: the causality lives on the ingest's own `TimelineEvent`.

    Actor `WEBHOOK` here and NOT on the transition, which keeps `property_state_transitions`
    free of an actor rule 9 names only in order to exclude it from the audit exemption.
    """
    notice = await _notice(db_session, tenant_id=tenant_a.id)
    factory = _Factory({PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False)})

    await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=[notice], now=NOW
    )

    events = (
        await db_session.execute(
            select(TimelineEventModel).where(TimelineEventModel.tenant_id == tenant_a.id)
        )
    ).scalars().all()
    assert events
    assert {event.actor_type for event in events} == {TimelineActorType.WEBHOOK}
    assert {event.metadata_["source"] for event in events} == {WEBHOOK_SOURCE}


@pytest.mark.asyncio
async def test_the_transition_goes_through_the_use_case_that_already_owns_it(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """R5.6's second half, D12. This change is the first production caller of the trigger."""
    from app.properties.domain.transition_enums import PropertyStateTrigger

    notice = await _notice(db_session, tenant_id=tenant_a.id)
    advance = _CountingAdvancer()

    await _tenant_use_case(
        db_session,
        _Factory({PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False)}),
        advance,
    ).execute(tenant_id=tenant_a.id, events=[notice], now=NOW)

    assert advance.calls == [
        (tenant_a.id, PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN)
    ]


@pytest.mark.asyncio
async def test_nothing_is_advanced_when_no_notice_landed(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """A provider that could not be reached leaves the portfolio untouched: re-evaluating it
    would be work provoked by a notice that produced no data."""
    notice = await _notice(db_session, tenant_id=tenant_a.id)
    advance = _CountingAdvancer()
    factory = _Factory({PMSProvider.MOCK: PmsUnavailableError("down")})

    outcome = await _tenant_use_case(db_session, factory, advance).execute(
        tenant_id=tenant_a.id, events=[notice], now=NOW
    )

    assert outcome == TenantWebhookOutcome(processed=0, failed=1)
    assert advance.calls == []


# --- Isolation: per event and per tenant (R5.4) ----------------------------------------------


@pytest.mark.asyncio
async def test_one_providers_failure_does_not_cost_the_other_its_notices(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """R5.4 per event: two notices, two providers, one provider down."""
    await _beds24_property(db_session, tenant_a.id)
    healthy = await _notice(db_session, tenant_id=tenant_a.id, provider="MOCK")
    broken = await _notice(db_session, tenant_id=tenant_a.id, provider="BEDS24")
    factory = _Factory(
        {
            PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False),
            PMSProvider.BEDS24: PmsUnavailableError("no adapter"),
        }
    )

    outcome = await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=[healthy, broken], now=NOW
    )

    assert outcome == TenantWebhookOutcome(processed=1, failed=1)
    landed = await db_session.get(WebhookEventModel, healthy.id)
    failed = await db_session.get(WebhookEventModel, broken.id)
    await db_session.refresh(landed)
    await db_session.refresh(failed)
    assert landed.processed is True
    assert failed.processed is False
    assert failed.attempts == 1
    assert failed.error == '{"code":"PROVIDER_UNAVAILABLE"}'


@pytest.mark.asyncio
async def test_a_notice_naming_an_unknown_provider_fails_alone(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """`webhook_events.provider` is free-form (§7.26), so an unserviceable value is a data
    state and not a bug — and it must not take the batch down with it."""
    good = await _notice(db_session, tenant_id=tenant_a.id, provider="MOCK")
    strange = await _notice(db_session, tenant_id=tenant_a.id, provider="octorate")
    factory = _Factory({PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False)})

    outcome = await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=[good, strange], now=NOW
    )

    assert outcome == TenantWebhookOutcome(processed=1, failed=1)
    row = await db_session.get(WebhookEventModel, strange.id)
    await db_session.refresh(row)
    assert row.error == '{"code":"PROVIDER_UNAVAILABLE","field":"provider"}'
    # Retried, not exhausted: a provider this system does not serve today may be one it serves
    # tomorrow, and `attempts = 3` would make that unrecoverable without hand-written SQL.
    assert row.attempts == 1


@pytest.mark.asyncio
async def test_a_tenant_whose_run_failed_does_not_stop_the_others(
    db_session: AsyncSession, tenant_a, tenant_b
) -> None:
    """R5.4 per tenant, at the batch use case's own boundary.

    The runner reports a rolled-back tenant as `None`, and the batch use case then owes those
    notices a retry recorded on ITS session — the failed tenant's is gone.
    """
    broken = await _notice(db_session, tenant_id=tenant_a.id)
    survivor = await _notice(db_session, tenant_id=tenant_b.id)
    await db_session.commit()
    seen: list[uuid.UUID] = []

    async def run_for_tenant(tenant_id, events, now):
        seen.append(tenant_id)
        if tenant_id == tenant_a.id:
            return None
        return TenantWebhookOutcome(processed=len(events))

    report = await ProcessWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        run_for_tenant=run_for_tenant,
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(now=NOW)

    assert set(seen) == {tenant_a.id, tenant_b.id}
    assert report.tenants == 2
    assert report.processed == 1
    assert report.failed == 1
    charged = await db_session.get(WebhookEventModel, broken.id)
    await db_session.refresh(charged)
    assert charged.attempts == 1
    assert charged.next_attempt_at == NOW + timedelta(minutes=1)
    assert survivor.id is not None


# --- The unattributed branch (R1.8, D11) -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_notice_without_a_tenant_is_exhausted_rather_than_retried(
    db_session: AsyncSession, tenant_a
) -> None:
    """D11: there is no tenant to attribute a reservation to, so the next attempt would fail
    identically. It is spent at once — visible for diagnosis, never selected again."""
    orphan = await _notice(db_session, tenant_id=None)
    await db_session.commit()

    async def run_for_tenant(tenant_id, events, now):
        return TenantWebhookOutcome(processed=len(events))

    report = await ProcessWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        run_for_tenant=run_for_tenant,
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(now=NOW)

    assert report.unattributed == 1
    assert report.tenants == 0
    row = await db_session.get(WebhookEventModel, orphan.id)
    await db_session.refresh(row)
    assert row.attempts == MAX_WEBHOOK_ATTEMPTS
    assert row.error == '{"code":"UNATTRIBUTED","field":"tenant_id"}'
    assert (
        await SqlAlchemyWebhookEventRepository(db_session).select_pending(now=NOW, limit=10)
        == []
    )


@pytest.mark.asyncio
async def test_an_empty_queue_costs_nothing(db_session: AsyncSession) -> None:
    async def run_for_tenant(tenant_id, events, now):
        raise AssertionError("nothing was selected, so nothing may run")

    report = await ProcessWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        run_for_tenant=run_for_tenant,
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(now=NOW)

    assert report.selected == 0
    assert report.tenants == 0


@pytest.mark.asyncio
async def test_the_batch_splits_by_tenant(
    db_session: AsyncSession, tenant_a, tenant_b
) -> None:
    """R5.5: each tenant's notices are handed over as one group, so each gets exactly one
    marked session rather than one per notice."""
    await _notice(db_session, tenant_id=tenant_a.id)
    await _notice(db_session, tenant_id=tenant_a.id)
    await _notice(db_session, tenant_id=tenant_b.id)
    await db_session.commit()
    handed: dict[uuid.UUID, int] = {}

    async def run_for_tenant(tenant_id, events, now):
        handed[tenant_id] = handed.get(tenant_id, 0) + len(events)
        return TenantWebhookOutcome(processed=len(events))

    report = await ProcessWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        run_for_tenant=run_for_tenant,
        uow=SqlAlchemyUnitOfWork(db_session),
    ).execute(now=NOW)

    assert handed == {tenant_a.id: 2, tenant_b.id: 1}
    assert report.selected == 3
    assert report.processed == 3


# --- Coalescing: the call count follows the cadence, not the traffic (R6.1-R6.3, D10) --------


@pytest.mark.asyncio
async def test_many_notices_for_one_provider_cost_one_call(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """R6.2 and D10: the batch IS the coalescing window, so no second clock is needed.

    Twenty notices is the shape rule 12(d) exists for — an anonymous caller who found the route
    and is hammering it. What must not scale with that number is the outbound call.
    """
    notices = [await _notice(db_session, tenant_id=tenant_a.id) for _ in range(20)]
    factory = _Factory({PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False)})

    outcome = await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=notices, now=NOW
    )

    assert factory.calls == [PMSProvider.MOCK]
    assert outcome == TenantWebhookOutcome(processed=20, failed=0)


@pytest.mark.asyncio
async def test_two_destinations_cost_one_call_each(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """One call per DISTINCT destination per execution — not one per notice, not one for all."""
    await _beds24_property(db_session, tenant_a.id)
    notices = [
        await _notice(db_session, tenant_id=tenant_a.id, provider="MOCK"),
        await _notice(db_session, tenant_id=tenant_a.id, provider="MOCK"),
        await _notice(db_session, tenant_id=tenant_a.id, provider="BEDS24"),
        await _notice(db_session, tenant_id=tenant_a.id, provider="BEDS24"),
    ]
    factory = _Factory(
        {
            PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False),
            PMSProvider.BEDS24: MockPMSAdapter(include_broken_rows=False),
        }
    )

    await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=notices, now=NOW
    )

    assert sorted(factory.calls, key=lambda p: p.value) == [
        PMSProvider.BEDS24,
        PMSProvider.MOCK,
    ]


@pytest.mark.asyncio
async def test_a_provider_the_batch_did_not_name_is_not_called(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """`providers` is what keeps one provider's notice from spending another's quota.

    Without it the re-read would sync the tenant's whole portfolio on every tick that any
    notice arrived, which is the coupling between request volume and outbound traffic that
    rule 12(d) forbids — just displaced onto a provider that was never mentioned.
    """
    await _beds24_property(db_session, tenant_a.id)
    notice = await _notice(db_session, tenant_id=tenant_a.id, provider="MOCK")
    factory = _Factory(
        {
            PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False),
            PMSProvider.BEDS24: AssertionError("BEDS24 named no notice in this batch"),
        }
    )

    await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=[notice], now=NOW
    )

    assert factory.calls == [PMSProvider.MOCK]


@pytest.mark.asyncio
async def test_receiving_a_webhook_makes_no_outbound_call(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """R6.3, from the outside: the receiving route reaches no provider, synchronously or at all.

    Asserted over the whole receiving path rather than by inspecting the router, because R6.3 is
    a property of the ROUTE and a call could be smuggled in through any collaborator it wires.
    What proves it is that the request leaves a queued notice and nothing else — no reservation,
    no timeline event, which is all a re-read could possibly have produced.

    The client is built here, with the throttle overridden, rather than taken from the `api`
    fixture — the convention `test_webhook_receiver_api.py` states in its own docstring. The real
    throttle would pull in `app.core.redis.get_redis`, whose process-wide memoisation binds a
    connection pool to the FIRST event loop that touches it; pytest-asyncio gives each test its
    own loop, so a later test using the real throttle dies with "Event loop is closed" in
    teardown. Nothing here is about rate limiting.
    """
    from httpx import ASGITransport, AsyncClient

    from app.core.crypto import encrypt
    from app.core.db import get_db_session
    from app.integrations.api.dependencies import get_webhook_throttle
    from app.integrations.domain.webhook_auth import (
        generate_header_secret,
        generate_webhook_token,
        hash_webhook_token,
    )
    from app.integrations.infrastructure.models import WebhookEndpointModel
    from app.main import create_app

    class _AllowAll:
        async def probe_allowed(self, client_ip: str) -> bool:
            return True

        async def delivery_allowed(self, token_hash: str) -> bool:
            return True

        async def record_failed_attempt(self, client_ip: str) -> None:
            return None

    token = generate_webhook_token()
    secret = generate_header_secret()
    db_session.add(
        WebhookEndpointModel(
            tenant_id=tenant_a.id,
            provider=PMSProvider.MOCK,
            token_hash=hash_webhook_token(token),
            header_name="X-Provider-Auth",
            header_secret_encrypted=encrypt(secret).ciphertext,
        )
    )
    await db_session.flush()

    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_webhook_throttle] = _AllowAll

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/webhooks/mock/{token}",
            json={"event": "booking.modified"},
            headers={"X-Provider-Auth": secret},
        )

    assert response.status_code == 202
    queued = (
        await db_session.execute(
            select(WebhookEventModel.id).where(WebhookEventModel.tenant_id == tenant_a.id)
        )
    ).scalars().all()
    assert len(queued) == 1
    for model in (ReservationModel, TimelineEventModel):
        produced = (
            await db_session.execute(
                select(model.id).where(model.tenant_id == tenant_a.id)
            )
        ).scalars().all()
        assert produced == [], f"{model.__tablename__} was written on the receiving path"


# --- The re-read's credential audit is reused, not rebuilt (R6.4, D14) -----------------------


@pytest.mark.asyncio
async def test_one_account_credential_serving_two_properties_is_audited_once(
    db_session: AsyncSession, tenant_a
) -> None:
    """R6.4 through the REAL factory, because the granularity is what is being checked.

    The formulation lives in one place — the second named exception of rule 9 in
    `steering/security.md` — and this change writes no second implementation of it (D14). What
    this proves is that the reuse actually reaches it: two properties on one account credential,
    one execution, one row. `BEDS24` has no adapter yet, so the run also fails the notice, and
    that is the harder half of the case: the credential was decrypted BEFORE the failure, so a
    trail that only recorded successes would be missing precisely the read that happened.
    """
    from app.audit.domain.actions import ENTITY_PMS_CREDENTIAL, PMS_CREDENTIAL_READ
    from app.audit.infrastructure.models import AuditLogModel
    from app.core.crypto import encrypt
    from app.integrations.domain.entities import PmsCredential
    from app.integrations.domain.enums import PmsCredentialScope
    from app.integrations.infrastructure.pms_factory import SqlAlchemyPMSAdapterFactory
    from app.integrations.infrastructure.repositories import (
        SqlAlchemyPmsCredentialRepository,
    )

    await _beds24_property(db_session, tenant_a.id)
    second = PropertyModel(
        tenant_id=tenant_a.id,
        name="Beds24 flat two",
        internal_code="B24-2",
        pms_external_id="PMS-B24-2",
        pms_provider=PMSProvider.BEDS24,
    )
    db_session.add(second)
    credential = PmsCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        provider=PMSProvider.BEDS24,
        scope=PmsCredentialScope.ACCOUNT,
        secret=encrypt("refresh-token"),
    )
    await SqlAlchemyPmsCredentialRepository(db_session).upsert(tenant_a.id, credential)
    await db_session.flush()
    notice = await _notice(db_session, tenant_id=tenant_a.id, provider="BEDS24")

    use_case = ProcessTenantWebhookEventsUseCase(
        queue=SqlAlchemyWebhookEventRepository(db_session),
        sync=SyncReservationsFromPmsUseCase(
            factory=SqlAlchemyPMSAdapterFactory(
                credentials=SqlAlchemyPmsCredentialRepository(db_session)
            ),
            reservations=SqlAlchemyReservationRepository(db_session),
            properties=SqlAlchemyPropertyRepository(db_session),
            guests=SqlAlchemyGuestRepository(db_session),
            timeline=SqlAlchemyTimelineEventRepository(db_session),
            uow=SqlAlchemyUnitOfWork(db_session),
            audit=SqlAlchemyAuditLogRepository(db_session),
        ),
        advance=_CountingAdvancer(),
        uow=SqlAlchemyUnitOfWork(db_session),
    )
    outcome = await use_case.execute(tenant_id=tenant_a.id, events=[notice], now=NOW)

    assert outcome == TenantWebhookOutcome(processed=0, failed=1)
    rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == PMS_CREDENTIAL_READ)
        )
    ).scalars().all()
    assert len(rows) == 1, "two properties on one account credential is still one read"
    assert rows[0].entity_type == ENTITY_PMS_CREDENTIAL
    assert rows[0].entity_id == credential.id
    # Rule 9's own wording: these rows go without an actor, and the webhook job has no more of
    # one than the command does.
    assert rows[0].actor_user_id is None
    assert rows[0].actor_ip is None


@pytest.mark.asyncio
async def test_the_re_read_window_starts_before_the_oldest_notice(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """A notice announces a change that already happened, so `since` cannot be the notice's own
    `received_at` — that would ask the provider for everything changed AFTER the change."""
    seen: list[datetime] = []

    class _RecordingAdapter:
        async def list_reservations(self, since, property_external_id=None):
            seen.append(since)
            return await MockPMSAdapter(include_broken_rows=False).list_reservations(
                since, property_external_id
            )

        async def get_reservation(self, external_id):
            return None

    oldest = NOW - timedelta(minutes=30)
    first = await _notice(db_session, tenant_id=tenant_a.id, received_at=oldest)
    second = await _notice(db_session, tenant_id=tenant_a.id, received_at=NOW)

    await _tenant_use_case(
        db_session, _Factory({PMSProvider.MOCK: _RecordingAdapter()}), _CountingAdvancer()
    ).execute(tenant_id=tenant_a.id, events=[first, second], now=NOW)

    # The EXACT anchor, not merely "earlier than the oldest notice". With the notices 30
    # minutes apart and a 1 h lookback, `since < oldest` holds just as well when anchored on
    # the NEWEST notice, so the looser assertion could not tell `min` from `max` — which is
    # precisely the selection D10 specifies. The QA panel of this section caught that.
    assert seen == [oldest - RE_READ_LOOKBACK]
    assert SEED_PROPERTY_CODE == property_a.pms_external_id


@pytest.mark.asyncio
async def test_each_destination_gets_its_own_window(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """D10 anchors the lookback on the oldest notice **of the group**, and the group is the
    destination.

    A shared anchor would widen one provider's window because a *different* provider happened
    to have an older notice in the same tick — the volume coupling of rule 12(d), displaced
    from the call count onto the window width. Found by the architecture panel of this section.
    """
    await _beds24_property(db_session, tenant_a.id)
    seen: dict[PMSProvider, list[datetime]] = {}

    class _RecordingFor:
        def __init__(self, provider: PMSProvider) -> None:
            self._provider = provider

        async def list_reservations(self, since, property_external_id=None):
            seen.setdefault(self._provider, []).append(since)
            return await MockPMSAdapter(include_broken_rows=False).list_reservations(
                since, property_external_id
            )

        async def get_reservation(self, external_id):
            return None

    ancient = NOW - timedelta(days=2)
    old_mock = await _notice(
        db_session, tenant_id=tenant_a.id, provider="MOCK", received_at=ancient
    )
    fresh_beds24 = await _notice(
        db_session, tenant_id=tenant_a.id, provider="BEDS24", received_at=NOW
    )
    factory = _Factory(
        {
            PMSProvider.MOCK: _RecordingFor(PMSProvider.MOCK),
            PMSProvider.BEDS24: _RecordingFor(PMSProvider.BEDS24),
        }
    )

    await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=[old_mock, fresh_beds24], now=NOW
    )

    assert seen[PMSProvider.MOCK] == [ancient - RE_READ_LOOKBACK]
    # The two-day-old MOCK notice must not drag BEDS24's window back with it.
    assert seen[PMSProvider.BEDS24] == [NOW - RE_READ_LOOKBACK]


@pytest.mark.asyncio
async def test_an_unresolvable_property_costs_only_its_own_destination(
    db_session: AsyncSession, tenant_a, property_a
) -> None:
    """R5.4, for the branch the QA panel of this section demonstrated was broken.

    `AmbiguousPropertyExternalIdError` escapes `_sync_one_provider`'s own try, so while the
    re-read was one call carrying every provider, one provider's duplicate `pms_external_id`
    marked EVERY other provider's notices failed — and re-marked them on every tick until a
    person fixed the duplicate. Re-reading per destination is what confines it.
    """
    await _beds24_property(db_session, tenant_a.id)
    healthy = await _notice(db_session, tenant_id=tenant_a.id, provider="MOCK")
    ambiguous = await _notice(db_session, tenant_id=tenant_a.id, provider="BEDS24")

    class _AmbiguousAdapter:
        async def list_reservations(self, since, property_external_id=None):
            raise AmbiguousPropertyExternalIdError(
                tenant_id=tenant_a.id, pms_external_id="PMS-B24"
            )

        async def get_reservation(self, external_id):
            return None

    factory = _Factory(
        {
            PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False),
            PMSProvider.BEDS24: _AmbiguousAdapter(),
        }
    )

    outcome = await _tenant_use_case(db_session, factory, _CountingAdvancer()).execute(
        tenant_id=tenant_a.id, events=[healthy, ambiguous], now=NOW
    )

    assert outcome == TenantWebhookOutcome(processed=1, failed=1)
    landed = await db_session.get(WebhookEventModel, healthy.id)
    blocked = await db_session.get(WebhookEventModel, ambiguous.id)
    await db_session.refresh(landed)
    await db_session.refresh(blocked)
    assert landed.processed is True
    assert landed.error is None
    assert blocked.processed is False
    assert blocked.error == '{"code":"UNMAPPABLE","field":"property.pms_external_id"}'
