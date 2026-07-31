"""The one place a `ReservationDTO` becomes a reservation (R2.4, R2.5, R3, R4, design D9).

Both ingest routes — the PMS sync and the CSV import — go through `ReservationIngestor`, so
idempotency, guest linking, timeline events and per-row error reporting behave identically
whichever door the data came in by. Two copies of this logic would drift on exactly the
detail that matters: whether a row already seen is created again.

How a property is resolved is the ONLY difference between the two routes, so it is a
parameter (`resolve_property`), not a branch inside.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.core.unit_of_work import UnitOfWork
from app.guests.domain.entities import Guest
from app.guests.domain.repositories import GuestRepository
from app.integrations.domain.dtos import ReservationDTO
from app.properties.domain.entities import Property
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.domain.exceptions import (
    DuplicateExternalReservationError,
    ReservationValidationError,
)
from app.reservations.domain.repositories import ReservationRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

PropertyResolver = Callable[[ReservationDTO], Awaitable[Property | None]]


@dataclass
class RowError:
    """Why one row was skipped, with enough to find it again."""

    reference: str
    reason: str


@dataclass
class IngestReport:
    """The outcome of one ingest run (R3.3, R4.1).

    `created`/`updated` are counted separately because that difference is what proves
    idempotency: a second identical run must show zero created.
    """

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[RowError] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": [{"reference": error.reference, "reason": error.reason} for error in self.errors],
        }


class ReservationIngestor:
    def __init__(
        self,
        *,
        reservations: ReservationRepository,
        guests: GuestRepository,
        timeline: TimelineEventRepository,
    ) -> None:
        self._reservations = reservations
        self._guests = guests
        self._timeline = timeline

    async def ingest(
        self,
        *,
        tenant_id: uuid.UUID,
        rows: list[ReservationDTO],
        resolve_property: PropertyResolver,
        now: datetime,
        actor_type: TimelineActorType,
        actor_user_id: uuid.UUID | None,
        source: str,
    ) -> IngestReport:
        """Ingest every row, reporting failures instead of aborting (R3.4, R4.2).

        One bad row must not cost the good ones: a CSV a person just uploaded, or a PMS page
        with one unknown property, still imports everything it can. Every failure mode
        therefore ends as a `RowError`, never as an exception out of this method — except a
        programming error, which is not caught on purpose.
        """
        report = IngestReport()
        for row in rows:
            try:
                await self._ingest_row(
                    tenant_id=tenant_id,
                    row=row,
                    resolve_property=resolve_property,
                    now=now,
                    actor_type=actor_type,
                    actor_user_id=actor_user_id,
                    source=source,
                    report=report,
                )
            except (
                ReservationValidationError,
                DuplicateExternalReservationError,
                AmbiguousPropertyExternalIdError,
                ValueError,
            ) as error:
                report.skipped += 1
                report.errors.append(RowError(reference=row.external_id, reason=str(error)))
        return report

    async def _ingest_row(
        self,
        *,
        tenant_id: uuid.UUID,
        row: ReservationDTO,
        resolve_property: PropertyResolver,
        now: datetime,
        actor_type: TimelineActorType,
        actor_user_id: uuid.UUID | None,
        source: str,
        report: IngestReport,
    ) -> None:
        prop = await resolve_property(row)
        if prop is None:
            report.skipped += 1
            report.errors.append(
                RowError(
                    reference=row.external_id,
                    reason=f"Unknown property {row.property_external_id!r} for this tenant",
                )
            )
            return

        existing = (
            await self._reservations.find_by_external_pms_id(tenant_id, row.external_id)
            if row.external_id
            else None
        )
        guest_id = await self._link_guest(tenant_id=tenant_id, row=row, now=now)

        if existing is not None:
            changes = _updatable_fields(row, guest_id=guest_id)
            applied = existing.update_details(changes, now=now)
            if applied:
                await self._reservations.save(tenant_id, existing)
                report.updated += 1
            else:
                # Known and unchanged: neither an update nor an error. Counting it as
                # updated would make a second identical sync look like it did work (R3.3).
                report.skipped += 1
            return

        reservation = Reservation.create(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=prop.id,
            channel=_channel(row.channel),
            check_in_date=row.check_in_date,
            check_out_date=row.check_out_date,
            now=now,
            adults=row.adults,
            children=row.children,
            guest_id=guest_id,
            external_pms_id=row.external_id or None,
            external_channel_id=row.external_channel_id,
            status=_status(row.status),
            check_in_time=row.check_in_time,
            check_out_time=row.check_out_time,
            gross_amount=row.gross_amount,
            ota_commission=row.ota_commission,
            net_amount=_net_amount(row),
            currency=row.currency,
            special_requests=row.special_requests,
        )
        await self._reservations.add(tenant_id, reservation)
        await self._record_imported(
            tenant_id=tenant_id,
            reservation=reservation,
            now=now,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            source=source,
        )
        report.created += 1

    async def _link_guest(
        self, *, tenant_id: uuid.UUID, row: ReservationDTO, now: datetime
    ) -> uuid.UUID | None:
        """Reuse the guest that matches by email, create one otherwise (R3.5, design D8).

        With no name and no email there is nothing to link: the reservation stays
        guest-less rather than growing an empty `Guest` per imported row.
        """
        if row.guest_email:
            existing = await self._guests.find_by_email(tenant_id, row.guest_email)
            if existing is not None:
                return existing.id
        if not row.guest_name and not row.guest_email:
            return None
        guest = Guest(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            full_name=row.guest_name or (row.guest_email or "Unknown guest"),
            created_at=now,
            updated_at=now,
            email=row.guest_email,
            phone=row.guest_phone,
        )
        await self._guests.add(tenant_id, guest)
        return guest.id

    async def _record_imported(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation: Reservation,
        now: datetime,
        actor_type: TimelineActorType,
        actor_user_id: uuid.UUID | None,
        source: str,
    ) -> None:
        event = TimelineEventFactory.create(
            TimelineEventData(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=reservation.property_id,
                reservation_id=reservation.id,
                actor_type=actor_type,
                actor_user_id=actor_user_id,
                event_type=TimelineEventType.RESERVATION_IMPORTED,
                title=f"Reservation imported from {source}",
                created_at=now,
                severity=TimelineSeverity.INFO,
                metadata={
                    "source": source,
                    "external_pms_id": reservation.external_pms_id,
                    "channel": reservation.channel.value,
                    "check_in_date": reservation.check_in_date.isoformat(),
                    "check_out_date": reservation.check_out_date.isoformat(),
                },
            )
        )
        await self._timeline.add(tenant_id, event)


def _updatable_fields(row: ReservationDTO, *, guest_id: uuid.UUID | None) -> dict[str, object]:
    """What an ingest run is allowed to change on a reservation it already knows.

    Only fields the provider owns. `internal_notes` is ours and never overwritten from
    outside, and `status` is included because a cancellation upstream must reach us.
    """
    changes: dict[str, object] = {
        "check_in_date": row.check_in_date,
        "check_out_date": row.check_out_date,
        "check_in_time": row.check_in_time,
        "check_out_time": row.check_out_time,
        "adults": row.adults,
        "children": row.children,
        "gross_amount": row.gross_amount,
        "ota_commission": row.ota_commission,
        "net_amount": _net_amount(row),
        "currency": row.currency,
        "special_requests": row.special_requests,
        "channel": _channel(row.channel),
    }
    if row.status:
        changes["status"] = _status(row.status)
    if guest_id is not None:
        changes["guest_id"] = guest_id
    return changes


def _channel(value: str) -> ReservationChannel:
    try:
        return ReservationChannel(value.strip().upper())
    except ValueError as error:
        raise ReservationValidationError(f"Unknown channel {value!r}") from error


def _status(value: str | None) -> ReservationStatus:
    if not value:
        return ReservationStatus.CONFIRMED
    try:
        return ReservationStatus(value.strip().upper())
    except ValueError as error:
        raise ReservationValidationError(f"Unknown reservation status {value!r}") from error


def _net_amount(row: ReservationDTO):
    """Derived, not taken on trust: net is gross minus the OTA's cut.

    PRD §16's DTO carries no `net_amount`, so computing it here is the only way the field
    of PRD §7.7 gets filled from an import — and deriving it means the three amounts cannot
    contradict each other.
    """
    if row.gross_amount is None:
        return None
    if row.ota_commission is None:
        return row.gross_amount
    return row.gross_amount - row.ota_commission
