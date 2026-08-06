"""Channex payload -> `ChannexAdapter` -> `ReservationIngestor` -> Postgres (R5, task 6).

The chain the change exists to prove, against **real Postgres** and **real captured payloads**.
Fakes would not do it: idempotency by `(tenant_id, external_pms_id)` rests on a unique
constraint, and the `TimelineEvent` persistence is the first thing a wrong mapping breaks.

The fixture now holds **three** reservations, and one of them is the real thing: `BDC-6558139322`
arrived from Booking.com's test environment on 2026-08-03 through the acquired channel, carrying
a populated `channel_id` — the marker that tells an OTA reservation apart from one created via
Channex's CRS API. The other two are CRS seeds.

Counts are derived from the fixture (`len(bookings_payload["data"])`) rather than hard-coded:
re-capturing is expected, and a test that breaks because a real payload arrived is a test that
punishes the very thing this change exists to do.

The HTTP boundary is `httpx.MockTransport` over the captured fixture, so the suite stays offline
(R2.5) even though the data behind it is real.
"""

from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.db import bind_session_to_tenant
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
from app.integrations.domain.enums import PMSProvider
from tests.integrations.test_sync import _FactoryReturning
from app.integrations.infrastructure.channex.adapter import ChannexAdapter
from app.integrations.infrastructure.channex.client import ChannexClient
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from tests.integrations.conftest import channex_fixture

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
SINCE = datetime(2026, 8, 1, tzinfo=UTC)

# The property the bookings really belong to, as provisioned by `scripts/channex_bootstrap.py`.
CHANNEX_PROPERTY_ID = "7963f1e3-72f5-4edd-a0fb-199e9b919d26"


@pytest.fixture
def bookings_payload() -> dict:
    return channex_fixture("bookings")


@pytest_asyncio.fixture
async def channex_property(db_session, tenant_a) -> PropertyModel:
    """A property wired to the Channex UUID — task 6.1's mapping, as a fixture.

    In the real staging run this is a documented one-off step in the runbook rather than a
    migration or a change to `app/cli/bootstrap.py`: it is a property of a provider that is not
    the MVP's, and it has no business in everybody's boot sequence (design D11).
    """
    prop = PropertyModel(
        tenant_id=tenant_a.id,
        # Deliberately NOT named after REDES11 or PAJARITOS8. Naming a sandbox after a listing
        # that is actually selling caused a real "is this my apartment?" scare once already.
        name="Channex Sandbox (test only)",
        internal_code="CHANNEX-SANDBOX",
        pms_external_id=CHANNEX_PROPERTY_ID,
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


def _use_case(db_session, payload: dict) -> SyncReservationsFromPmsUseCase:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = ChannexAdapter(
        ChannexClient(
            api_key="test-key",
            base_url="https://staging.channex.io/api/v1",
            max_pages=10,
            page_limit=100,
            transport=httpx.MockTransport(handler),
        )
    )
    return SyncReservationsFromPmsUseCase(
        factory=_FactoryReturning(adapter),
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
    )


@pytest.mark.asyncio
async def test_real_channex_bookings_reach_the_database_with_timeline_events(
    db_session, tenant_a, channex_property, bookings_payload
) -> None:
    """The headline: two real reservations in, two rows and two timeline events out.

    Without the status translation of task 4.6 this returns `created=0` with two reported
    errors, because every captured booking arrives as `status: "new"` and
    `ReservationStatus.parse_ingested("new")` raises. That is the assertion doing real work.
    """
    report = await _use_case(db_session, bookings_payload).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    expected = len(bookings_payload["data"])
    assert report.errors == []
    assert report.created == expected
    assert report.skipped == 0

    reservations = int(
        await db_session.scalar(select(func.count()).select_from(ReservationModel)) or 0
    )
    events = int(
        await db_session.scalar(select(func.count()).select_from(TimelineEventModel)) or 0
    )
    assert (reservations, events) == (expected, expected)


@pytest.mark.asyncio
async def test_running_it_twice_updates_instead_of_duplicating(
    db_session, tenant_a, channex_property, bookings_payload
) -> None:
    """Idempotency by `(tenant_id, external_pms_id)`, which is why `external_id` had to be
    `unique_id` and not `revision_id` (design D7): a per-revision id would create a new
    reservation on every modification.

    An unchanged row counts as **skipped with no error**, not as `updated` — the same semantics
    `test_sync.py` already pins for the mock, where `skipped` covers both "nothing changed" and
    "could not use this row" and `errors` is what tells them apart.
    """
    await _use_case(db_session, bookings_payload).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )
    second = await _use_case(db_session, bookings_payload).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    expected = len(bookings_payload["data"])
    assert second.created == 0
    assert second.skipped == expected
    assert second.errors == []
    reservations = int(
        await db_session.scalar(select(func.count()).select_from(ReservationModel)) or 0
    )
    assert reservations == expected


