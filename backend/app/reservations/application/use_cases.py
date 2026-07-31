"""Use cases of the reservations module (R1, R2, R5; design D4, D6, D15, D16).

One use case is one business operation and one transaction: it orchestrates the aggregate
and its ports and calls `commit()` exactly once (design D4). No business rule lives here —
the invariants are in `Reservation` — and no `sqlalchemy` import either, which is what
`tests/test_layering.py` enforces for this layer.

Every mutating use case writes the reservation **and** its `TimelineEvent` before that
single commit, so a failure recording the event leaves the reservation unchanged (R2.6).
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.core.unit_of_work import UnitOfWork
from app.guests.domain.repositories import GuestRepository
from app.guests.domain.value_objects import GuestSummary
from app.properties.domain.repositories import PropertyRepository
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import PaymentStatus, ReservationChannel
from app.reservations.domain.exceptions import (
    GuestNotFoundError,
    PropertyNotFoundError,
    ReservationNotFoundError,
)
from app.reservations.domain.repositories import (
    Page,
    ReservationFilters,
    ReservationRepository,
)
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData


@dataclass(frozen=True)
class CreateReservationCommand:
    """What `POST /reservations` accepts (R1.2).

    `nights` and `total_guests` are absent on purpose: they are derived by the aggregate
    (see `Reservation.create`). So is `status`, which starts at its default — a manual
    booking that is already `CANCELLED` is not something to create in one step.
    """

    property_id: uuid.UUID
    channel: ReservationChannel
    check_in_date: date
    check_out_date: date
    adults: int = 1
    children: int = 0
    guest_id: uuid.UUID | None = None
    check_in_time: time | None = None
    check_out_time: time | None = None
    gross_amount: Decimal | None = None
    ota_commission: Decimal | None = None
    net_amount: Decimal | None = None
    currency: str = "EUR"
    payment_status: PaymentStatus = PaymentStatus.PENDING
    cleaning_required: bool = True
    special_requests: str | None = None
    internal_notes: str | None = None
    external_channel_id: str | None = None


@dataclass(frozen=True)
class ReservationDetail:
    """A reservation plus the guest data the caller is allowed to see (R1.8, design D17)."""

    reservation: Reservation
    guest: GuestSummary | None = None


@dataclass
class _TimelineWriter:
    """Builds and records one event, always through the domain factory (R2.7).

    Shared by the four mutating use cases so the actor rules of design D15 are applied in
    one place: `USER` events carry the acting user, `SYSTEM` events must not — a
    constraint `TimelineEventFactory` also enforces, which is why nothing here re-checks
    it.
    """

    timeline: TimelineEventRepository

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        reservation_id: uuid.UUID,
        event_type: TimelineEventType,
        title: str,
        now: datetime,
        actor_type: TimelineActorType,
        actor_user_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TimelineEvent:
        event = TimelineEventFactory.create(
            TimelineEventData(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=property_id,
                reservation_id=reservation_id,
                actor_type=actor_type,
                actor_user_id=actor_user_id,
                event_type=event_type,
                title=title,
                created_at=now,
                severity=TimelineSeverity.INFO,
                metadata=metadata,
            )
        )
        await self.timeline.add(tenant_id, event)
        return event


class CreateReservationUseCase:
    def __init__(
        self,
        *,
        reservations: ReservationRepository,
        properties: PropertyRepository,
        guests: GuestRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reservations = reservations
        self._properties = properties
        self._guests = guests
        self._timeline = _TimelineWriter(timeline)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        command: CreateReservationCommand,
        now: datetime,
    ) -> Reservation:
        """Create a manual reservation and its timeline event (R1.2, R2.1).

        The property is resolved through its tenant-scoped port, so a `property_id` from
        another tenant is indistinguishable from one that does not exist (R1.4, design
        D6) — and the resolution is also what satisfies the precondition of D18 before an
        event is written.
        """
        if await self._properties.get(tenant_id, command.property_id) is None:
            raise PropertyNotFoundError("Property does not exist")
        if command.guest_id is not None:
            if await self._guests.get(tenant_id, command.guest_id) is None:
                raise GuestNotFoundError("Guest does not exist")

        reservation = Reservation.create(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=command.property_id,
            channel=command.channel,
            check_in_date=command.check_in_date,
            check_out_date=command.check_out_date,
            now=now,
            adults=command.adults,
            children=command.children,
            guest_id=command.guest_id,
            check_in_time=command.check_in_time,
            check_out_time=command.check_out_time,
            gross_amount=command.gross_amount,
            ota_commission=command.ota_commission,
            net_amount=command.net_amount,
            currency=command.currency,
            payment_status=command.payment_status,
            cleaning_required=command.cleaning_required,
            special_requests=command.special_requests,
            internal_notes=command.internal_notes,
            external_channel_id=command.external_channel_id,
        )
        await self._reservations.add(tenant_id, reservation)
        await self._timeline.record(
            tenant_id=tenant_id,
            property_id=reservation.property_id,
            reservation_id=reservation.id,
            event_type=TimelineEventType.RESERVATION_CREATED_MANUAL,
            title="Reservation created manually",
            now=now,
            actor_type=TimelineActorType.USER,
            actor_user_id=actor_user_id,
            metadata={
                "channel": reservation.channel.value,
                "check_in_date": reservation.check_in_date.isoformat(),
                "check_out_date": reservation.check_out_date.isoformat(),
                "nights": reservation.nights,
                "total_guests": reservation.total_guests,
            },
        )
        await self._uow.commit()
        return reservation


class UpdateReservationUseCase:
    def __init__(
        self,
        *,
        reservations: ReservationRepository,
        guests: GuestRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reservations = reservations
        self._guests = guests
        self._timeline = _TimelineWriter(timeline)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        reservation_id: uuid.UUID,
        changes: dict[str, Any],
        now: datetime,
    ) -> Reservation:
        """Apply a partial update (R1.5) and record what changed (R2.2).

        A PATCH that changes nothing effectively — no fields, or fields carrying the
        values already stored — writes nothing and records nothing: the timeline is
        evidence of change, not of requests.
        """
        reservation = await self._reservations.get(tenant_id, reservation_id)
        if reservation is None:
            raise ReservationNotFoundError("Reservation does not exist")
        if changes.get("guest_id") is not None and changes["guest_id"] != reservation.guest_id:
            if await self._guests.get(tenant_id, changes["guest_id"]) is None:
                raise GuestNotFoundError("Guest does not exist")

        applied = reservation.update_details(changes, now=now)
        if not applied:
            return reservation

        await self._reservations.save(tenant_id, reservation)
        await self._timeline.record(
            tenant_id=tenant_id,
            property_id=reservation.property_id,
            reservation_id=reservation.id,
            event_type=TimelineEventType.RESERVATION_UPDATED,
            title="Reservation updated",
            now=now,
            actor_type=TimelineActorType.USER,
            actor_user_id=actor_user_id,
            metadata={"changed": applied},
        )
        await self._uow.commit()
        return reservation


class CancelReservationUseCase:
    def __init__(
        self,
        *,
        reservations: ReservationRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._reservations = reservations
        self._timeline = _TimelineWriter(timeline)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        reservation_id: uuid.UUID,
        now: datetime,
    ) -> None:
        """Cancel, idempotently (R1.6, R1.7, R2.3).

        A second `DELETE` finds the reservation already cancelled, writes nothing and adds
        no event — the aggregate reports whether the transition happened, so this does not
        have to compare statuses itself.
        """
        reservation = await self._reservations.get(tenant_id, reservation_id)
        if reservation is None:
            raise ReservationNotFoundError("Reservation does not exist")

        previous_status = reservation.status
        if not reservation.cancel(now=now):
            return

        await self._reservations.save(tenant_id, reservation)
        await self._timeline.record(
            tenant_id=tenant_id,
            property_id=reservation.property_id,
            reservation_id=reservation.id,
            event_type=TimelineEventType.RESERVATION_CANCELLED,
            title="Reservation cancelled",
            now=now,
            actor_type=TimelineActorType.USER,
            actor_user_id=actor_user_id,
            metadata={"previous_status": previous_status.value},
        )
        await self._uow.commit()


class GetReservationUseCase:
    def __init__(
        self, *, reservations: ReservationRepository, guests: GuestRepository
    ) -> None:
        self._reservations = reservations
        self._guests = guests

    async def execute(
        self, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> ReservationDetail:
        """The reservation and its linked guest, without document data (R1.8, D17)."""
        reservation = await self._reservations.get(tenant_id, reservation_id)
        if reservation is None:
            raise ReservationNotFoundError("Reservation does not exist")
        guest = (
            await self._guests.get(tenant_id, reservation.guest_id)
            if reservation.guest_id is not None
            else None
        )
        return ReservationDetail(reservation=reservation, guest=guest)


class ListReservationsUseCase:
    def __init__(self, *, reservations: ReservationRepository) -> None:
        self._reservations = reservations

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: ReservationFilters,
        page: int,
        per_page: int,
    ) -> Page:
        """Filtered and paginated (R1.1).

        The tenant comes from the caller's context and is never a filter the client can
        set (R5.2) — `ReservationFilters` has no `tenant_id` field for that reason.
        """
        return await self._reservations.list(
            tenant_id, filters, page=page, per_page=per_page
        )
