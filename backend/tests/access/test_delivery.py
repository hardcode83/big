"""`DeliverAccessInstructionsUseCase` against fakes (`guest-scheduled-comms` R3, R4; design
D5, D6, D8, D9, D12).

Unit tests with in-memory fakes of the ports, as `steering/backend-architecture.md` prescribes
for `application/`: fakes, never the real DB and never a SQLAlchemy mock. `ReservationRepository`
and `GuestRepository` fakes are reused from `tests.reservations.doubles` (already the shared
home of those two fakes — `tests/properties/doubles.py` re-exports from the same module for
the same reason); this file adds the two doubles those tests do not need: a fake
`AccessRecordRepository` exposing only `list_awaiting_instructions`, and the
`NotificationLogRepository` fake this use case dedups and writes through.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.access.application.use_cases import DeliverAccessInstructionsUseCase
from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessCreatedMode, AccessProvider, AccessRecordStatus
from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.entities import Guest
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus, NotificationType
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus

from tests.reservations.doubles import FakeGuestRepository, FakeReservationRepository, FakeUnitOfWork

TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()


@dataclass
class FakeAccessRecordRepository:
    """`AccessRecordRepository`, of which only `list_awaiting_instructions` is reachable from
    this use case — it never reads `get`/`save` and never mutates a record."""

    records: dict[uuid.UUID, AccessRecord] = field(default_factory=dict)

    def add_record(self, record: AccessRecord) -> AccessRecord:
        self.records[record.id] = record
        return record

    async def list_awaiting_instructions(
        self, tenant_id: uuid.UUID, *, limit: int
    ) -> list[AccessRecord]:
        rows = [
            record
            for record in self.records.values()
            if record.tenant_id == tenant_id
            and record.status
            in (AccessRecordStatus.MANUAL_ADDED, AccessRecordStatus.CREATED_EXTERNAL)
            and record.code_masked is not None
        ]
        rows.sort(key=lambda record: (record.created_at, str(record.id)))
        return rows[:limit]

    # The rest of the Protocol is unreachable from this use case; a call here is a bug.
    async def get(self, tenant_id, record_id):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def get_by_reservation(self, tenant_id, reservation_id):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def list(self, tenant_id, filters, *, page, per_page):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def add(self, tenant_id, record):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def save(self, tenant_id, record):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def list_reservations_missing_records(self, tenant_id, *, limit):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def list_expirable(self, tenant_id, *, now, limit):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def list_revocable(self, tenant_id, *, limit):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")


@dataclass
class FakeNotificationLogRepository:
    """`NotificationLogRepository`, of which only `add` and `exists_for` are reachable from
    this use case — identical shape to `tests/reservations/test_checkin_reminders.py`'s own."""

    rows: list[NotificationLog] = field(default_factory=list)

    async def add(self, tenant_id: uuid.UUID, log: NotificationLog) -> None:
        if log.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="notification_log", entity_tenant_id=log.tenant_id, acting_tenant_id=tenant_id
            )
        self.rows.append(log)

    async def exists_for(
        self, tenant_id: uuid.UUID, *, related_type: str, related_id: uuid.UUID, notification_type: str
    ) -> bool:
        assert related_type is not None and related_id is not None
        return any(
            row.tenant_id == tenant_id
            and row.related_type == related_type
            and row.related_id == related_id
            and row.notification_type == notification_type
            for row in self.rows
        )

    async def list_sla_breach_candidates(self, tenant_id, now):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def mark_breached(self, tenant_id, log):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def list_pending(self, tenant_id, limit):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def list_for_recipient(self, tenant_id, recipient_user_id, *, page, per_page, unread=None, channel=NotificationChannel.IN_APP):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def mark_read(self, tenant_id, user_id, log_id):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def count_unread(self, tenant_id, user_id, *, channel=NotificationChannel.IN_APP):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def mark_all_read(self, tenant_id, user_id):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def record_attempt(self, tenant_id, log_id, *, status, attempts, sent_at, last_error):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")

    async def cancel_sla_deadline(self, tenant_id, *, related_type, related_id, notification_type):  # pragma: no cover
        raise AssertionError("not exercised by DeliverAccessInstructionsUseCase")


def _now() -> datetime:
    return datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _reservation(
    *, tenant_id=TENANT, guest_id: uuid.UUID | None, **overrides: Any
) -> Reservation:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=uuid.uuid4(),
        channel=ReservationChannel.MANUAL,
        check_in_date=_now().date(),
        check_out_date=_now().date() + timedelta(days=2),
        nights=2,
        created_at=_now(),
        updated_at=_now(),
        guest_id=guest_id,
        status=ReservationStatus.CONFIRMED,
    )
    defaults.update(overrides)
    return Reservation(**defaults)