@pytest.mark.asyncio
async def test_the_persisted_rows_carry_the_translated_domain_values(
    db_session, tenant_a, channex_property, bookings_payload
) -> None:
    """Everything section 4 decided, verified where it actually matters: in the database."""
    await _use_case(db_session, bookings_payload).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    rows = (await db_session.execute(select(ReservationModel))).scalars().all()
    by_id = {row.external_pms_id: row for row in rows}

    # Keyed by identity, not by channel: since the real Booking.com reservation landed, TWO rows
    # map to `BOOKING` (`Booking.com` from the CRS seed and `BookingCom` from the OTA), and a
    # dict keyed on channel silently collapses them.
    seeded_ota = by_id["BDC-AUTOHOST-TEST-BDC-001"]
    seeded_offline = by_id["OFL-AUTOHOST-TEST-OFFLINE-001"]

    # `new` became CONFIRMED, not PENDING: a booking off a PMS feed is already accepted.
    for row in rows:
        assert row.status is ReservationStatus.CONFIRMED

    # Both spellings Channex really uses land on the same channel. `BookingCom` (no dot) is what
    # a genuine Booking.com reservation carries; `Booking.com` is what the CRS seed was given.
    assert seeded_ota.channel is ReservationChannel.BOOKING
    assert seeded_offline.channel is ReservationChannel.MANUAL

    # R2.6 as revised after measuring a REAL Booking.com reservation: a `"0.00"` commission is
    # persisted as `None`, never as a zero that would assert "this OTA charged nothing".
    assert seeded_ota.ota_commission is not None
    assert float(seeded_ota.ota_commission) == 54.0
    assert seeded_offline.ota_commission is None
    for row in rows:
        assert row.ota_commission is None or row.ota_commission != 0


@pytest_asyncio.fixture
async def channex_property_of_tenant_b(db_session, tenant_b) -> PropertyModel:
    """Tenant B's property wired to the SAME Channex UUID as tenant A's would be.

    Not a contrived scenario: the Channex API is not tenant-aware. One API key, one provider
    account, and a single `GET /bookings` response can carry rows for any property under it. The
    only thing standing between that and a cross-tenant write is that
    `find_by_pms_external_id` is scoped — which is exactly what needs a test rather than
    confidence.
    """
    prop = PropertyModel(
        tenant_id=tenant_b.id,
        name="Channex Sandbox de otro tenant",
        internal_code="CHANNEX-SANDBOX-B",
        pms_external_id=CHANNEX_PROPERTY_ID,
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


@pytest.mark.asyncio
async def test_a_tenant_never_ingests_a_booking_belonging_to_another_tenants_property(
    db_session, tenant_a, tenant_b, channex_property_of_tenant_b, bookings_payload
) -> None:
    """Rule 1 of `steering/security.md`, for this ingestion path.

    Only tenant B owns a property with this Channex UUID. Tenant A runs the sync against the
    very same provider payload and must import **nothing**.

    **How that is now guaranteed changed, and earlier is better.** It used to rest on
    `find_by_pms_external_id` being tenant-scoped: the provider was called, every row resolved to
    no property of A, and each was reported. With per-provider grouping the portfolio is read
    first, so tenant A — which owns no property — forms no group and the provider is never
    called at all. The invariant is the same and the exposure is smaller: a real provider account
    can hold properties belonging to anyone, and now none of their bookings are even fetched on
    A's behalf.

    Mirrors `test_sync.py::test_the_sync_never_touches_another_tenants_property`.
    """
    bind_session_to_tenant(db_session, tenant_a.id)

    report = await _use_case(db_session, bookings_payload).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.created == 0
    # Zero, not "one skip per booking": nothing was fetched on A's behalf, so there was nothing
    # to skip. See the docstring — the guarantee moved earlier, it did not weaken.
    assert report.skipped == 0
    assert report.errors == []

    # Unmarked before counting, or the tenant filter would hide rows the assertion is about.
    db_session.info.pop("tenant_id", None)
    reservations = int(
        await db_session.scalar(select(func.count()).select_from(ReservationModel)) or 0
    )
    events = int(
        await db_session.scalar(select(func.count()).select_from(TimelineEventModel)) or 0
    )
    assert (reservations, events) == (0, 0)


@pytest.mark.asyncio
async def test_the_other_tenant_can_still_ingest_its_own_bookings(
    db_session, tenant_b, channex_property_of_tenant_b, bookings_payload
) -> None:
    """The other half: scoping must block the wrong tenant without blocking the right one.

    Without this, a mapping bug that made every row unresolvable would satisfy the isolation
    test above while importing nothing for anybody.
    """
    report = await _use_case(db_session, bookings_payload).execute(
        tenant_id=tenant_b.id, since=SINCE, now=NOW
    )

    assert report.created == len(bookings_payload["data"])
    assert report.errors == []

    rows = (await db_session.execute(select(ReservationModel))).scalars().all()
    assert {row.tenant_id for row in rows} == {tenant_b.id}


@pytest.mark.asyncio
async def test_a_booking_for_an_unknown_property_is_reported_not_fatal(
    db_session, tenant_a, channex_property, bookings_payload
) -> None:
    """R3.4 of `specs/reservations.md` still holds through the real adapter: one unresolvable
    row is reported and the rest still import."""
    payload = {
        "meta": {"total": len(bookings_payload["data"]) + 1, "page": 1, "limit": 100},
        "data": [
            *bookings_payload["data"],
            {
                "type": "booking",
                "id": "ghost",
                "attributes": {
                    **bookings_payload["data"][0]["attributes"],
                    "unique_id": "GHOST-0001",
                    "property_id": "00000000-0000-0000-0000-000000000000",
                },
            },
        ],
    }

    report = await _use_case(db_session, payload).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.created == len(bookings_payload["data"])
    assert report.skipped == 1
    assert len(report.errors) == 1
