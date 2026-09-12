"""The one place a `ReservationDTO` becomes a reservation (R2.4, R2.5, R3, R4, design D9).

All three ingest routes — the PMS sync, the CSV import and the demo seed — go through
`ReservationIngestor`, so idempotency, guest linking, timeline events and per-row error
reporting behave identically whichever door the data came in by. Two copies of this logic
would drift on exactly the detail that matters: whether a row already seen is created again.

How a property is resolved is the ONLY difference between the three routes, so it is a
parameter (`resolve_property`), not a branch inside.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.core.unit_of_work import UnitOfWork
from app.guests.application.resolution import ManualGuestIdentityInput, ResolveOrCreateGuest
from app.guests.domain.ports import GuestEmailExclusion
from app.guests.domain.repositories import GuestRepository
from app.integrations.domain.dtos import ReservationDTO
from app.integrations.domain.ports import PropertyStateAdvancer
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyStatus
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.reservations.domain.entities import (
    INGEST_OWNED_FIELDS,
    Reservation,
    net_amount_from,
)
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


@dataclass(frozen=True)
class IngestRow:
    """One row to ingest, with whatever identifies it for the person reading the report.

    `line` is the CSV line number (the header is line 1) and is `None` for the PMS sync, which
    has no lines — there its identity is the provider's `external_id`. Carrying both is what
    lets R4.2 report "línea 7" instead of an empty reference for a row whose optional
    `external_pms_id` was blank. The feature-scale architecture review found that gap.
    """

    dto: ReservationDTO
    line: int | None = None


@dataclass
class RowError:
    """Why one row was skipped, with enough for a person to find it again."""

    reason: str
    reference: str | None = None
    line: int | None = None


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
    provider_failures: list[str] = field(default_factory=list)
    """Providers whose sync could not run at all. Empty for the CSV path, which has no provider.

    Its own field and not just an entry in `errors`, because it decides the command's EXIT CODE
    and a stringly-typed check over `errors` would be a contract nobody could see. A per-provider
    failure stopped aborting the run (one provider down must not cost a tenant the others), and
    the QA panel of sections 6-8 caught what that silently broke: `PmsUnavailableError` no longer
    reached `main`, so a property whose provider has no credential exited **0** with "created 0" —
    the exact confusion design D9 exists to prevent. Isolation and a loud exit are not in
    conflict; they just need separate channels.
    """

    def as_dict(self) -> dict[str, object]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": [
                {"line": error.line, "reference": error.reference, "reason": error.reason}
                for error in self.errors
            ],
        }


class ReservationIngestor:
    """The known production writer for ingest-time guest email resolution.

    PMS/CSV/demo ingest reaches ``ResolveOrCreateGuest`` here. Guest Portal check-in creates
    its reservation guest without email and remains outside this policy; ``seed_demo`` may seed
    controlled demo Guests directly. Manual reservations use the same resolver from their own
    use case, so this class owns the ingest-specific DTO/default/reporting concerns only.
    """

    def __init__(
        self,
        *,
        reservations: ReservationRepository,
        guests: GuestRepository,
        timeline: TimelineEventRepository,
        email_exclusion: GuestEmailExclusion,
        advance: PropertyStateAdvancer | None = None,
    ) -> None:
        self._reservations = reservations
        self._guests = guests
        self._timeline = timeline
        self._resolver = ResolveOrCreateGuest(guests, email_exclusion)
        self._advance = advance

    async def ingest(
        self,
        *,
        tenant_id: uuid.UUID,
        rows: list[IngestRow],
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
        any_newly_cancelled = False
        for item in rows:
            row = item.dto
            try:
                newly_cancelled = await self._ingest_row(
                    tenant_id=tenant_id,
                    row=row,
                    line=item.line,
                    resolve_property=resolve_property,
                    now=now,
                    actor_type=actor_type,
                    actor_user_id=actor_user_id,
                    source=source,
                    report=report,
                )
                any_newly_cancelled = any_newly_cancelled or newly_cancelled
            except (
                ReservationValidationError,
                DuplicateExternalReservationError,
                AmbiguousPropertyExternalIdError,
                ValueError,
            ) as error:
                report.skipped += 1
                report.errors.append(
                    RowError(
                        reason=str(error),
                        reference=row.external_id or None,
                        line=item.line,
                    )
                )
        if self._advance is not None and any_newly_cancelled:
            # Once per batch, not per row (design D2): the advancer re-evaluates every property
            # of the tenant for this trigger, so calling it once already covers every reservation
            # the batch cancelled.
            await self._advance.execute(
                tenant_id=tenant_id,
                trigger=PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN,
                now=now,
            )
        return report

    async def _ingest_row(
        self,
        *,
        tenant_id: uuid.UUID,
        row: ReservationDTO,
        line: int | None,
        resolve_property: PropertyResolver,
        now: datetime,
        actor_type: TimelineActorType,
        actor_user_id: uuid.UUID | None,
        source: str,
        report: IngestReport,
    ) -> bool:
        """Ingest one row, returning whether it newly cancelled a reservation (R3.1, design D2).

        The return value feeds `ingest()`'s batch-wide decision of whether to call `advance` —
        it is never used for anything per-row, since the property-transition trigger fires once
        for the whole batch, not once per cancelled row.
        """
        prop = await resolve_property(row)
        if prop is None:
            report.skipped += 1
            report.errors.append(
                RowError(
                    reason=f"Unknown property {row.property_external_id!r} for this tenant",
                    reference=row.external_id or None,
                    line=line,
                )
            )
            return False
        if prop.status is PropertyStatus.INACTIVE:
            # A retired home does not take new bookings (`properties-crud` design D11). Both
            # batch paths — the CSV import and the PMS sync — reach this one branch, so the
            # rule lives here once instead of in each resolver.
            #
            # It is a SKIPPED ROW and not a raise: aborting the batch over one retired property
            # would cost a tenant every other row, which is the same reasoning R3.4 gives for
            # reporting an unresolvable property instead of failing the run. And it is its own
            # branch rather than making the resolver return `None`, because "you retired this
            # one" and "no such property" are different answers and a person reading the report
            # has to be able to act on the difference.
            report.skipped += 1
            report.errors.append(
                RowError(
                    reason=(
                        f"Property {row.property_external_id!r} is retired and does not "
                        "accept reservations"
                    ),
                    reference=row.external_id or None,
                    line=line,
                )
            )
            return False

        existing = (
            await self._reservations.find_by_external_pms_id(tenant_id, row.external_id)
            if row.external_id
            else None
        )
        guest_id = await self._link_guest(tenant_id=tenant_id, row=row, now=now)

        if existing is not None:
            was_cancelled = existing.status is ReservationStatus.CANCELLED
            changes = _updatable_fields(row, guest_id=guest_id)
            applied = existing.update_details(changes, now=now)
            if applied:
                await self._reservations.save(tenant_id, existing)
                newly_cancelled = (
                    not was_cancelled and existing.status is ReservationStatus.CANCELLED
                )
                await self._record_updated(
                    tenant_id=tenant_id,
                    reservation=existing,
                    newly_cancelled=newly_cancelled,
                    applied=applied,
                    now=now,
                    actor_type=actor_type,
                    actor_user_id=actor_user_id,
                )
                report.updated += 1
                return newly_cancelled
            else:
                # Known and unchanged: neither an update nor an error. Counting it as
                # updated would make a second identical sync look like it did work (R3.3), and
                # with nothing applied there is no evidence to record (R2.1).
                report.skipped += 1
            return False

        reservation = Reservation.create(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            property_id=prop.id,
            channel=ReservationChannel.parse(row.channel),
            check_in_date=row.check_in_date,
            check_out_date=row.check_out_date,
            now=now,
            adults=row.adults,
            children=row.children,
            guest_id=guest_id,
            external_pms_id=row.external_id or None,
            external_channel_id=row.external_channel_id,
            status=ReservationStatus.parse_ingested(row.status),
            check_in_time=row.check_in_time,
            check_out_time=row.check_out_time,
            gross_amount=row.gross_amount,
            ota_commission=row.ota_commission,
            net_amount=net_amount_from(row.gross_amount, row.ota_commission),
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
        return False

    async def _link_guest(
        self, *, tenant_id: uuid.UUID, row: ReservationDTO, now: datetime
    ) -> uuid.UUID | None:
        """Reuse the guest that matches by email, create one otherwise (R3.5, design D8).

        With no name and no email there is nothing to link: the reservation stays
        guest-less rather than growing an empty `Guest` per imported row.
        """
        normalized_name = row.guest_name.strip() if row.guest_name else None
        normalized_email = row.guest_email.strip() if row.guest_email else None
        if not normalized_email and not normalized_name:
            return None
        return await self._resolver.execute(
            tenant_id=tenant_id,
            identity=ManualGuestIdentityInput(
                full_name=normalized_name or normalized_email or "Unknown guest",
                email=normalized_email,
                phone=row.guest_phone,
            ),
            now=now,
        )

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

    async def _record_updated(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation: Reservation,
        newly_cancelled: bool,
        applied: dict[str, object],
        now: datetime,
        actor_type: TimelineActorType,
        actor_user_id: uuid.UUID | None,
    ) -> None:
        """Record the update path's evidence of change (R1), mirroring `_record_imported`.

        The event-selection rule is the one `use_cases.py:294-319`'s manual `PATCH` already
        proved: `RESERVATION_CANCELLED` only when this update is what newly cancelled the
        reservation, `RESERVATION_UPDATED` for every other applied change — and `applied` is
        passed straight through as `metadata["changed"]` rather than recomputed, since
        `update_details` already returns it in the shape the timeline wants.
        """
        event = TimelineEventFactory.create(
            TimelineEventData(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                property_id=reservation.property_id,
                reservation_id=reservation.id,
                actor_type=actor_type,
                actor_user_id=actor_user_id,
                event_type=(
                    TimelineEventType.RESERVATION_CANCELLED
                    if newly_cancelled
                    else TimelineEventType.RESERVATION_UPDATED
                ),
                title="Reservation cancelled" if newly_cancelled else "Reservation updated",
                created_at=now,
                severity=TimelineSeverity.INFO,
                metadata={"changed": applied},
            )
        )
        await self._timeline.add(tenant_id, event)


def _updatable_fields(row: ReservationDTO, *, guest_id: uuid.UUID | None) -> dict[str, object]:
    """Translate a provider row into the fields an ingest run may write (R3.2).

    Pure translation: WHICH fields an external system is allowed to own is a domain rule
    (`INGEST_OWNED_FIELDS`), and the derivation of `net_amount` is another (`net_amount_from`).
    This function only maps the DTO onto them — and asserts it stayed inside the allow-list, so
    adding a field here without deciding it in the domain fails loudly.
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
        "net_amount": net_amount_from(row.gross_amount, row.ota_commission),
        "currency": row.currency,
        "special_requests": row.special_requests,
        "channel": ReservationChannel.parse(row.channel),
    }
    if row.status:
        changes["status"] = ReservationStatus.parse_ingested(row.status)
    if guest_id is not None:
        changes["guest_id"] = guest_id
    assert set(changes) <= INGEST_OWNED_FIELDS
    return changes