def _guest(
    *, tenant_id=TENANT, email: str | None = "guest@example.com", **overrides: Any
) -> Guest:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        full_name="Ana Guest",
        created_at=_now(),
        updated_at=_now(),
        email=email,
    )
    defaults.update(overrides)
    return Guest(**defaults)


def _record(
    *,
    tenant_id=TENANT,
    reservation_id: uuid.UUID | None,
    status: AccessRecordStatus = AccessRecordStatus.MANUAL_ADDED,
    code_masked: str | None = "****42",
    **overrides: Any,
) -> AccessRecord:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=uuid.uuid4(),
        created_at=_now(),
        updated_at=_now(),
        reservation_id=reservation_id,
        provider=AccessProvider.MANUAL,
        status=status,
        code_masked=code_masked,
        created_mode=AccessCreatedMode.MANUAL,
    )
    defaults.update(overrides)
    return AccessRecord(**defaults)


@dataclass
class World:
    records: FakeAccessRecordRepository
    reservations: FakeReservationRepository
    guests: FakeGuestRepository
    notifications: FakeNotificationLogRepository
    uow: FakeUnitOfWork
    use_case: DeliverAccessInstructionsUseCase


def _world(*, batch_size: int = 100) -> World:
    records = FakeAccessRecordRepository()
    reservations = FakeReservationRepository()
    guests = FakeGuestRepository()
    notifications = FakeNotificationLogRepository()
    uow = FakeUnitOfWork()
    use_case = DeliverAccessInstructionsUseCase(
        records=records,
        reservations=reservations,
        guests=guests,
        notifications=notifications,
        uow=uow,
        batch_size=batch_size,
    )
    return World(records, reservations, guests, notifications, uow, use_case)


@pytest.mark.asyncio
async def test_a_manual_added_record_with_a_masked_code_fires_exactly_once() -> None:
    world = _world()
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(guest_id=guest.id)
    world.reservations.reservations[reservation.id] = reservation
    record = world.records.add_record(
        _record(reservation_id=reservation.id, status=AccessRecordStatus.MANUAL_ADDED)
    )

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.candidates == 1
    assert report.written == 1
    assert len(world.notifications.rows) == 1
    row = world.notifications.rows[0]
    assert row.notification_type == NotificationType.ACCESS_INSTRUCTIONS_SENT.value
    assert row.channel is NotificationChannel.EMAIL
    assert row.status is NotificationStatus.PENDING
    assert row.recipient_contact == "guest@example.com"
    assert row.related_type == "access_record"
    assert row.related_id == record.id
    assert row.sla_deadline_at is None
    assert row.body is not None
    assert "****42" in row.body
    assert world.uow.commits == 1


@pytest.mark.asyncio
async def test_a_created_external_record_with_a_masked_code_also_fires() -> None:
    world = _world()
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(guest_id=guest.id)
    world.reservations.reservations[reservation.id] = reservation
    world.records.add_record(
        _record(reservation_id=reservation.id, status=AccessRecordStatus.CREATED_EXTERNAL)
    )

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.written == 1


@pytest.mark.asyncio
async def test_a_second_run_does_not_duplicate() -> None:
    world = _world()
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(guest_id=guest.id)
    world.reservations.reservations[reservation.id] = reservation
    world.records.add_record(_record(reservation_id=reservation.id))

    first = await world.use_case.execute(tenant_id=TENANT, now=_now())
    second = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert first.written == 1
    assert second.written == 0
    assert len(world.notifications.rows) == 1


@pytest.mark.asyncio
async def test_a_record_with_no_guest_email_is_skipped_and_counted() -> None:
    world = _world()
    guest = world.guests.add_guest(_guest(email=None))
    reservation = _reservation(guest_id=guest.id)
    world.reservations.reservations[reservation.id] = reservation
    world.records.add_record(_record(reservation_id=reservation.id))

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.written == 0
    assert report.skipped_missing_email == 1
    assert report.candidates == 1
    assert world.notifications.rows == []


@pytest.mark.asyncio
async def test_a_record_with_no_reservation_id_is_skipped_and_counted() -> None:
    world = _world()
    world.records.add_record(_record(reservation_id=None))

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.written == 0
    assert report.skipped_missing_email == 1


@pytest.mark.asyncio
async def test_a_reservation_with_no_guest_id_is_skipped_and_counted() -> None:
    world = _world()
    reservation = _reservation(guest_id=None)
    world.reservations.reservations[reservation.id] = reservation
    world.records.add_record(_record(reservation_id=reservation.id))

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.written == 0
    assert report.skipped_missing_email == 1


