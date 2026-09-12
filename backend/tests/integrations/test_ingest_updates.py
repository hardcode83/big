"""`ReservationIngestor`'s update path emits timeline evidence (R1, R2, R6).

Against real Postgres, driving `ReservationIngestor` directly rather than through one of its
three callers (PMS sync, CSV import, demo seed) — the update path is common to all three, so
proving it once here is what the design counts on (`ingest.py`'s own module docstring).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.guests.infrastructure.postgres_guest_email_exclusion import PostgresGuestEmailExclusion
from app.integrations.infrastructure.postgres_reservation_ingest_lock import PostgresReservationIngestLock
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.ingest import IngestRow, ReservationIngestor
from app.integrations.domain.dtos import ReservationDTO
from app.properties.domain.entities import Property as PropertyEntity
from app.properties.domain.enums import PropertyOperationalState
from app.reservations.infrastructure.models import ReservationModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
EXTERNAL_ID = "PMS-TEST-0001"


def _ingestor(db_session, *, advance=None) -> ReservationIngestor:
    return ReservationIngestor(
        reservations=SqlAlchemyReservationRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        email_exclusion=PostgresGuestEmailExclusion(db_session),
        ingest_lock=PostgresReservationIngestLock(db_session),
        advance=advance,
    )


def _row(**overrides) -> IngestRow:
    fields = {
        "external_id": EXTERNAL_ID,
        "channel": "DIRECT",
        "property_external_id": "PMS-REDES11",
        "check_in_date": NOW.date(),
        "check_out_date": NOW.date() + timedelta(days=2),
        "gross_amount": Decimal("100.00"),
        "ota_commission": Decimal("0.00"),
    }
    fields.update(overrides)
    return IngestRow(dto=ReservationDTO(**fields))


async def _resolve_property_a(property_a: PropertyEntity):
    async def _resolve(row):
        return property_a

    return _resolve


async def _seed(db_session, tenant_a, property_a) -> None:
    """Create the reservation the update tests will then update, via the ingestor itself."""
    report = await _ingestor(db_session).ingest(
        tenant_id=tenant_a.id,
        rows=[_row()],
        resolve_property=await _resolve_property_a(property_a),
        now=NOW,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )
    assert report.created == 1


async def _events(db_session) -> list[TimelineEventModel]:
    return (await db_session.execute(select(TimelineEventModel))).scalars().all()


@pytest.mark.asyncio
async def test_an_update_that_changes_a_field_emits_one_reservation_updated_event(
    db_session, tenant_a, property_a
) -> None:
    await _seed(db_session, tenant_a, property_a)

    new_check_in = NOW.date() + timedelta(days=1)
    report = await _ingestor(db_session).ingest(
        tenant_id=tenant_a.id,
        rows=[_row(check_in_date=new_check_in)],
        resolve_property=await _resolve_property_a(property_a),
        now=LATER,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )

    assert report.created == 0
    assert report.updated == 1
    assert report.skipped == 0

    events = await _events(db_session)
    updated_events = [e for e in events if e.event_type is TimelineEventType.RESERVATION_UPDATED]
    assert len(updated_events) == 1
    assert "check_in_date" in updated_events[0].metadata_["changed"]


@pytest.mark.asyncio
async def test_an_update_that_cancels_emits_one_cancelled_event_and_no_updated_event(
    db_session, tenant_a, property_a
) -> None:
    await _seed(db_session, tenant_a, property_a)

    report = await _ingestor(db_session).ingest(
        tenant_id=tenant_a.id,
        rows=[_row(status="CANCELLED")],
        resolve_property=await _resolve_property_a(property_a),
        now=LATER,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )

    assert report.created == 0
    assert report.updated == 1
    assert report.skipped == 0

    events = await _events(db_session)
    cancelled_events = [
        e for e in events if e.event_type is TimelineEventType.RESERVATION_CANCELLED
    ]
    updated_events = [e for e in events if e.event_type is TimelineEventType.RESERVATION_UPDATED]
    assert len(cancelled_events) == 1
    assert updated_events == []
    assert cancelled_events[0].metadata_["changed"]["status"]["to"] == "CANCELLED"


@pytest.mark.asyncio
async def test_a_no_op_update_emits_no_event_and_stays_skipped(
    db_session, tenant_a, property_a
) -> None:
    await _seed(db_session, tenant_a, property_a)
    before = await _events(db_session)

    # The exact same row again: `update_details` has nothing to apply.
    report = await _ingestor(db_session).ingest(
        tenant_id=tenant_a.id,
        rows=[_row()],
        resolve_property=await _resolve_property_a(property_a),
        now=LATER,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )

    assert report.created == 0
    assert report.updated == 0
    assert report.skipped == 1
    assert await _events(db_session) == before


@pytest.mark.asyncio
async def test_counts_are_unaffected_by_whether_an_event_fired(
    db_session, tenant_a, property_a
) -> None:
    """R6: `created`/`updated`/`skipped` must mean exactly what they meant before this change."""
    await _seed(db_session, tenant_a, property_a)

    changed = await _ingestor(db_session).ingest(
        tenant_id=tenant_a.id,
        rows=[_row(check_in_date=NOW.date() + timedelta(days=1))],
        resolve_property=await _resolve_property_a(property_a),
        now=LATER,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )
    assert (changed.created, changed.updated, changed.skipped) == (0, 1, 0)

    unchanged = await _ingestor(db_session).ingest(
        tenant_id=tenant_a.id,
        rows=[_row(check_in_date=NOW.date() + timedelta(days=1))],
        resolve_property=await _resolve_property_a(property_a),
        now=LATER,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )
    assert (unchanged.created, unchanged.updated, unchanged.skipped) == (0, 0, 1)


@pytest.mark.asyncio
async def test_ingest_does_not_crash_with_no_advancer_even_on_a_cancellation(
    db_session, tenant_a, property_a
) -> None:
    """`advance=None` is the default; a batch that newly-cancels a row must not require it."""
    await _seed(db_session, tenant_a, property_a)

    report = await _ingestor(db_session, advance=None).ingest(
        tenant_id=tenant_a.id,
        rows=[_row(status="CANCELLED")],
        resolve_property=await _resolve_property_a(property_a),
        now=LATER,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )

    assert report.updated == 1
    row = (
        await db_session.execute(
            select(ReservationModel).where(ReservationModel.external_pms_id == EXTERNAL_ID)
        )
    ).scalar_one()
    assert row.status == "CANCELLED"


class _CountingAdvancer:
    """Stands in for `AdvancePropertyStatesUseCase`; proves R5/D3 by never being called."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(self, *, tenant_id, trigger, now):
        self.calls.append((tenant_id, trigger))
        return None


