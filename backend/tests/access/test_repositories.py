"""`SqlAlchemyAccessRecordRepository` — R1, R3, design D1/D2.

Two things beyond CRUD get the attention here: the **projection** to
`reservations.access_status`, which is the whole reason `save` writes two tables, and the
**tenant isolation** DoD §28.18 requires per module.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessRecordStatus
from app.access.domain.exceptions import AccessRecordNotFoundError
from app.access.domain.repositories import AccessRecordFilters
from app.access.infrastructure.models import AccessRecordModel
from app.access.infrastructure.repositories import SqlAlchemyAccessRecordRepository
from app.core.tenancy import CrossTenantWriteError
from app.reservations.domain.enums import ReservationAccessStatus, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from tests.access.conftest import (
    insert_access_record,
    insert_property,
    insert_reservation,
)

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def _entity(tenant, prop, reservation=None, *, status=AccessRecordStatus.PENDING):
    return AccessRecord(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        created_at=NOW,
        updated_at=NOW,
        reservation_id=reservation.id if reservation is not None else None,
        status=status,
    )


async def _reservation_access_status(db_session, reservation_id):
    row = await db_session.execute(
        select(ReservationModel.access_status).where(ReservationModel.id == reservation_id)
    )
    return row.scalar_one()


# --- the projection of design D1 --------------------------------------------------


@pytest.mark.asyncio
async def test_adding_a_record_projects_onto_the_reservation(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)

    await SqlAlchemyAccessRecordRepository(db_session).add(
        tenant_a.id, _entity(tenant_a, property_a, reservation)
    )

    assert (
        await _reservation_access_status(db_session, reservation.id)
        is ReservationAccessStatus.PENDING
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("record_status", "projected"),
    [
        (AccessRecordStatus.MANUAL_ADDED, ReservationAccessStatus.MANUAL_ADDED),
        (AccessRecordStatus.CREATED_EXTERNAL, ReservationAccessStatus.CREATED_EXTERNAL),
        (AccessRecordStatus.DELIVERED, ReservationAccessStatus.DELIVERED),
        (AccessRecordStatus.EXPIRED, ReservationAccessStatus.EXPIRED),
        # The ASSUMPTION of design D1: PRD §7.6 closes `ReservationAccessStatus` without a
        # `REVOKED`, and the only thing that revokes an access is a cancelled stay — for
        # which "no access required" is what actually applies.
        (AccessRecordStatus.REVOKED, ReservationAccessStatus.NOT_REQUIRED),
    ],
)
async def test_every_record_status_projects(
    db_session, tenant_a, property_a, record_status, projected
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    record = await insert_access_record(
        db_session, tenant_a, property_a, reservation=reservation
    )
    repository = SqlAlchemyAccessRecordRepository(db_session)
    entity = await repository.get(tenant_a.id, record.id)
    assert entity is not None
    entity.status = record_status

    await repository.save(tenant_a.id, entity)

    assert await _reservation_access_status(db_session, reservation.id) is projected


@pytest.mark.asyncio
async def test_a_record_without_a_reservation_projects_nowhere(
    db_session, tenant_a, property_a
) -> None:
    """`access_records.reservation_id` is nullable, and the column belongs to a stay."""
    await SqlAlchemyAccessRecordRepository(db_session).add(
        tenant_a.id, _entity(tenant_a, property_a, None)
    )
    # No exception, nothing to assert about a reservation that does not exist.


@pytest.mark.asyncio
async def test_saving_a_vanished_record_raises_instead_of_writing_nothing(
    db_session, tenant_a, property_a
) -> None:
    """The caller has already written a timeline event by then (design D14)."""
    repository = SqlAlchemyAccessRecordRepository(db_session)

    with pytest.raises(AccessRecordNotFoundError):
        await repository.save(tenant_a.id, _entity(tenant_a, property_a))


# --- tenant isolation (DoD §28.18, rule 1) ----------------------------------------


@pytest.mark.asyncio
async def test_reads_never_cross_tenants(
    db_session, tenant_a, tenant_b, property_a, property_b
) -> None:
    theirs = await insert_access_record(db_session, tenant_b, property_b)
    repository = SqlAlchemyAccessRecordRepository(db_session)

    assert await repository.get(tenant_a.id, theirs.id) is None
    page = await repository.list(tenant_a.id, AccessRecordFilters(), page=1, per_page=20)
    assert page.items == ()
    assert page.total == 0


@pytest.mark.asyncio
async def test_writes_refuse_an_entity_of_another_tenant(
    db_session, tenant_a, tenant_b, property_b
) -> None:
    repository = SqlAlchemyAccessRecordRepository(db_session)
    theirs = _entity(tenant_b, property_b)

    with pytest.raises(CrossTenantWriteError):
        await repository.add(tenant_a.id, theirs)
    with pytest.raises(CrossTenantWriteError):
        await repository.save(tenant_a.id, theirs)


@pytest.mark.asyncio
async def test_the_revocable_join_does_not_reach_a_neighbours_reservation(
    db_session, tenant_a, tenant_b, property_a, property_b
) -> None:
    """The JOIN is on `reservation_id` alone, so without the second tenant predicate a
    neighbour's cancelled booking would drag our record into the revocation list — the same
    trap `cleaning` documented for `cleaning_checklist_completions`."""
    theirs = await insert_reservation(
        db_session, tenant_b, property_b, status=ReservationStatus.CANCELLED
    )
    await insert_access_record(db_session, tenant_b, property_b, reservation=theirs)

    found = await SqlAlchemyAccessRecordRepository(db_session).list_revocable(
        tenant_a.id, limit=50
    )

    assert found == []


# --- the reconciler's queries (design D2) -----------------------------------------


@pytest.mark.asyncio
async def test_a_confirmed_reservation_without_a_record_is_queued(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)

    found = await SqlAlchemyAccessRecordRepository(db_session).list_reservations_missing_records(
        tenant_a.id, limit=50
    )

    assert [row.reservation_id for row in found] == [reservation.id]
    assert found[0].property_id == property_a.id
    assert found[0].cancelled is False


@pytest.mark.asyncio
async def test_a_reservation_that_already_has_one_is_not_queued_again(
    db_session, tenant_a, property_a
) -> None:
    """R1.3 — idempotence by construction: the condition is "confirmed **without** a record"."""
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    await insert_access_record(db_session, tenant_a, property_a, reservation=reservation)

    found = await SqlAlchemyAccessRecordRepository(db_session).list_reservations_missing_records(
        tenant_a.id, limit=50
    )

    assert found == []


@pytest.mark.asyncio
async def test_a_pending_booking_is_not_queued(db_session, tenant_a, property_a) -> None:
    """Nobody has agreed to it yet, so there is no access to arrange."""
    await insert_reservation(
        db_session, tenant_a, property_a, status=ReservationStatus.PENDING
    )

    found = await SqlAlchemyAccessRecordRepository(db_session).list_reservations_missing_records(
        tenant_a.id, limit=50
    )

    assert found == []


@pytest.mark.asyncio
async def test_a_cancelled_booking_is_queued_and_flagged(
    db_session, tenant_a, property_a
) -> None:
    """It gets a record in `REVOKED`, not no record at all.

    Otherwise every run would find it again and create a `PENDING` access for a stay that is
    off — a reconciler that never converges.
    """
    await insert_reservation(
        db_session, tenant_a, property_a, status=ReservationStatus.CANCELLED
    )

    found = await SqlAlchemyAccessRecordRepository(db_session).list_reservations_missing_records(
        tenant_a.id, limit=50
    )

    assert len(found) == 1
    assert found[0].cancelled is True


@pytest.mark.asyncio
async def test_a_live_record_of_a_cancelled_booking_is_revocable(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    record = await insert_access_record(
        db_session, tenant_a, property_a, reservation=reservation
    )
    reservation.status = ReservationStatus.CANCELLED
    await db_session.flush()

    found = await SqlAlchemyAccessRecordRepository(db_session).list_revocable(
        tenant_a.id, limit=50
    )

    assert [row.id for row in found] == [record.id]


@pytest.mark.asyncio
async def test_an_already_revoked_record_is_not_revocable_again(
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

    found = await SqlAlchemyAccessRecordRepository(db_session).list_revocable(
        tenant_a.id, limit=50
    )

    assert found == []


@pytest.mark.asyncio
async def test_expirable_finds_nothing_because_nothing_writes_valid_to(
    db_session, tenant_a, property_a
) -> None:
    """OQ4, pinned as an absence.

    No code writes `valid_from`/`valid_to` — that is a real access provider's job and the MVP
    has none. The query is built and tested so the path exists; this test is what will start
    failing, usefully, the day a provider begins filling those columns.
    """
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    await insert_access_record(
        db_session,
        tenant_a,
        property_a,
        reservation=reservation,
        status=AccessRecordStatus.DELIVERED,
    )

    found = await SqlAlchemyAccessRecordRepository(db_session).list_expirable(
        tenant_a.id, now=NOW, limit=50
    )

    assert found == []


@pytest.mark.asyncio
async def test_expirable_finds_a_record_whose_window_has_closed(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    record = await insert_access_record(
        db_session,
        tenant_a,
        property_a,
        reservation=reservation,
        status=AccessRecordStatus.DELIVERED,
        valid_to=NOW - timedelta(hours=1),
    )
    # And one that is still open, plus one that is `PENDING` — which has nothing to expire and
    # whose entity would refuse the transition if the query handed it over.
    await insert_access_record(
        db_session,
        tenant_a,
        property_a,
        status=AccessRecordStatus.DELIVERED,
        valid_to=NOW + timedelta(hours=1),
    )
    await insert_access_record(
        db_session,
        tenant_a,
        property_a,
        status=AccessRecordStatus.PENDING,
        valid_to=NOW - timedelta(hours=1),
    )

    found = await SqlAlchemyAccessRecordRepository(db_session).list_expirable(
        tenant_a.id, now=NOW, limit=50
    )

    assert [row.id for row in found] == [record.id]


# --- listing and filters (R3.1) ---------------------------------------------------


@pytest.mark.asyncio
async def test_the_filters_narrow_independently(db_session, tenant_a, property_a) -> None:
    other_property = await insert_property(db_session, tenant_a, code="PAJARITOS8")
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    mine = await insert_access_record(
        db_session, tenant_a, property_a, reservation=reservation
    )
    await insert_access_record(
        db_session, tenant_a, other_property, status=AccessRecordStatus.DELIVERED
    )
    repository = SqlAlchemyAccessRecordRepository(db_session)

    by_property = await repository.list(
        tenant_a.id, AccessRecordFilters(property_id=property_a.id), page=1, per_page=20
    )
    by_reservation = await repository.list(
        tenant_a.id,
        AccessRecordFilters(reservation_id=reservation.id),
        page=1,
        per_page=20,
    )
    by_status = await repository.list(
        tenant_a.id,
        AccessRecordFilters(status=AccessRecordStatus.DELIVERED),
        page=1,
        per_page=20,
    )

    assert [row.id for row in by_property.items] == [mine.id]
    assert [row.id for row in by_reservation.items] == [mine.id]
    assert by_status.total == 1
    assert by_status.items[0].status is AccessRecordStatus.DELIVERED


@pytest.mark.asyncio
async def test_get_by_reservation_returns_the_stays_record(
    db_session, tenant_a, property_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    record = await insert_access_record(
        db_session, tenant_a, property_a, reservation=reservation
    )

    found = await SqlAlchemyAccessRecordRepository(db_session).get_by_reservation(
        tenant_a.id, reservation.id
    )

    assert found is not None
    assert found.id == record.id


@pytest.mark.asyncio
async def test_the_stored_row_never_holds_a_plaintext_code(
    db_session, tenant_a, property_a
) -> None:
    """Design D9 at the storage layer: there is no column, so there is nothing to check —
    which is exactly the assertion worth making, over the model's own columns."""
    columns = {column.name for column in AccessRecordModel.__table__.columns}

    assert "code" not in columns
    assert "code_plain" not in columns
    assert "code_masked" in columns
