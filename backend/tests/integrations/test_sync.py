"""The PMS sync against real Postgres (R3.2, R3.3, R3.4, R3.5, R2.4).

Integration, not fakes: idempotency rests on a unique constraint and on what the repository
actually reads back, and a fake would let a broken `find_by_external_pms_id` pass.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.db import bind_session_to_tenant
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.models import GuestModel
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
from app.integrations.domain.dtos import PmsFetchResult, PmsRowFailure
from app.integrations.domain.enums import PMSProvider
from app.integrations.infrastructure.mock_pms import SEED_PROPERTY_CODE, MockPMSAdapter
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
SINCE = datetime(2026, 7, 1, tzinfo=UTC)



class _FactoryReturning:
    """A `PMSAdapterFactory` that hands back one adapter for every property.

    The use case now depends on the FACTORY, not on an adapter (ADR 0006 decision 7), so a test
    that wants to drive a specific adapter supplies one of these. It also stands in for the real
    grouping: `provider_for` reports a single provider, so the whole portfolio forms one group
    and the test exercises exactly one call, which is what these tests were written to assert.
    """

    def __init__(self, adapter, provider=PMSProvider.MOCK) -> None:
        self._adapter = adapter
        self._provider = provider
        self.calls = 0

    def supports_messaging(self, provider) -> bool:
        return False

    def provider_for(self, property):
        return self._provider

    async def reservations_for(self, property, *, read_log=None):
        self.calls += 1
        return self._adapter

    async def messaging_for(self, property):
        raise AssertionError("this test should not resolve messaging")


def _use_case(db_session, *, include_broken_rows: bool = True) -> SyncReservationsFromPmsUseCase:
    return _use_case_with(
        db_session, MockPMSAdapter(include_broken_rows=include_broken_rows)
    )


def _build(db_session, factory) -> SyncReservationsFromPmsUseCase:
    return SyncReservationsFromPmsUseCase(
        factory=factory,
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
    )


async def _counts(db_session) -> tuple[int, int]:
    reservations = await db_session.scalar(select(func.count()).select_from(ReservationModel))
    events = await db_session.scalar(select(func.count()).select_from(TimelineEventModel))
    return int(reservations or 0), int(events or 0)


@pytest.mark.asyncio
async def test_it_imports_the_seed_reservations(db_session, tenant_a, property_a) -> None:
    report = await _use_case(db_session, include_broken_rows=False).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.created == 2
    assert report.updated == 0
    assert report.errors == []
    reservations, events = await _counts(db_session)
    assert reservations == 2
    assert events == 2


@pytest.mark.asyncio
async def test_the_imported_events_are_system_events(db_session, tenant_a, property_a) -> None:
    """R2.4 and design D15: no person runs the sync, so no `actor_user_id`."""
    await _use_case(db_session, include_broken_rows=False).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    events = (await db_session.execute(select(TimelineEventModel))).scalars().all()
    assert {event.event_type for event in events} == {TimelineEventType.RESERVATION_IMPORTED}
    assert all(event.actor_type is TimelineActorType.SYSTEM for event in events)
    assert all(event.actor_user_id is None for event in events)
    assert all(event.created_at == NOW for event in events)


@pytest.mark.asyncio
async def test_a_second_identical_run_creates_nothing_and_adds_no_events(
    db_session, tenant_a, property_a
) -> None:
    """R3.3, the observable definition of idempotency."""
    use_case = _use_case(db_session, include_broken_rows=False)
    await use_case.execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)
    before = await _counts(db_session)

    second = await use_case.execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)

    assert second.created == 0
    assert await _counts(db_session) == before


@pytest.mark.asyncio
async def test_a_changed_reservation_is_updated_not_duplicated(
    db_session, tenant_a, property_a
) -> None:
    """R3.2: the same `external_pms_id` on a later run updates the row it already has."""
    await _use_case(db_session, include_broken_rows=False).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    # A later window shifts the mock's dates, which is exactly what a changed booking looks
    # like from the outside.
    later = SINCE.replace(day=15)
    report = await _use_case(db_session, include_broken_rows=False).execute(
        tenant_id=tenant_a.id, since=later, now=NOW
    )

    assert report.created == 0
    assert report.updated == 2
    reservations, _ = await _counts(db_session)
    assert reservations == 2


@pytest.mark.asyncio
async def test_broken_rows_are_reported_without_aborting_the_run(
    db_session, tenant_a, property_a
) -> None:
    """R3.4: the unknown property and the impossible stay must not cost the good rows."""
    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)

    assert report.created == 2
    assert report.skipped == 2
    reasons = " ".join(error.reason for error in report.errors)
    assert "Unknown property" in reasons
    assert "check_out_date" in reasons
    reservations, _ = await _counts(db_session)
    assert reservations == 2


@pytest.mark.asyncio
async def test_guests_are_created_once_and_reused(db_session, tenant_a, property_a) -> None:
    """R3.5 + design D8: two runs must not leave two John Smiths."""
    use_case = _use_case(db_session, include_broken_rows=False)
    await use_case.execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)
    await use_case.execute(tenant_id=tenant_a.id, since=SINCE.replace(day=15), now=NOW)

    guests = (await db_session.execute(select(GuestModel))).scalars().all()
    assert sorted(guest.email for guest in guests) == [
        "john.smith@example.com",
        "maria.garcia@example.com",
    ]


@pytest.mark.asyncio
async def test_an_existing_guest_of_the_tenant_is_linked_instead_of_duplicated(
    db_session, tenant_a, property_a
) -> None:
    existing = GuestModel(
        tenant_id=tenant_a.id, full_name="John Smith (already here)", email="john.smith@example.com"
    )
    db_session.add(existing)
    await db_session.flush()

    await _use_case(db_session, include_broken_rows=False).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    linked = await db_session.scalar(
        select(ReservationModel.guest_id).where(ReservationModel.external_pms_id == "MOCK-PMS-0001")
    )
    assert linked == existing.id


@pytest.mark.asyncio
async def test_a_guest_of_another_tenant_with_the_same_email_is_not_linked(
    db_session, tenant_a, tenant_b, property_a
) -> None:
    """The dedup lookup is tenant-scoped, so the neighbour's John Smith is invisible here.

    Proven at the ingest level and not only at the repository level: this is the path where an
    external payload supplies the email, so it is where the mistake would be made.
    """
    theirs = GuestModel(
        tenant_id=tenant_b.id, full_name="Their John", email="john.smith@example.com"
    )
    db_session.add(theirs)
    await db_session.flush()

    await _use_case(db_session, include_broken_rows=False).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    linked = await db_session.scalar(
        select(ReservationModel.guest_id).where(ReservationModel.external_pms_id == "MOCK-PMS-0001")
    )
    assert linked is not None
    assert linked != theirs.id
    mine = await db_session.scalar(select(GuestModel).where(GuestModel.id == linked))
    assert mine.tenant_id == tenant_a.id


@pytest.mark.asyncio
async def test_the_sync_never_touches_another_tenants_property(
    db_session, tenant_a, tenant_b, property_b
) -> None:
    """Tenant A has no property at all; B does — and A must import nothing.

    **The number changed with per-provider grouping, and the new one is the better guarantee.**
    This used to assert `skipped == 2`: the sync called the PMS once for the whole tenant and then
    discarded every row that resolved to no property of A. Now the portfolio is grouped first, so
    a tenant with no properties forms no groups and the provider is **never called** — the
    isolation holds earlier, and a tenant with nothing to sync no longer spends any of the credit
    budget the whole grouping design exists to protect.

    So `skipped == 0` is not a weaker assertion: nothing was attempted, and `calls == 0` below is
    what pins the property that replaced it.
    """
    bind_session_to_tenant(db_session, tenant_a.id)
    factory = _FactoryReturning(MockPMSAdapter(include_broken_rows=False))

    report = await _build(db_session, factory).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.created == 0
    assert report.skipped == 0
    assert factory.calls == 0, "a tenant with no properties must not reach the provider"
    db_session.info.pop("tenant_id", None)
    reservations, _ = await _counts(db_session)
    assert reservations == 0


@pytest.mark.asyncio
async def test_amounts_are_derived_consistently(db_session, tenant_a, property_a) -> None:
    """`net_amount` is not in the PMS DTO, so it has to be derived (gross − commission)."""
    from decimal import Decimal

    await _use_case(db_session, include_broken_rows=False).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    row = (
        await db_session.execute(
            select(ReservationModel).where(ReservationModel.external_pms_id == "MOCK-PMS-0001")
        )
    ).scalar_one()
    assert row.gross_amount == Decimal("350.00")
    assert row.ota_commission == Decimal("52.50")
    assert row.net_amount == Decimal("297.50")


# --- The fold of provider elements the adapter could not map (R6.3, design D10) ---


class _AdapterWithFailures:
    """A `PMSAdapter` that reports unmappable elements. `MockPMSAdapter` cannot: it builds its own
    elements, so it always returns `failures=[]`, which is why nothing exercised this fold.

    Structural conformance, no inheritance — the port is a plain `Protocol` and that is how the
    repo does it (`tests/test_unit_of_work.py`).
    """

    def __init__(
        self,
        failures: list[PmsRowFailure],
        reservations: list | None = None,
    ) -> None:
        self._failures = failures
        # Reservations too, so a single call can carry BOTH failure channels at once: elements the
        # adapter could not map, and well-formed DTOs the ingestor will reject. Without this the
        # combined case is unreachable and the `+=` in the fold cannot be distinguished from `=`.
        self._reservations = reservations or []

    async def list_reservations(self, since, property_external_id=None) -> PmsFetchResult:
        return PmsFetchResult(
            reservations=list(self._reservations), failures=list(self._failures)
        )

    async def get_reservation(self, external_id):
        return None


def _use_case_with(db_session, adapter) -> SyncReservationsFromPmsUseCase:
    return _build(db_session, _FactoryReturning(adapter))


@pytest.mark.asyncio
async def test_unmappable_provider_elements_are_folded_into_the_report(
    db_session, tenant_a, property_a
) -> None:
    """The fold used to live in `cli/pms_sync.py`, so no test covered it once it moved here.

    Flagged by the QA panel of this change: every existing test either stubbed `run()` or used
    `MockPMSAdapter`, whose `failures` is always empty — so task 2.4's promised test did not
    exist and the moved code was verified only by reading the diff.
    """
    adapter = _AdapterWithFailures(
        [
            PmsRowFailure(external_id="BDC-1", reason="UnmappableField: arrival_date"),
            PmsRowFailure(external_id="BDC-2", reason="KeyError"),
            # An element malformed in the very field that would name it.
            PmsRowFailure(external_id=None, reason="TypeError"),
        ]
    )

    report = await _use_case_with(db_session, adapter).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.created == 0
    assert report.skipped == 3
    assert len(report.errors) == 3
    # The identifier travels in `reference`, its own field, so bounding `reason` to a closed
    # vocabulary cannot destroy it. `cli/pms_sync.py` prints both.
    assert [error.reference for error in report.errors] == ["BDC-1", "BDC-2", None]
    assert all(
        error.reason.startswith("provider row could not be mapped: ")
        for error in report.errors
    )
    # No line numbers: an API response has none, unlike the CSV path.
    assert all(error.line is None for error in report.errors)


@pytest.mark.asyncio
async def test_the_fold_adds_to_the_rows_the_ingestor_already_rejected(
    db_session, tenant_a, property_a
) -> None:
    """Two different failure channels in ONE call, and the counters must not shadow each other.

    Elements the adapter could not map at all are one channel; well-formed DTOs the INGESTOR
    rejects (`MockPMSAdapter` emits an unknown property and a zero-night stay on purpose) are
    another. Both land in `skipped`, so this pins that the fold ADDS rather than replaces: with
    `=` instead of `+=` the count would be 3, not 5.

    **Two earlier versions of this test were wrong, and both matter as a record.** The first was
    ceremonial — the QA panel caught that it only asserted the ingestor-only baseline and never
    combined the channels, so it would have passed with `=`. The second combined them but ran
    `execute` TWICE against one session to compute that baseline, and the second pass reprocessed
    what the first had already written (`skipped` came out 7). Hence one call, and the ingestor's
    contribution taken as the constant it is, asserted from the error texts rather than from a
    second run.
    """
    ingestor_rejected = (await MockPMSAdapter().list_reservations(SINCE)).reservations
    report = await _use_case_with(
        db_session,
        _AdapterWithFailures(
            [
                PmsRowFailure(external_id="BDC-9", reason="UnmappableField: arrival_date"),
                PmsRowFailure(external_id="BDC-10", reason="AttributeError"),
                PmsRowFailure(external_id=None, reason="TypeError"),
            ],
            reservations=ingestor_rejected,
        ),
    ).execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)

    unmappable = [
        error
        for error in report.errors
        if error.reason.startswith("provider row could not be mapped: ")
    ]
    rejected_by_ingestor = [error for error in report.errors if error not in unmappable]

    assert len(unmappable) == 3
    assert len(rejected_by_ingestor) == 2, "MockPMSAdapter's two deliberately broken rows"
    # 2 + 3. This is the assertion an `=` would fail and the first version could not make.
    assert report.skipped == 5
    assert len(report.errors) == 5
    # The two good seed rows still landed, so the fold did not disturb the happy path.
    assert report.created == 2


@pytest.mark.asyncio
async def test_a_run_with_no_failures_reports_none(db_session, tenant_a, property_a) -> None:
    report = await _use_case_with(db_session, _AdapterWithFailures([])).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.skipped == 0
    assert report.errors == []


async def _extra_property(db_session, tenant, *, code: str, external_id: str):
    """One more property for this tenant, so grouping has something to group."""
    prop = PropertyModel(
        tenant_id=tenant.id,
        name=code.title(),
        internal_code=code,
        pms_external_id=external_id,
        max_guests=2,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


# --- Per-provider grouping (R2.2, the decision recorded in BLOCKED.md) ---


class _CountingFactory:
    """Tracks how many times each provider was resolved and which properties it was asked about.

    The whole point of grouping is the CALL COUNT, so a test of it needs to observe calls rather
    than results.
    """

    def __init__(self, adapters: dict) -> None:
        self._adapters = adapters
        self.resolved: list = []

    def supports_messaging(self, provider) -> bool:
        return False

    def provider_for(self, property):
        return property.pms_provider or PMSProvider.MOCK

    async def reservations_for(self, property, *, read_log=None):
        self.resolved.append((self.provider_for(property), property.internal_code))
        return self._adapters[self.provider_for(property)]

    async def messaging_for(self, property):
        raise AssertionError("not expected")


@pytest.mark.asyncio
async def test_the_sync_calls_each_provider_once_not_each_property(
    db_session, tenant_a, property_a
) -> None:
    """One provider, four properties → one resolution.

    **On its own this does NOT prove grouping**, and the QA panel was right to say the docstring
    claimed it did: with a single provider in play, "one call per provider" and the old "one call
    per tenant" produce the same count. What discriminates them is
    `test_two_providers_in_one_tenant_get_one_call_each` and
    `test_a_reservation_cannot_attach_to_a_property_of_another_provider`, both of which fail if
    grouping is reverted. This one pins the half those do not: that adding properties does not add
    calls.

    A call per property scales without bound; the measured Beds24 budget is 100 credits per 300 s
    per account and a cycle costs 8, so a dozen properties exhaust a five-minute window in one
    pass (`specs/pms-beds24-spike.md`). Grouping scales with the number of DISTINCT providers,
    which is two or three.

    Four properties, one provider → exactly one resolution, not four.
    """
    repository = SqlAlchemyPropertyRepository(db_session)
    extra = [
        await _extra_property(db_session, tenant_a, code=f"EXTRA-{n}", external_id=f"EXT-{n}")
        for n in range(3)
    ]
    for prop in extra:
        await repository.set_pms_provider(tenant_a.id, prop.id, PMSProvider.MOCK)
    await db_session.flush()

    factory = _CountingFactory({PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False)})
    await _build(db_session, factory).execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)

    assert len(factory.resolved) == 1, factory.resolved
    assert factory.resolved[0][0] is PMSProvider.MOCK


@pytest.mark.asyncio
async def test_two_providers_in_one_tenant_get_one_call_each(
    db_session, tenant_a, property_a
) -> None:
    """The scenario ADR 0006 decision 7 exists for: a tenant mid-migration.

    Some properties already moved to another provider and some have not. Before this change the
    sync had a single adapter per run and simply could not serve both.
    """
    repository = SqlAlchemyPropertyRepository(db_session)
    moved = await _extra_property(db_session, tenant_a, code="MOVED", external_id="EXT-MOVED")
    await repository.set_pms_provider(tenant_a.id, moved.id, PMSProvider.CHANNEX)
    await db_session.flush()

    factory = _CountingFactory(
        {
            PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False),
            PMSProvider.CHANNEX: MockPMSAdapter(include_broken_rows=False),
        }
    )
    await _build(db_session, factory).execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)

    providers = sorted(provider.value for provider, _ in factory.resolved)
    assert providers == ["CHANNEX", "MOCK"]
    assert len(factory.resolved) == 2


@pytest.mark.asyncio
async def test_a_reservation_cannot_attach_to_a_property_of_another_provider(
    db_session, tenant_a, property_a
) -> None:
    """External ids are unique only WITHIN a provider, and the schema does not say otherwise —
    `ix_properties_tenant_id_pms_external_id` is an index, not a constraint.

    So matching is restricted to the group being synced. Without that, a Channex booking whose id
    happens to equal a Beds24 property's id would attach a guest to the wrong home, which is the
    same failure `find_by_pms_external_id` refuses to make by raising on an ambiguous id.
    """
    repository = SqlAlchemyPropertyRepository(db_session)
    # A second property, on a DIFFERENT provider, carrying the SAME external id as the seed one.
    collision = await _extra_property(
        db_session, tenant_a, code="COLLIDE", external_id=SEED_PROPERTY_CODE
    )
    await repository.set_pms_provider(tenant_a.id, collision.id, PMSProvider.CHANNEX)
    await db_session.flush()

    factory = _CountingFactory(
        {
            PMSProvider.MOCK: MockPMSAdapter(include_broken_rows=False),
            # The Channex group gets an adapter that returns nothing, so any reservation that
            # landed on the colliding property could only have come from the mock's group.
            PMSProvider.CHANNEX: _AdapterWithFailures([]),
        }
    )
    await _build(db_session, factory).execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)

    attached = await db_session.execute(
        select(func.count()).select_from(ReservationModel).where(
            ReservationModel.property_id == collision.id
        )
    )
    assert int(attached.scalar() or 0) == 0
