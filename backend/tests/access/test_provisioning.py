"""The access reconciler (R1, R6.2; design D2).

Against the real repository and a real database: what is being verified is the **convergence**
of a sweep — that a second pass writes nothing, that a cancelled stay does not oscillate
between `PENDING` and `REVOKED`, and that a legal status already past `NOT_REQUIRED` is not
dragged backwards. A fake repository would assert the fake's own idea of the work queue.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.access.application.use_cases import ProvisionAccessRecordsUseCase
from app.access.domain.enums import AccessRecordStatus
from app.access.infrastructure.adapters import ManualAccessAdapter
from app.access.infrastructure.models import AccessRecordModel
from app.access.infrastructure.repositories import SqlAlchemyAccessRecordRepository
from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.guests.domain.enums import LegalRegistrationStatus
from app.guests.infrastructure.legal import SqlAlchemyLegalRegistrationInitialiser
from app.reservations.domain.enums import ReservationAccessStatus, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.timeline.domain.enums import TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from tests.access.conftest import insert_access_record, insert_reservation

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


class _Uow:
    """`flush`, not `commit`: the fixture owns the outer transaction."""

    def __init__(self, session) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.flush()


def _use_case(db_session, *, batch_size: int = 100) -> ProvisionAccessRecordsUseCase:
    return ProvisionAccessRecordsUseCase(
        records=SqlAlchemyAccessRecordRepository(db_session),
        provider=ManualAccessAdapter(),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        legal=SqlAlchemyLegalRegistrationInitialiser(db_session),
        uow=_Uow(db_session),
        batch_size=batch_size,
    )


async def _records_of(db_session, tenant_id):
    rows = await db_session.execute(
        select(AccessRecordModel).where(AccessRecordModel.tenant_id == tenant_id)
    )
    return list(rows.scalars())


async def _events_of(db_session, tenant_id, event_type):
    rows = await db_session.execute(
        select(TimelineEventModel).where(
            TimelineEventModel.tenant_id == tenant_id,
            TimelineEventModel.event_type == event_type,
        )
    )
    return list(rows.scalars())


async def _audit_of(db_session, tenant_id):
    rows = await db_session.execute(
        select(AuditLogModel).where(AuditLogModel.tenant_id == tenant_id)
    )
    return list(rows.scalars())


# --- R1.1 / R1.2: create the record and its timeline event ------------------------


@pytest.mark.asyncio
async def test_a_confirmed_reservation_gets_a_pending_record_and_an_event(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.created == 1
    [record] = await _records_of(db_session, tenant_a.id)
    assert record.status is AccessRecordStatus.PENDING
    assert record.reservation_id == reservation.id
    assert record.property_id == property_a.id
    events = await _events_of(db_session, tenant_a.id, TimelineEventType.ACCESS_CODE_PENDING)
    assert len(events) == 1


@pytest.mark.asyncio
async def test_the_projection_reaches_the_reservation(
    db_session, tenant_a, property_a
) -> None:
    """Design D1: `reservations.access_status` has no other writer."""
    reservation = await insert_reservation(db_session, tenant_a, property_a)

    await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    await db_session.refresh(reservation)
    assert reservation.access_status is ReservationAccessStatus.PENDING


@pytest.mark.asyncio
async def test_the_creation_is_audited_without_an_actor(
    db_session, tenant_a, property_a
) -> None:
    """Rule 9 names `AccessRecord`; its named exception is about property state transitions
    and does not extend here. The row exists — it just has no person to name."""
    await insert_reservation(db_session, tenant_a, property_a)

    await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    [entry] = await _audit_of(db_session, tenant_a.id)
    assert entry.action == "ACCESS_RECORD_CREATED"
    assert entry.entity_type == "ACCESS_RECORD"
    assert entry.actor_user_id is None
    assert entry.actor_ip is None


# --- R1.3: idempotence, which is the whole design of a sweep ----------------------


@pytest.mark.asyncio
async def test_a_second_pass_writes_nothing(db_session, tenant_a, property_a) -> None:
    """R1.3 — no second record and no second timeline event.

    The mechanism is the work queue itself ("confirmed **without** a record"), not a flag the
    job keeps: the same thing that makes `EscalateBreachedSlasUseCase` idempotent.
    """
    await insert_reservation(db_session, tenant_a, property_a)
    use_case = _use_case(db_session)

    first = await use_case.execute(tenant_id=tenant_a.id, now=NOW)
    second = await use_case.execute(tenant_id=tenant_a.id, now=NOW + timedelta(minutes=5))

    assert first.created == 1
    assert second.created == 0
    assert len(await _records_of(db_session, tenant_a.id)) == 1
    assert (
        len(await _events_of(db_session, tenant_a.id, TimelineEventType.ACCESS_CODE_PENDING))
        == 1
    )


@pytest.mark.asyncio
async def test_a_reservation_nobody_agreed_to_gets_nothing(
    db_session, tenant_a, property_a
) -> None:
    await insert_reservation(
        db_session, tenant_a, property_a, status=ReservationStatus.PENDING
    )

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.created == 0
    assert await _records_of(db_session, tenant_a.id) == []


# --- R1.4: cancellation ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_live_record_of_a_cancelled_stay_is_revoked(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    record = await insert_access_record(
        db_session, tenant_a, property_a, reservation=reservation
    )
    reservation.status = ReservationStatus.CANCELLED
    await db_session.flush()

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.revoked == 1
    await db_session.refresh(record)
    assert record.status is AccessRecordStatus.REVOKED
    await db_session.refresh(reservation)
    # The ASSUMPTION of design D1: PRD §7.6 has no `REVOKED`, and "no access required" is what
    # actually applies to a cancelled stay.
    assert reservation.access_status is ReservationAccessStatus.NOT_REQUIRED


@pytest.mark.asyncio
async def test_a_stay_cancelled_before_the_job_ever_ran_gets_a_revoked_record(
    db_session, tenant_a, property_a
) -> None:
    """The convergence case, and the reason cancelled stays are in the work queue at all.

    Skipping them would leave the reservation permanently without a record, so every run
    would find it again — and if it were treated like any other, it would get a `PENDING`
    access for a booking that is off.
    """
    await insert_reservation(
        db_session, tenant_a, property_a, status=ReservationStatus.CANCELLED
    )
    use_case = _use_case(db_session)

    first = await use_case.execute(tenant_id=tenant_a.id, now=NOW)
    second = await use_case.execute(tenant_id=tenant_a.id, now=NOW + timedelta(minutes=5))

    assert first.revoked == 1
    assert second.revoked == 0
    [record] = await _records_of(db_session, tenant_a.id)
    assert record.status is AccessRecordStatus.REVOKED


@pytest.mark.asyncio
async def test_a_re_confirmed_stay_gets_a_new_live_record(
    db_session, tenant_a, property_a
) -> None:
    """Found by the feature-scale QA panel: the sweep did **not** converge for this input.

    `Reservation.UPDATABLE_FIELDS` allows `status` and no state machine forbids
    `CANCELLED → CONFIRMED`, so a booking really can come back. The work queue used to
    exclude any reservation that had *any* record, and `revoke()` is terminal — so a
    re-confirmed stay kept its `REVOKED` record and sat at `access_status = NOT_REQUIRED`
    for ever, with an active guest and no access to arrange.

    The revoked row is not resurrected: it is the account of what happened. A new one is
    created beside it.
    """
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    use_case = _use_case(db_session)

    await use_case.execute(tenant_id=tenant_a.id, now=NOW)
    reservation.status = ReservationStatus.CANCELLED
    await db_session.flush()
    await use_case.execute(tenant_id=tenant_a.id, now=NOW + timedelta(minutes=5))
    reservation.status = ReservationStatus.CONFIRMED
    await db_session.flush()

    report = await use_case.execute(tenant_id=tenant_a.id, now=NOW + timedelta(minutes=10))

    assert report.created == 1
    records = await _records_of(db_session, tenant_a.id)
    assert len(records) == 2
    assert sorted(r.status.value for r in records) == ["PENDING", "REVOKED"]
    await db_session.refresh(reservation)
    assert reservation.access_status is ReservationAccessStatus.PENDING


@pytest.mark.asyncio
async def test_the_re_confirmed_stay_then_settles(
    db_session, tenant_a, property_a
) -> None:
    """The other half of convergence: having fixed it, it must not now loop.

    A live stay with a live record is excluded again, so the run after the repair writes
    nothing — otherwise the fix would trade a stuck reservation for a job minting a record
    every five minutes.
    """
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    use_case = _use_case(db_session)
    await use_case.execute(tenant_id=tenant_a.id, now=NOW)
    reservation.status = ReservationStatus.CANCELLED
    await db_session.flush()
    await use_case.execute(tenant_id=tenant_a.id, now=NOW + timedelta(minutes=5))
    reservation.status = ReservationStatus.CONFIRMED
    await db_session.flush()
    await use_case.execute(tenant_id=tenant_a.id, now=NOW + timedelta(minutes=10))

    report = await use_case.execute(tenant_id=tenant_a.id, now=NOW + timedelta(minutes=15))

    assert report == type(report)()
    assert len(await _records_of(db_session, tenant_a.id)) == 2


@pytest.mark.asyncio
async def test_a_cancelled_stay_never_accumulates_revoked_records(
    db_session, tenant_a, property_a
) -> None:
    """The asymmetry that makes the two halves of the work queue different.

    A cancelled stay is excluded by having **any** record; a live one by having a
    non-terminal one. Applying the live rule to a cancelled stay would mint a fresh
    `REVOKED` row on every tick, which is the failure the previous shape avoided and this
    fix must not reintroduce.
    """
    await insert_reservation(
        db_session, tenant_a, property_a, status=ReservationStatus.CANCELLED
    )
    use_case = _use_case(db_session)

    for minute in (0, 5, 10):
        await use_case.execute(tenant_id=tenant_a.id, now=NOW + timedelta(minutes=minute))

    assert len(await _records_of(db_session, tenant_a.id)) == 1


@pytest.mark.asyncio
async def test_an_already_revoked_record_is_not_revoked_again(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(
        db_session, tenant_a, property_a, status=ReservationStatus.CANCELLED
    )
    await insert_access_record(
        db_session,
        tenant_a,
        property_a,
        reservation=reservation,
        status=AccessRecordStatus.REVOKED,
    )

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.revoked == 0


# --- R6.2: the legal registration status ------------------------------------------


@pytest.mark.asyncio
async def test_a_confirmed_stay_starts_waiting_for_guest_data(
    db_session, tenant_a, property_a
) -> None:
    """PRD §17 step 1."""
    reservation = await insert_reservation(db_session, tenant_a, property_a)

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.legal_status_initialised == 1
    await db_session.refresh(reservation)
    assert (
        reservation.legal_registration_status is LegalRegistrationStatus.PENDING_GUEST_DATA
    )


@pytest.mark.asyncio
async def test_a_registration_already_under_way_is_never_dragged_backwards(
    db_session, tenant_a, property_a
) -> None:
    """The sweep runs every five minutes; resetting a `SUBMITTED` stay to "waiting for guest
    data" would be the worst possible kind of idempotence."""
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    reservation.legal_registration_status = LegalRegistrationStatus.SUBMITTED
    await db_session.flush()

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.legal_status_initialised == 0
    await db_session.refresh(reservation)
    assert reservation.legal_registration_status is LegalRegistrationStatus.SUBMITTED


