"""The PMS sync against real Postgres (R3.2, R3.3, R3.4, R3.5, R2.4).

Integration, not fakes: idempotency rests on a unique constraint and on what the repository
actually reads back, and a fake would let a broken `find_by_external_pms_id` pass.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.db import bind_session_to_tenant
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.models import GuestModel
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
from app.integrations.infrastructure.mock_pms import MockPMSAdapter
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
SINCE = datetime(2026, 7, 1, tzinfo=UTC)


def _use_case(db_session, *, include_broken_rows: bool = True) -> SyncReservationsFromPmsUseCase:
    return SyncReservationsFromPmsUseCase(
        pms=MockPMSAdapter(include_broken_rows=include_broken_rows),
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
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
async def test_the_sync_never_touches_another_tenants_property(
    db_session, tenant_a, tenant_b, property_b
) -> None:
    """Tenant A has no property with the mock's code; B does — and A must import nothing."""
    bind_session_to_tenant(db_session, tenant_a.id)

    report = await _use_case(db_session, include_broken_rows=False).execute(
        tenant_id=tenant_a.id, since=SINCE, now=NOW
    )

    assert report.created == 0
    assert report.skipped == 2
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