@pytest.mark.asyncio
async def test_a_date_change_on_an_awaiting_checkin_property_emits_an_event_but_no_transition(
    db_session, tenant_a, property_a
) -> None:
    """R5 and design D3: a date-only update is evidence enough on its own — it deliberately
    gets no new `PropertyStateTrigger`, must not raise, and must not touch
    `current_operational_state`, even while the property is `AWAITING_CHECKIN` for this very
    stay (the same precondition `RESERVATION_CANCELLED_BEFORE_CHECKIN` cares about)."""
    await _seed(db_session, tenant_a, property_a)
    property_a.current_operational_state = PropertyOperationalState.AWAITING_CHECKIN
    await db_session.flush()

    advance = _CountingAdvancer()
    new_check_in = NOW.date() + timedelta(days=1)
    report = await _ingestor(db_session, advance=advance).ingest(
        tenant_id=tenant_a.id,
        rows=[_row(check_in_date=new_check_in)],
        resolve_property=await _resolve_property_a(property_a),
        now=LATER,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )

    assert report.created == 0
    assert report.updated == 1
    assert report.skipped == 0

    events = await _events(db_session)
    updated_events = [e for e in events if e.event_type is TimelineEventType.RESERVATION_UPDATED]
    assert len(updated_events) == 1
    assert "check_in_date" in updated_events[0].metadata_["changed"]

    # D3: no new trigger fired, and the property's state is untouched.
    assert advance.calls == []
    await db_session.refresh(property_a)
    assert property_a.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN
