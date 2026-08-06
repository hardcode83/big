"""Beds24 payload -> `Beds24Adapter` -> `ReservationIngestor` -> Postgres (R2, R5).

The chain the change exists to prove, against **real Postgres** and the **real captured
payload**. Fakes would not do it: idempotency by `(tenant_id, external_pms_id)` rests on a
unique constraint, and `TimelineEvent` persistence is the first thing a wrong mapping breaks.

The HTTP boundary is `httpx.MockTransport` over the captured fixture, so the suite stays offline
(R2.6) even though the data behind it is real.

**Where the evidence is weaker, and it is said out loud**: the captured booking is `confirmed`.
A *cancelled* one cannot be captured until somebody runs `beds24_probe.py window` against the
measurement account (`BLOCKED.md`, items 1 and 4), so the cancellation test derives that state
from the real element with an explicit override. It is a derivation from a real payload, not an
invention, and task 1.4 replaces it with the real thing.
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


def _booking() -> dict:
    return beds24_fixture("bookings")["payload"]["data"][0]


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

    The cancelled element is DERIVED from the captured one (`BLOCKED.md`, item 4) — the
    measurement account has not produced a real cancellation yet.
    """
    await _use_case(db_session, _payload([_booking()])).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    cancelled = _booking() | {"status": "cancelled", "cancelTime": "2026-08-06T10:00:00Z"}
    report = await _use_case(db_session, _payload([cancelled])).execute(
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
