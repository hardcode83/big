"""Beds24 payload -> `Beds24Adapter` -> `ReservationIngestor` -> Postgres (R2, R5).

The chain the change exists to prove, against **real Postgres** and the **real captured
payload**. Fakes would not do it: idempotency by `(tenant_id, external_pms_id)` rests on a
unique constraint, and `TimelineEvent` persistence is the first thing a wrong mapping breaks.

The HTTP boundary is `httpx.MockTransport` over the captured fixture, so the suite stays offline
(R2.6) even though the data behind it is real.

All three booking states are **captured from the real account** (2026-08-06, via
`beds24_probe.py window`): confirmed, modified and cancelled. Nothing here is derived by hand.
"""

from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
from app.integrations.domain.enums import PMSProvider
from app.integrations.infrastructure.beds24.adapter import Beds24Adapter
from app.integrations.infrastructure.beds24.client import Beds24Client
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from tests.integrations.conftest import beds24_fixture
from tests.integrations.test_sync import _FactoryReturning

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
SINCE = datetime(2026, 8, 1, tzinfo=UTC)

# The property the captured booking really belongs to, in the measurement account.
BEDS24_PROPERTY_ID = "345754"


def _booking(name: str = "bookings") -> dict:
    return beds24_fixture(name)["payload"]["data"][0]


def _payload(rows: list[dict]) -> dict:
    return {
        "success": True,
        "type": "booking",
        "count": len(rows),
        "pages": {"nextPageExists": False, "nextPageLink": None},
        "data": rows,
    }


