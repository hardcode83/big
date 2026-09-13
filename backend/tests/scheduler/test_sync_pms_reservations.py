"""The periodic PMS re-sync (`pms-sync-schedule` R1, R2, R3, R5; design D4/D16).

Thin like every other task in `app/scheduler/tasks.py`, so what is worth testing here is the
wiring, not `SyncReservationsFromPmsUseCase` itself — that use case's own behaviour (provider
grouping, idempotent upsert, provider-failure isolation) is `tests/integrations/test_sync.py`'s
subject.

**Two things are only true here, and each is tested against something that can fail — the
same split `test_generate_price_recommendations.py` documents and this file copies.**

The first is `since`: this job must derive it from `settings.pms_sync_window_days`, not the
30-day default `app/integrations/cli/pms_sync.py` uses for a manual run, and it must tag the
resulting `TimelineEvent`s with `SCHEDULED_SOURCE` rather than `PMS_SOURCE` — both silent if
wrong, so both are asserted against a real ingest rather than a mock.

The second is the per-tenant sweep, and it has the exact same trap `generate_price_
recommendations` had: the Celery task reaches the database through
`worker_session_factory()`, built from `settings.database_url` — the **dev** database, which
`tests/conftest.py` deliberately does not touch. That database has no tenants, so
`run_for_every_tenant` never enters its loop and any assertion on the report of a real task
call is vacuous. So the loop is tested with the tenant list stubbed, and the wiring the loop
invokes is tested directly against the real test-database session.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.db import bind_session_to_tenant
from app.integrations.application.use_cases import PMS_SOURCE, SCHEDULED_SOURCE
from app.integrations.cli.pms_sync import DEFAULT_WINDOW_DAYS
from app.integrations.domain.dtos import PmsFetchResult, ReservationDTO
from app.integrations.domain.enums import PMSProvider
from app.integrations.infrastructure.mock_pms import SEED_PROPERTY_CODE
from app.properties.domain.enums import PropertyOperationalState
from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.scheduler import runner
from app.scheduler.locks import lock_ttl_for, task_lock
from app.scheduler.schedule import CADENCES
from app.scheduler.tasks import _sync_pms_reservations, sync_pms_reservations
from app.timeline.domain.enums import TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel

from tests.auth.conftest import insert_tenant

TASK_NAME = "sync_pms_reservations"

NOW = datetime(2026, 6, 10, 8, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def redis():
    """Own client per test, same reasoning as `test_locks.py` / `test_generate_price_
    recommendations.py`."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def worker_sessions(test_engine, monkeypatch):
    """`test_runner.py`'s fixture: point the runner's own factory at the test database
    instead of the dev one `worker_session_factory()` resolves in production."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(runner, "_session_factory", factory)
    return factory


def _mock_property(tenant_id: uuid.UUID, *, code: str) -> PropertyModel:
    return PropertyModel(
        tenant_id=tenant_id,
        name=f"{code} flat",
        internal_code=code,
        pms_external_id=SEED_PROPERTY_CODE,
    )


# --- Mitad 1: the wiring, against the real test session --------------------------------


@pytest.mark.asyncio
async def test_since_is_derived_from_the_settings_window_and_not_the_cli_default(
    db_session,
) -> None:
    """R1/R3: the scheduled sweep's `since` is `settings.pms_sync_window_days`, never the
    manual CLI's 30-day default.

    `MockPMSAdapter._seed` builds its two reservations off `since.date()`, so the dates
    landing on the `Reservation` row are a real signal of what `since` the job actually
    computed — not a mock assertion on a call that never happened.
    """
    tenant = await insert_tenant(db_session, name="pms-since-tenant")
    db_session.add(_mock_property(tenant.id, code="PMSSINCE-1"))
    await db_session.commit()
    bind_session_to_tenant(db_session, tenant.id)

    outcome = await _sync_pms_reservations(db_session, tenant.id, NOW)

    assert outcome.created == 2

    expected_since_date = (NOW - timedelta(days=settings.pms_sync_window_days)).date()
    wrong_cli_since_date = (NOW - timedelta(days=DEFAULT_WINDOW_DAYS)).date()
    assert expected_since_date != wrong_cli_since_date, "the two windows must differ for this test to mean anything"

    reservation = await db_session.scalar(
        select(ReservationModel).where(ReservationModel.check_out_date == expected_since_date + timedelta(days=1))
    )
    assert reservation is not None
    assert reservation.check_in_date == expected_since_date - timedelta(days=2)
    # The CLI's own 30-day window would have landed a different date here — asserted
    # explicitly so a regression that silently swapped in `DEFAULT_WINDOW_DAYS` fails loud.
    assert reservation.check_in_date != wrong_cli_since_date - timedelta(days=2)


@pytest.mark.asyncio
async def test_the_resulting_timeline_events_are_tagged_scheduled_not_manual_or_webhook(
    db_session,
) -> None:
    """R3: the scheduled sweep's `TimelineEvent`s must say "the schedule came round", not
    "an operator ran the CLI" (`PMS_SOURCE`) and not "a webhook told us" (`WEBHOOK_SOURCE`)."""
    tenant = await insert_tenant(db_session, name="pms-source-tenant")
    db_session.add(_mock_property(tenant.id, code="PMSSOURCE-1"))
    await db_session.commit()
    bind_session_to_tenant(db_session, tenant.id)

    outcome = await _sync_pms_reservations(db_session, tenant.id, NOW)
    assert outcome.created == 2

    events = (
        await db_session.execute(
            select(TimelineEventModel).where(
                TimelineEventModel.event_type == TimelineEventType.RESERVATION_IMPORTED
            )
        )
    ).scalars().all()

    assert len(events) == 2
    assert {event.metadata_["source"] for event in events} == {SCHEDULED_SOURCE}
    assert PMS_SOURCE not in {event.metadata_["source"] for event in events}


# --- The property transition the sweep now triggers (`pms-ingest-change-events` R3.3) --
#
# Wiring again, and only wiring: whether a cancellation frees a flat is
# `AdvancePropertyStatesUseCase`'s own subject and `tests/properties/` its home. What is only
# true HERE is that `_sync_pms_reservations` supplies that collaborator at all — it did not
# before this change, so the periodic sweep could learn a booking had been cancelled and leave
# the flat waiting for a guest who was never coming.


class _FeedAdapter:
    """A provider answering the sweep with exactly the rows the test names."""

    def __init__(self, *rows: ReservationDTO) -> None:
        self._rows = list(rows)

    async def list_reservations(self, since, property_external_id=None) -> PmsFetchResult:
        return PmsFetchResult(reservations=list(self._rows), failures=[])

    async def get_reservation(self, external_id):
        return None


class _FeedFactory:
    """Stands in for `SqlAlchemyPMSAdapterFactory`, structurally (the port is a Protocol).

    Only the factory is replaced. Everything the job wires below it — the repositories, the
    two units of work, the advancer of `_nested_advance` — stays real, which is the point: a
    stub of the sync use case would pass whether or not the collaborator was supplied.
    """

    def __init__(self, adapter: _FeedAdapter) -> None:
        self._adapter = adapter

    def supports_messaging(self, provider) -> bool:
        return False

    def provider_for(self, property):
        return PMSProvider.MOCK

    async def reservations_for(self, property, *, read_log=None):
        return self._adapter

    async def messaging_for(self, property):
        raise AssertionError("the sync must never resolve messaging")


CANCELLED_EXTERNAL_ID = "SCHED-CANCEL-1"


def _stay(status: str) -> ReservationDTO:
    """A stay checking in the day after `NOW`, so it is still *before* check-in."""
    return ReservationDTO(
        external_id=CANCELLED_EXTERNAL_ID,
        channel="AIRBNB",
        property_external_id=SEED_PROPERTY_CODE,
        check_in_date=date(2026, 6, 11),
        check_out_date=date(2026, 6, 14),
        check_in_time=time(15, 0),
        check_out_time=time(11, 0),
        guest_name="Ada Lovelace",
        adults=2,
        status=status,
    )


def _feed(monkeypatch, status: str) -> None:
    monkeypatch.setattr(
        "app.scheduler.tasks.SqlAlchemyPMSAdapterFactory",
        lambda **kwargs: _FeedFactory(_FeedAdapter(_stay(status))),
    )


@pytest.mark.asyncio
async def test_a_cancellation_the_sweep_discovers_frees_the_property(
    db_session, monkeypatch
) -> None:
    """R3.1/R3.3 through `_sync_pms_reservations`'s own composition root.

    Two sweeps: the first creates the booking and must move nothing, the second reports it
    CANCELLED. The flat lands in `VACANT_READY` with exactly one `PropertyStateTransition`
    row — and it can only get there through the `advance=` this job now passes.
    """
    tenant = await insert_tenant(db_session, name="pms-cancel-tenant")
    prop = _mock_property(tenant.id, code="PMSCANCEL-1")
    prop.current_operational_state = PropertyOperationalState.AWAITING_CHECKIN
    db_session.add(prop)
    await db_session.commit()
    bind_session_to_tenant(db_session, tenant.id)

    _feed(monkeypatch, "CONFIRMED")
    created = await _sync_pms_reservations(db_session, tenant.id, NOW)
    assert created.created == 1
    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN

    _feed(monkeypatch, "CANCELLED")
    outcome = await _sync_pms_reservations(db_session, tenant.id, NOW)

    assert outcome.updated == 1
    await db_session.refresh(prop)
    assert prop.current_operational_state is PropertyOperationalState.VACANT_READY
    transitions = (
        await db_session.execute(
            select(PropertyStateTransitionModel).where(
                PropertyStateTransitionModel.property_id == prop.id
            )
        )
    ).scalars().all()
    assert len(transitions) == 1
    assert transitions[0].to_state is PropertyOperationalState.VACANT_READY
    reservation = await db_session.scalar(
        select(ReservationModel).where(
            ReservationModel.external_pms_id == CANCELLED_EXTERNAL_ID
        )
    )
    assert reservation.status is ReservationStatus.CANCELLED


# --- Mitad 2: the lock and the per-tenant sweep, tenant list stubbed -------------------


def test_the_lock_ttl_is_the_cadence_times_three(monkeypatch) -> None:
    """R1.3: the TTL that actually reaches `task_lock`, not the constant in `CADENCES`.

    Against the real dev database (empty of tenants), the same posture `test_generate_
    price_recommendations.py`'s TTL test takes: the tenant loop finding nothing proves
    nothing about the TTL, which is computed before the loop even starts.
    """
    taken: list[timedelta] = []

    @asynccontextmanager
    async def recording_lock(redis, name: str, ttl: timedelta):
        taken.append(ttl)
        async with task_lock(redis, name, ttl) as acquired:
            yield acquired

    monkeypatch.setattr("app.scheduler.tasks.task_lock", recording_lock)

    sync_pms_reservations()

    assert taken == [lock_ttl_for(CADENCES[TASK_NAME])]
    assert taken == [timedelta(hours=18)]


def test_a_run_that_loses_the_lock_is_skipped_not_failed(redis) -> None:
    """R1.3: a losing run is `skipped_locked`, not a failure — the second beat process
    during a redeploy must not report an error for finding the first one already running."""

    async def hold_and_run() -> dict:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            async with task_lock(client, TASK_NAME, timedelta(seconds=10)):
                return await asyncio.to_thread(sync_pms_reservations)
        finally:
            await client.aclose()

    report = asyncio.run(hold_and_run())

    assert report["skipped_locked"] is True
    assert report["task"] == TASK_NAME


def test_it_calls_the_sync_once_per_active_tenant(redis, monkeypatch) -> None:
    """R1's loop, with the tenant list stubbed so the assertion can fail.

    Against the real dev database this reports zero tenants and proves nothing — the module
    docstring says why. The stub goes on `app.scheduler.runner.list_active_tenants`, and
    `_sync_pms_reservations` itself is replaced too: what is pinned here is the loop
    (`run_for_every_tenant`'s one-call-per-tenant contract), already covered end to end by
    the real wiring tests above.
    """
    tenants = [uuid.uuid4(), uuid.uuid4()]
    calls: list[uuid.UUID] = []

    async def stub_tenants() -> list[uuid.UUID]:
        return tenants

    async def recording_sync(session: AsyncSession, tenant_id: uuid.UUID, now: datetime):
        calls.append(tenant_id)

    monkeypatch.setattr("app.scheduler.runner.list_active_tenants", stub_tenants)
    monkeypatch.setattr("app.scheduler.tasks._sync_pms_reservations", recording_sync)

    report = sync_pms_reservations()

    assert report["skipped_locked"] is False
    assert report["failed"] == 0
    assert report["tenants"] == len(tenants)
    assert calls == tenants


# --- R5: tenant isolation during the sweep, `test_runner.py`'s pattern -----------------


@pytest.mark.asyncio
async def test_a_tenant_never_sees_another_tenants_reservations_or_timeline_events(
    db_session, worker_sessions
) -> None:
    """R5: two ACTIVE tenants, each with a `MOCK` property, one sweep of `sync_pms_
    reservations`'s own per-tenant work function.

    Rule 1 of `steering/security.md`, at this job's own wiring rather than `run_for_every_
    tenant`'s generic version `test_runner.py` already covers: each tenant's `Reservation`s
    and `TimelineEvent`s carry the right `tenant_id`, and — the sharper claim — an ORM read
    on a session marked for one tenant never surfaces the other tenant's rows, even though
    both properties resolve the identical `SEED_PROPERTY_CODE` from the same mock adapter.
    """
    tenant_a = await insert_tenant(db_session, name="pms-isolation-a")
    tenant_b = await insert_tenant(db_session, name="pms-isolation-b")
    db_session.add(_mock_property(tenant_a.id, code="PMSISO-A"))
    db_session.add(_mock_property(tenant_b.id, code="PMSISO-B"))
    await db_session.commit()

    report = await runner.run_for_every_tenant(TASK_NAME, _sync_pms_reservations, now=NOW)

    assert report.failed == 0
    assert report.tenants == 2

    # Read unmarked (this session was never bound): both tenants' rows are visible, and each
    # one carries the tenant_id the sweep was run for — the "correct tenant_id" half of R5.
    all_reservations = (
        await db_session.execute(select(ReservationModel.tenant_id))
    ).scalars().all()
    all_events = (
        await db_session.execute(
            select(TimelineEventModel.tenant_id).where(
                TimelineEventModel.event_type == TimelineEventType.RESERVATION_IMPORTED
            )
        )
    ).scalars().all()
    assert set(all_reservations) == {tenant_a.id, tenant_b.id}
    assert set(all_events) == {tenant_a.id, tenant_b.id}
    # Set membership alone would pass even if a cross-tenant bug misattributed rows (e.g.
    # tenant_a ending up with 3 reservations, one really tenant_b's, leaving tenant_b with
    # only 1) as long as both tenant_id values are still represented somewhere. Each tenant's
    # single MOCK property yields exactly 2 valid reservations/events per sync (`MockPMSAdapter
    # ._seed`, matched by `outcome.created == 2` in the wiring tests above) — so the per-tenant
    # count must be exactly 2, not just "at least one row of each tenant exists".
    assert all_reservations.count(tenant_a.id) == 2, all_reservations
    assert all_reservations.count(tenant_b.id) == 2, all_reservations
    assert all_events.count(tenant_a.id) == 2, all_events
    assert all_events.count(tenant_b.id) == 2, all_events

    # Read through a session marked for each tenant: the sharper half of R5 — no row of the
    # other tenant is reachable through an ORM read that names no tenant_id at all.
    for tenant, other in ((tenant_a, tenant_b), (tenant_b, tenant_a)):
        async with worker_sessions() as marked:
            bind_session_to_tenant(marked, tenant.id)
            visible_reservations = (
                await marked.execute(select(ReservationModel.tenant_id))
            ).scalars().all()
            visible_events = (
                await marked.execute(select(TimelineEventModel.tenant_id))
            ).scalars().all()
        assert set(visible_reservations) == {tenant.id}, (tenant.id, visible_reservations)
        assert set(visible_events) == {tenant.id}, (tenant.id, visible_events)
        assert other.id not in visible_reservations
        assert other.id not in visible_events