@pytest.mark.asyncio
async def test_a_cancelled_stay_is_not_asked_for_guest_data(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(
        db_session, tenant_a, property_a, status=ReservationStatus.CANCELLED
    )

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.legal_status_initialised == 0
    await db_session.refresh(reservation)
    assert reservation.legal_registration_status is LegalRegistrationStatus.NOT_REQUIRED


# --- expiry (OQ4) and isolation ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_window_that_has_closed_expires(db_session, tenant_a, property_a) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    record = await insert_access_record(
        db_session,
        tenant_a,
        property_a,
        reservation=reservation,
        status=AccessRecordStatus.DELIVERED,
        valid_to=NOW - timedelta(hours=1),
    )

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.expired == 1
    await db_session.refresh(record)
    assert record.status is AccessRecordStatus.EXPIRED


@pytest.mark.asyncio
async def test_the_sweep_never_touches_another_tenant(
    db_session, tenant_a, tenant_b, property_a, property_b
) -> None:
    await insert_reservation(db_session, tenant_b, property_b)

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.created == 0
    assert await _records_of(db_session, tenant_b.id) == []


@pytest.mark.asyncio
async def test_the_batch_size_bounds_one_run(db_session, tenant_a, property_a) -> None:
    for _ in range(3):
        await insert_reservation(db_session, tenant_a, property_a)

    report = await _use_case(db_session, batch_size=2).execute(
        tenant_id=tenant_a.id, now=NOW
    )

    assert report.created == 2