@pytest.mark.asyncio
async def test_a_reservation_that_does_not_resolve_is_skipped_and_counted() -> None:
    """The record's `reservation_id` points nowhere `FakeReservationRepository` knows about —
    unreachable in production (the FK guarantees it exists), but the use case must not raise."""
    world = _world()
    world.records.add_record(_record(reservation_id=uuid.uuid4()))

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.written == 0
    assert report.skipped_missing_email == 1


@pytest.mark.asyncio
async def test_a_delivered_record_is_not_a_candidate_at_all() -> None:
    """R3.4/design D9 — an operator's own confirmation stops the automatic send from firing
    again; a `DELIVERED` record has nothing this sweep needs to do."""
    world = _world()
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(guest_id=guest.id)
    world.reservations.reservations[reservation.id] = reservation
    world.records.add_record(
        _record(reservation_id=reservation.id, status=AccessRecordStatus.DELIVERED)
    )

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.candidates == 0
    assert report.written == 0


@pytest.mark.asyncio
async def test_a_pending_record_with_no_code_is_not_a_candidate_at_all() -> None:
    world = _world()
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(guest_id=guest.id)
    world.reservations.reservations[reservation.id] = reservation
    world.records.add_record(
        _record(
            reservation_id=reservation.id,
            status=AccessRecordStatus.PENDING,
            code_masked=None,
        )
    )

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.candidates == 0
    assert report.written == 0


@pytest.mark.asyncio
async def test_the_use_case_never_touches_the_access_record_status_or_mark_delivered() -> None:
    """R3.4/design D9, asserted explicitly: this use case reads `AccessRecordRepository`
    through exactly one method (`list_awaiting_instructions`) and never calls `get`/`save`, so
    `AccessRecord.status` cannot move as a side effect of this send, and `mark_delivered`
    (`MarkAccessDeliveredUseCase`) stays the operator's own, entirely separate action."""
    world = _world()
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(guest_id=guest.id)
    world.reservations.reservations[reservation.id] = reservation
    record = world.records.add_record(
        _record(reservation_id=reservation.id, status=AccessRecordStatus.MANUAL_ADDED)
    )
    stored_status_before = world.records.records[record.id].status

    await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert world.records.records[record.id].status == stored_status_before
    assert world.records.records[record.id].status is AccessRecordStatus.MANUAL_ADDED
    # `DeliverAccessInstructionsUseCase` has no dependency the fake would need to satisfy a
    # `mark_delivered` call through — `_AccessOperationBase`'s collaborators (provider,
    # timeline, audit) are simply absent from its constructor.
    assert not hasattr(world.use_case, "_provider")
    assert not hasattr(world.use_case, "_timeline")
    assert not hasattr(world.use_case, "_audit")


@pytest.mark.asyncio
async def test_a_second_tenants_qualifying_record_is_neither_read_nor_written() -> None:
    """Tenant isolation — a review-round finding in section 2, fixed up front here per the
    change's own implementation notes: a second tenant's qualifying `AccessRecord` must not be
    read (it must not count as a candidate) or written (no notification for it)."""
    world = _world()
    guest = world.guests.add_guest(_guest())
    reservation = _reservation(guest_id=guest.id)
    world.reservations.reservations[reservation.id] = reservation
    world.records.add_record(_record(reservation_id=reservation.id))

    other_guest = world.guests.add_guest(_guest(tenant_id=OTHER_TENANT, email="other@example.com"))
    other_reservation = _reservation(tenant_id=OTHER_TENANT, guest_id=other_guest.id)
    world.reservations.reservations[other_reservation.id] = other_reservation
    world.records.add_record(_record(tenant_id=OTHER_TENANT, reservation_id=other_reservation.id))

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.candidates == 1
    assert report.written == 1
    assert len(world.notifications.rows) == 1
    assert world.notifications.rows[0].tenant_id == TENANT
    assert all(row.recipient_contact != "other@example.com" for row in world.notifications.rows)


@pytest.mark.asyncio
async def test_the_batch_size_bounds_one_run() -> None:
    world = _world(batch_size=2)
    for _ in range(3):
        guest = world.guests.add_guest(_guest(email=f"{uuid.uuid4()}@example.com"))
        reservation = _reservation(guest_id=guest.id)
        world.reservations.reservations[reservation.id] = reservation
        world.records.add_record(_record(reservation_id=reservation.id))

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report.candidates == 2
    assert report.written == 2


@pytest.mark.asyncio
async def test_no_candidates_short_circuits_without_touching_other_ports() -> None:
    world = _world()

    report = await world.use_case.execute(tenant_id=TENANT, now=_now())

    assert report == type(report)()
    assert world.uow.commits == 1
