"""Use cases of the reservations module (R1, R2, R5; design D4, D6, D15, D16).

One use case is one business operation and one transaction: it orchestrates the aggregate
and its ports and calls `commit()` exactly once (design D4). No business rule lives here —
the invariants are in `Reservation` — and no `sqlalchemy` import either, which is what
`tests/test_layering.py` enforces for this layer.

Every mutating use case writes the reservation **and** its `TimelineEvent` before that
single commit, so a failure recording the event leaves the reservation unchanged (R2.6).
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from app.core.unit_of_work import UnitOfWork
from app.guests.application.resolution import ManualGuestIdentityInput, ResolveOrCreateGuest
from app.guests.domain.repositories import GuestRepository
from app.guests.domain.ports import GuestEmailExclusion
from app.guests.domain.value_objects import GuestSummary
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus, NotificationType
from app.notifications.domain.repositories import NotificationLogRepository
from app.properties.domain.clock_triggers import effective_bounds
from app.properties.domain.enums import PropertyStatus
from app.properties.domain.exceptions import IncompatibleTransitionContextError
from app.properties.domain.repositories import PropertyRepository
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import PaymentStatus, ReservationChannel, ReservationStatus
from app.reservations.domain.exceptions import (
    GuestNotFoundError,
    InactivePropertyError,
    PropertyNotFoundError,
    ReservationNotFoundError,
    ReservationValidationError,
)
from app.reservations.domain.notifications import render_checkin_reminder_email
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

# A manual booking is created by a person, on a channel that is not an OTA feed. The OTA
# channels arrive through the PMS sync or the CSV import, which set `external_pms_id`.
MANUAL_CHANNELS = frozenset({ReservationChannel.MANUAL, ReservationChannel.DIRECT})


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
    guest: ManualGuestIdentityInput | None = None
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

    def __post_init__(self) -> None:
        """A hand-made booking may only carry a manual channel (R1.2).

        The rule lives on the command, not in the router where it started (the architecture
        review caught it: `steering/backend.md` — "la lógica nunca vive en el router"), so it
        holds for every caller of `CreateReservationUseCase`, HTTP or not.

        Why the rule exists: an OTA channel means the booking came from the PMS feed and
        carries an `external_pms_id`, which is the idempotency key of the ingest paths. One
        typed by hand would have no such id, so the next sync would import the same stay again
        as a second row.
        """
        if self.channel not in MANUAL_CHANNELS:
            raise ReservationValidationError(
                "channel must be MANUAL or DIRECT when creating a reservation by hand; "
                f"{self.channel.value} arrives through the PMS sync or the CSV import"
            )
        if self.guest_id is not None and self.guest is not None:
            raise ReservationValidationError("guest_id and guest are mutually exclusive")


@dataclass(frozen=True)
class ReservationDetail:
    """A reservation plus the guest data the caller is allowed to see (R1.8, design D17).

    The two derived `property_*` fields follow `reservation-property-identity` (R2, D1,
    D4, D5): the linked `Property` is resolved server-side, and the answer degrades to
    `None` (with its key) when the FK does not resolve inside the token's tenant — which
    is why the field exists on the read model and not as a separate endpoint.
    """

    reservation: Reservation
    guest: GuestSummary | None = None
    property_name: str | None = None
    property_internal_code: str | None = None


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
                metadata=metadata or {},
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
        guest_email_exclusion: GuestEmailExclusion,
    ) -> None:
        self._reservations = reservations
        self._properties = properties
        self._guests = guests
        self._timeline = _TimelineWriter(timeline)
        self._uow = uow
        # The resolver shares the caller-owned GuestRepository and transaction-scoped
        # exclusion. Section 3 supplies the identity input and invokes it before the
        # Reservation is built; constructing it here closes the manual composition root now.
        self._guest_resolver = ResolveOrCreateGuest(guests, guest_email_exclusion)

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
        property = await self._properties.get(tenant_id, command.property_id)
        if property is None:
            raise PropertyNotFoundError("Property does not exist")
        if property.status is PropertyStatus.INACTIVE:
            # A retired home does not take new bookings (`properties-crud` design D11). The
            # check is here and not in the entity because it is a fact about the PROPERTY, not
            # an invariant of the reservation, and `Reservation.create` has no property to ask.
            raise InactivePropertyError("Property is retired and does not accept reservations")
        resolved_guest_id = command.guest_id
        if command.guest is not None:
            resolved_guest_id = await self._guest_resolver.execute(
                tenant_id=tenant_id, identity=command.guest, now=now
            )
        if resolved_guest_id is not None:
            if await self._guests.get(tenant_id, resolved_guest_id) is None:
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
            guest_id=resolved_guest_id,
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

        was_cancelled = reservation.status is ReservationStatus.CANCELLED
        applied = reservation.update_details(changes, now=now)
        if not applied:
            return reservation

        # A PATCH that sets `status: CANCELLED` cancels the booking as surely as a DELETE
        # does, so it must leave the SAME evidence (R2.3). Recording only
        # `RESERVATION_UPDATED` would mean a reservation could end up cancelled with no
        # `RESERVATION_CANCELLED` anywhere in the timeline — and since `cancel()` is
        # idempotent, a later DELETE would add nothing either, so the event would never
        # appear. The timeline is the whole audit trail of a reservation until
        # `AuditLog` arrives (design D14), so this is not a cosmetic distinction.
        # Found by the security review of section 4.
        cancelled_now = (
            not was_cancelled and reservation.status is ReservationStatus.CANCELLED
        )
        await self._reservations.save(tenant_id, reservation)
        await self._timeline.record(
            tenant_id=tenant_id,
            property_id=reservation.property_id,
            reservation_id=reservation.id,
            event_type=(
                TimelineEventType.RESERVATION_CANCELLED
                if cancelled_now
                else TimelineEventType.RESERVATION_UPDATED
            ),
            title="Reservation cancelled" if cancelled_now else "Reservation updated",
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
        self,
        *,
        reservations: ReservationRepository,
        guests: GuestRepository,
        properties: PropertyRepository,
    ) -> None:
        self._reservations = reservations
        self._guests = guests
        self._properties = properties

    async def execute(
        self, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> ReservationDetail:
        """The reservation, its linked guest (no document data, R1.8, D17), and the
        readable identity of its linked property (R2, D1, D4, D5).

        A `property_id` pointing to another tenant — or to a row that does not exist at
        all within the token's tenant — answers the two new fields as `None` with their
        key, **not** a `404`. The entity is the reservation; the FK that happened not to
        resolve does not promote itself to the primary key (D5 rejects `404` here on
        purpose: the use-case design of `tech-incident-context` chose `404`, but there
        the property is the body of the response, while here it is three of thirty).
        """
        reservation = await self._reservations.get(tenant_id, reservation_id)
        if reservation is None:
            raise ReservationNotFoundError("Reservation does not exist")
        guest = (
            await self._guests.get(tenant_id, reservation.guest_id)
            if reservation.guest_id is not None
            else None
        )
        property = await self._properties.get(tenant_id, reservation.property_id)
        # `guest_full_name` rides on the entity so `ReservationResponse.from_domain` and
        # `ReservationDetailResponse.from_detail` can carry it without learning yet
        # another composition pattern — the alternative was to thread it through the DTO
        # factory, which the contract reviewer (D1) already rejected for the listing.
        enriched = replace(
            reservation,
            property_name=property.name if property is not None else None,
            property_internal_code=property.internal_code if property is not None else None,
            guest_full_name=guest.full_name if guest is not None else None,
        )
        return ReservationDetail(
            reservation=enriched,
            guest=guest,
            # `None` on a missing/foreign-tenant FK is the deliberate "degrade, do not
            # 404" choice of D5 — the field's key is always present in the response.
            property_name=property.name if property is not None else None,
            property_internal_code=property.internal_code if property is not None else None,
        )


class ListReservationsUseCase:
    def __init__(
        self,
        *,
        reservations: ReservationRepository,
        properties: PropertyRepository,
        guests: GuestRepository,
    ) -> None:
        self._reservations = reservations
        self._properties = properties
        self._guests = guests

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        filters: ReservationFilters,
        page: int,
        per_page: int,
    ) -> Page:
        """Filtered and paginated (R1.1), enriched with the readable identity of every
        reservation's property and guest (R1, R3, R5, D1, D3, D4).

        The tenant comes from the caller's context and is never a filter the client can
        set (R5.2) — `ReservationFilters` has no `tenant_id` field for that reason.

        Composition lives here, not in the response model (D1). The two batch readers
        run AFTER the page query — once, not per row (D3), each with an explicit
        `tenant_id` per call (D2 of `dashboard-api`). The result is the union of three
        independent queries (one for the page, two batches), which `test_list_identity_queries`
        asserts as a constant statement count.
        """
        page_result = await self._reservations.list(
            tenant_id, filters, page=page, per_page=per_page
        )
        property_ids: set[uuid.UUID] = {
            item.property_id for item in page_result.items if item.property_id is not None
        }
        guest_ids: set[uuid.UUID] = {
            item.guest_id for item in page_result.items if item.guest_id is not None
        }
        # Batches short-circuit on empty input (their own contracts); no need to gate here.
        properties_by_id = {
            prop.id: prop
            for prop in await self._properties.list_for_ids(tenant_id, property_ids)
        }
        guests_by_id = {
            guest.id: guest
            for guest in await self._guests.list_for_ids(tenant_id, guest_ids)
        }
        enriched: list[Reservation] = []
        for item in page_result.items:
            prop = properties_by_id.get(item.property_id)
            guest = guests_by_id.get(item.guest_id) if item.guest_id is not None else None
            enriched.append(replace(item, property_name=prop.name if prop else None,
                                    property_internal_code=prop.internal_code if prop else None,
                                    guest_full_name=guest.full_name if guest else None))
        return Page(items=tuple(enriched), total=page_result.total)


# --- `guest-scheduled-comms` R1: check-in reminders at 24h and 2h (design D1-D8, D11, D12) ----

#: `related_type` this use case's rows are dedup-keyed on (design D8) — a reservation, never
#: a property or a guest, because R1's dedup is per-reservation-and-type.
RELATED_TYPE_RESERVATION = "reservation"

#: How far the candidate query looks on either side of `now` (design D4). Narrow on purpose:
#: this is not `properties.domain.clock_triggers.CANDIDATE_LOOKAHEAD`/`CANDIDATE_LOOKBEHIND`
#: (which bound a different job's much wider backlog-recovery window) — a guest reminder only
#: ever fires inside a 24h lead, so one day on each side already covers every property's
#: timezone offset and both lead times. `list_for_properties`' own stay-overlap semantics make
#: this an upper bound on the candidate set, never a hole in it: the precise threshold check
#: below is what actually decides.
_CANDIDATE_WINDOW = timedelta(days=1)

#: Which `NotificationType` is due at which lead time before the check-in instant (design D1,
#: D3). A mapping, not two near-identical `if`s, so the loop that evaluates both is the same
#: code for each.
_CHECKIN_REMINDER_LEADS: dict[NotificationType, timedelta] = {
    NotificationType.CHECKIN_REMINDER_24H: timedelta(hours=24),
    NotificationType.CHECKIN_REMINDER_2H: timedelta(hours=2),
}


@dataclass
class CheckinReminderReport:
    """What one tenant's sweep did (R1, R4).

    `candidates` counts every `CONFIRMED` reservation the candidate query returned, whether or
    not either reminder type turned out to be due for it. `skipped_missing_email` and
    `skipped_invalid_local_time` are R1.3's and the DST risk's "skip and count" cases,
    respectively — neither aborts the tenant's sweep (R4).
    """

    candidates: int = 0
    written: int = 0
    skipped_missing_email: int = 0
    skipped_invalid_local_time: int = 0


class SendCheckinRemindersUseCase:
    """`send_checkin_reminders` (PRD §8.3, `guest-scheduled-comms` R1; design D1, D3-D5, D8,
    D11, D12).

    One sweep evaluates both `CHECKIN_REMINDER_24H` and `CHECKIN_REMINDER_2H` per candidate
    reservation (design D1) — they share the identical "confirmed reservation, property-timezone
    instant, threshold, dedup" shape and differ only in their lead time
    (`_CHECKIN_REMINDER_LEADS`).

    **The candidate query is deliberately approximate; the threshold check is not** (design D3,
    D4). `list_for_properties`' stay-overlap window can return a reservation whose check-in is
    not actually near `now` (e.g. a long stay that started days ago); that costs nothing but a
    wasted iteration, because `effective_bounds` plus the threshold comparison below is the
    real gate, and it is symmetric with a missed tick: `checkin_instant - lead <= now <
    checkin_instant` stays true until the check-in itself, so a reservation a sweep does not
    reach this tick is still caught by the next one, and `exists_for` (design D8) is what stops
    a caught-twice reservation from being reminded twice.

    **Recipient resolution only runs for a reservation with at least one due type** (design
    D5) — resolving the guest is one more query, and most candidates the window returns are not
    due at all.
    """

    def __init__(
        self,
        *,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        guests: GuestRepository,
        notifications: NotificationLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._properties = properties
        self._reservations = reservations
        self._guests = guests
        self._notifications = notifications
        self._uow = uow

    async def execute(
        self, *, tenant_id: uuid.UUID, now: datetime
    ) -> CheckinReminderReport:
        report = CheckinReminderReport()

        properties = await self._properties.list_all(tenant_id)
        if not properties:
            return report
        properties_by_id = {property.id: property for property in properties}

        date_from = (now - _CANDIDATE_WINDOW).date()
        date_to = (now + _CANDIDATE_WINDOW).date()
        candidates = await self._reservations.list_for_properties(
            tenant_id, list(properties_by_id), date_from, date_to
        )

        for reservation in candidates:
            if reservation.status is not ReservationStatus.CONFIRMED:
                continue
            report.candidates += 1

            property = properties_by_id.get(reservation.property_id)
            if property is None:
                # The reservation's own FK guarantees the property exists within the tenant;
                # unreachable in practice, and treated the same as an incompatible context
                # rather than raised, so a wiring surprise cannot abort the whole sweep.
                report.skipped_invalid_local_time += 1
                continue

            try:
                checkin_instant, _ = effective_bounds(property, reservation)
            except IncompatibleTransitionContextError:
                # A nonexistent/ambiguous local wall time, or an invalid property timezone
                # (design *Risks*): skip and count this reservation for this tick rather than
                # letting one bad property abort the tenant's sweep. The next tick tries again
                # with the same inputs, so this is not silent unless the property never gets
                # fixed — which is the same tolerance `_active_reservations` callers already
                # give this error.
                report.skipped_invalid_local_time += 1
                continue

            due_types = [
                notification_type
                for notification_type, lead in _CHECKIN_REMINDER_LEADS.items()
                if checkin_instant - lead <= now < checkin_instant
            ]
            if not due_types:
                continue

            recipient = await self._recipient(tenant_id, reservation.guest_id)
            if recipient is None:
                report.skipped_missing_email += 1
                continue
            email, language = recipient

            check_in_time_local = reservation.check_in_time or property.default_check_in_time
            subject, body = render_checkin_reminder_email(
                language,
                property.name,
                reservation.check_in_date,
                check_in_time_local,
            )

            if NotificationType.CHECKIN_REMINDER_24H in due_types and await self._write_if_new(
                tenant_id,
                reservation.id,
                NotificationType.CHECKIN_REMINDER_24H,
                email,
                subject,
                body,
                now,
            ):
                report.written += 1

            if NotificationType.CHECKIN_REMINDER_2H in due_types and await self._write_if_new(
                tenant_id,
                reservation.id,
                NotificationType.CHECKIN_REMINDER_2H,
                email,
                subject,
                body,
                now,
            ):
                report.written += 1

        await self._uow.commit()
        return report

    async def _write_if_new(
        self,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        notification_type: NotificationType,
        email: str,
        subject: str,
        body: str,
        now: datetime,
    ) -> bool:
        """`exists_for` dedup (design D8), then one of exactly two literal `NotificationLog(...)`
        constructions — one per `NotificationType` member, never a single call parameterised by
        a variable.

        **Not folded into one call with `notification_type.value`, on purpose.**
        `tests/notifications/test_writer_census.py` counts a writer only when the AST sees the
        literal shape `NotificationType.<X>.value` at the `NotificationLog(...)` call site
        itself — a local variable holding the member is invisible to it. `exists_for` has no
        such constraint (the census only matches `NotificationLog`/`Escalation` callees), so its
        `notification_type=notification_type.value` above stays a plain parameter.
        """
        if await self._notifications.exists_for(
            tenant_id,
            related_type=RELATED_TYPE_RESERVATION,
            related_id=reservation_id,
            notification_type=notification_type.value,
        ):
            return False

        if notification_type is NotificationType.CHECKIN_REMINDER_24H:
            await self._notifications.add(
                tenant_id,
                NotificationLog(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    recipient_contact=email,
                    channel=NotificationChannel.EMAIL,
                    notification_type=NotificationType.CHECKIN_REMINDER_24H.value,
                    created_at=now,
                    updated_at=now,
                    subject=subject,
                    body=body,
                    status=NotificationStatus.PENDING,
                    related_type=RELATED_TYPE_RESERVATION,
                    related_id=reservation_id,
                    # D11: none of the four writers this change adds carries an SLA deadline —
                    # a guest reminder has nobody to escalate to if "late".
                    sla_deadline_at=None,
                ),
            )
        elif notification_type is NotificationType.CHECKIN_REMINDER_2H:
            await self._notifications.add(
                tenant_id,
                NotificationLog(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    recipient_contact=email,
                    channel=NotificationChannel.EMAIL,
                    notification_type=NotificationType.CHECKIN_REMINDER_2H.value,
                    created_at=now,
                    updated_at=now,
                    subject=subject,
                    body=body,
                    status=NotificationStatus.PENDING,
                    related_type=RELATED_TYPE_RESERVATION,
                    related_id=reservation_id,
                    sla_deadline_at=None,
                ),
            )
        else:  # pragma: no cover - defensive; only the two members above are ever passed
            raise ValueError(f"Unsupported check-in reminder type: {notification_type!r}")
        return True

    async def _recipient(
        self, tenant_id: uuid.UUID, guest_id: uuid.UUID | None
    ) -> tuple[str, str] | None:
        """The guest's email and preferred language, or `None` to skip-and-count (R1.3,
        design D5).

        Mirrors `SendGuestAccessTokenUseCase._recipient`
        (`guests/application/portal.py:915-941`), adapted from "raise
        `GuestContactMissingError`" to "return `None`": there is no HTTP caller here to answer
        `422` to, only a sweep that must count the candidate and move on.
        """
        if guest_id is None:
            return None
        guest = await self._guests.get(tenant_id, guest_id)
        if guest is None:
            return None
        email = (guest.email or "").strip()
        if not email:
            return None
        return email, guest.preferred_language