@pytest.mark.asyncio
async def test_a_reservation_that_vanished_is_not_a_crash(
    db_session, tenant_a, property_a
) -> None:
    """A record whose reservation id points nowhere: the projection is an UPDATE with a
    predicate, so zero rows is simply zero rows."""
    record = await insert_access_record(db_session, tenant_a, property_a)
    record.reservation_id = None
    await db_session.flush()

    report = await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    assert report.created == 0


@pytest.mark.asyncio
async def test_records_are_not_created_for_a_reservation_of_another_tenant(
    db_session, tenant_a, tenant_b, property_b
) -> None:
    await insert_reservation(db_session, tenant_b, property_b)

    found = await SqlAlchemyAccessRecordRepository(
        db_session
    ).list_reservations_missing_records(tenant_a.id, limit=50)

    assert found == []
    assert uuid.UUID(str(tenant_a.id)) != uuid.UUID(str(tenant_b.id))


@pytest.mark.asyncio
async def test_a_reservation_row_is_not_moved_by_a_neighbours_sweep(
    db_session, tenant_a, tenant_b, property_b
) -> None:
    theirs = await insert_reservation(db_session, tenant_b, property_b)

    await _use_case(db_session).execute(tenant_id=tenant_a.id, now=NOW)

    stored = await db_session.execute(
        select(ReservationModel.legal_registration_status).where(
            ReservationModel.id == theirs.id
        )
    )
    assert stored.scalar_one() is LegalRegistrationStatus.NOT_REQUIRED