@pytest_asyncio.fixture
async def beds24_property(db_session, tenant_a) -> PropertyModel:
    """A property wired to the Beds24 `propertyId` — design D11's operating contract.

    Deliberately NOT named after REDES11 or PAJARITOS8: naming a sandbox after a listing that
    is actually selling caused a real "is this my apartment?" scare once already.
    """
    prop = PropertyModel(
        tenant_id=tenant_a.id,
        name="Beds24 Sandbox (test only)",
        internal_code="BEDS24-SANDBOX",
        pms_external_id=BEDS24_PROPERTY_ID,
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


def _use_case(db_session, payload: dict) -> SyncReservationsFromPmsUseCase:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authentication/token"):
            return httpx.Response(200, json={"token": "access", "expiresIn": 86400})
        return httpx.Response(200, json=payload, headers={"X-Request-Cost": "1"})

    adapter = Beds24Adapter(
        Beds24Client(
            refresh_token="a-real-looking-refresh-token",
            max_pages=10,
            page_limit=100,
            transport=httpx.MockTransport(handler),
        )
    )
    return SyncReservationsFromPmsUseCase(
        factory=_FactoryReturning(adapter, provider=PMSProvider.BEDS24),
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
    )


@pytest.mark.asyncio
async def test_a_real_beds24_booking_reaches_the_database_with_its_timeline_event(
    db_session, tenant_a, beds24_property
) -> None:
    """The headline: the captured payload in, a row and a timeline event out.

    Without the status translation in `mapping.STATUS_BY_BEDS24_STATUS` this returns
    `created=0` with one reported error, because `ReservationStatus.parse_ingested` raises on
    the provider's own vocabulary. That is the assertion doing real work.
    """
    report = await _use_case(db_session, _payload([_booking()])).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.errors == []
    assert report.created == 1

    reservations = int(
        await db_session.scalar(select(func.count()).select_from(ReservationModel)) or 0
    )
    events = int(
        await db_session.scalar(select(func.count()).select_from(TimelineEventModel)) or 0
    )
    assert (reservations, events) == (1, 1)


@pytest.mark.asyncio
async def test_running_it_twice_updates_instead_of_duplicating(
    db_session, tenant_a, beds24_property
) -> None:
    """Idempotency by `(tenant_id, external_pms_id)`, which is why `external_id` is the
    provider's `id` and not `apiReference` — the id survives modification and cancellation,
    which is exactly what makes the modification window useful."""
    payload = _payload([_booking()])

    await _use_case(db_session, payload).execute(tenant_id=tenant_a.id, since=SINCE, now=NOW)
    second = await _use_case(db_session, payload).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert second.created == 0
    assert second.errors == []
    reservations = int(
        await db_session.scalar(select(func.count()).select_from(ReservationModel)) or 0
    )
    assert reservations == 1


@pytest.mark.asyncio
async def test_a_cancellation_arriving_through_the_window_updates_the_existing_row(
    db_session, tenant_a, beds24_property
) -> None:
    """**R2.1's whole point, end to end.**

    Channex cannot deliver this at all: its `/bookings` filters on `inserted_at`, so a booking
    created before `since` and cancelled after it never comes back, and the row in our database
    stays `CONFIRMED` forever while the guest has cancelled. Beds24 filters by modification
    date, so the same booking returns with `status: cancelled` and the existing row moves.

    Both elements are **captured from the real account** (2026-08-06): the same booking
    confirmed and then cancelled, produced by `beds24_probe.py window`. And the cancellation is
    only visible at all because the adapter sends the status enumeration — the default listing
    omits cancellations, which is the measurement that saved this requirement.
    """
    confirmed = _booking("bookings_modified")
    await _use_case(db_session, _payload([confirmed])).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    report = await _use_case(db_session, _payload([_booking("bookings_cancelled")])).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.errors == []
    stored = (
        await db_session.execute(select(ReservationModel).limit(1))
    ).scalar_one()
    assert stored.status is ReservationStatus.CANCELLED
    assert int(
        await db_session.scalar(select(func.count()).select_from(ReservationModel)) or 0
    ) == 1


@pytest.mark.asyncio
async def test_one_tenants_beds24_sync_never_reaches_another_tenants_data(
    db_session, tenant_a, tenant_b, beds24_property
) -> None:
    """Rule 1 of `sdd/steering/security.md`, for this module.

    *"Tests automáticos que demuestran que un tenant no accede a datos de otro — **obligatorios
    en cada módulo nuevo**."* `beds24/` is a new module and it carries a **decrypted
    account-level credential**, which rule 3 calls the most dangerous kind precisely because a
    scoping failure there grants write access rather than leaking a read.

    The generic cross-tenant test in `test_sync.py` exercises `MockPMSAdapter`, so until this
    one existed nothing demonstrated the property for the real adapter. Raised by the tenancy
    reviewer at feature scale.

    The trap this pins is specific and real: B owns a property whose `pms_external_id` is the
    **same Beds24 `propertyId`** as A's — which is what a shared measurement account looks like,
    and what would happen if two tenants were onboarded onto one Beds24 account by mistake. The
    provider returns a booking for that id; it must land in A and nowhere else.
    """
    twin = PropertyModel(
        tenant_id=tenant_b.id,
        name="Beds24 Sandbox of another tenant",
        internal_code="BEDS24-SANDBOX-B",
        pms_external_id=BEDS24_PROPERTY_ID,
        max_guests=4,
    )
    db_session.add(twin)
    await db_session.flush()

    report = await _use_case(db_session, _payload([_booking()])).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.created == 1
    rows = (await db_session.execute(select(ReservationModel))).scalars().all()
    assert [row.tenant_id for row in rows] == [tenant_a.id]
    events = (await db_session.execute(select(TimelineEventModel))).scalars().all()
    assert {event.tenant_id for event in events} == {tenant_a.id}


@pytest.mark.asyncio
async def test_a_calendar_block_never_becomes_a_reservation(
    db_session, tenant_a, beds24_property
) -> None:
    """Design D10 — Beds24 serves owner blocks from the same endpoint.

    Importing one would invent a guest and drive the `PropertyStateMachine` on a property
    nobody booked, which `steering/architecture.md` names as the single place transitions may
    happen.
    """
    blocked = _booking() | {"id": 90923999, "status": "black"}

    report = await _use_case(db_session, _payload([_booking(), blocked])).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.created == 1
    assert report.errors == []
    assert int(
        await db_session.scalar(select(func.count()).select_from(ReservationModel)) or 0
    ) == 1
