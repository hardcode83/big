"""In-memory doubles of the ports the reservation use cases depend on.

`steering/backend-architecture.md` and `steering/testing.md` both ask for fakes at this
layer — not mocks of SQLAlchemy — so the use-case tests exercise real orchestration and
fail for behavioural reasons rather than because a call count changed.

Each fake enforces the same tenant scoping the real adapter does: a use case that forgot to
pass `tenant_id`, or passed the wrong one, must fail here too, otherwise these tests would
"prove" isolation that only the integration tests actually check.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date

from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.entities import Guest
from app.guests.domain.value_objects import GuestSummary, normalize_email
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState
from app.reservations.domain.entities import Reservation
from app.reservations.domain.exceptions import DuplicateExternalReservationError
from app.reservations.domain.repositories import Page, ReservationFilters
from app.timeline.domain.entities import TimelineEvent


@dataclass
class FakePropertyRepository:
    properties: dict[uuid.UUID, Property] = field(default_factory=dict)

    def add_property(self, prop: Property) -> Property:
        self.properties[prop.id] = prop
        return prop

    async def get(self, tenant_id: uuid.UUID, property_id: uuid.UUID) -> Property | None:
        prop = self.properties.get(property_id)
        return prop if prop is not None and prop.tenant_id == tenant_id else None

    async def find_by_internal_code(
        self, tenant_id: uuid.UUID, internal_code: str
    ) -> Property | None:
        for prop in self.properties.values():
            if prop.tenant_id == tenant_id and prop.internal_code == internal_code.strip():
                return prop
        return None

    async def find_by_pms_external_id(
        self, tenant_id: uuid.UUID, pms_external_id: str
    ) -> Property | None:
        for prop in self.properties.values():
            if prop.tenant_id == tenant_id and prop.pms_external_id == pms_external_id.strip():
                return prop
        return None

    async def list_all(self, tenant_id: uuid.UUID) -> list[Property]:
        rows = [prop for prop in self.properties.values() if prop.tenant_id == tenant_id]
        return sorted(rows, key=lambda prop: str(prop.id))

    async def list_by_state(
        self, tenant_id: uuid.UUID, states: Collection[PropertyOperationalState]
    ) -> list[Property]:
        if not states:
            return []
        rows = [
            prop
            for prop in self.properties.values()
            if prop.tenant_id == tenant_id and prop.current_operational_state in states
        ]
        return sorted(rows, key=lambda prop: str(prop.id))

    async def save(self, tenant_id: uuid.UUID, prop: Property) -> None:
        if prop.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property",
                entity_tenant_id=prop.tenant_id,
                acting_tenant_id=tenant_id,
            )
        # Mirrors the real adapter's narrowness (`celery-jobs` design D6): only the
        # operational state is persisted, so a use case that mutated anything else on the
        # entity must not see the change survive here either.
        stored = self.properties[prop.id]
        stored.current_operational_state = prop.current_operational_state


@dataclass
class FakeGuestRepository:
    guests: dict[uuid.UUID, Guest] = field(default_factory=dict)

    def add_guest(self, guest: Guest) -> Guest:
        self.guests[guest.id] = guest
        return guest

    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> GuestSummary | None:
        guest = self.guests.get(guest_id)
        if guest is None or guest.tenant_id != tenant_id:
            return None
        return _summary(guest)

    async def find_by_email(self, tenant_id: uuid.UUID, email: str) -> GuestSummary | None:
        normalised = normalize_email(email) if email else ""
        if not normalised:
            return None
        matches = [
            guest
            for guest in self.guests.values()
            if guest.tenant_id == tenant_id
            and guest.email
            and normalize_email(guest.email) == normalised
        ]
        if not matches:
            return None
        oldest = sorted(matches, key=lambda guest: (guest.created_at, str(guest.id)))[0]
        return _summary(oldest)

    async def add(self, tenant_id: uuid.UUID, guest: Guest) -> None:
        if guest.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="guest",
                entity_tenant_id=guest.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self.guests[guest.id] = guest


@dataclass
class FakeReservationRepository:
    reservations: dict[uuid.UUID, Reservation] = field(default_factory=dict)

    async def get(self, tenant_id: uuid.UUID, reservation_id: uuid.UUID) -> Reservation | None:
        reservation = self.reservations.get(reservation_id)
        return (
            reservation
            if reservation is not None and reservation.tenant_id == tenant_id
            else None
        )

    async def find_by_external_pms_id(
        self, tenant_id: uuid.UUID, external_pms_id: str
    ) -> Reservation | None:
        for reservation in self.reservations.values():
            if (
                reservation.tenant_id == tenant_id
                and reservation.external_pms_id == external_pms_id.strip()
            ):
                return reservation
        return None

    async def list(
        self, tenant_id: uuid.UUID, filters: ReservationFilters, *, page: int, per_page: int
    ) -> Page:
        rows = [
            reservation
            for reservation in self.reservations.values()
            if reservation.tenant_id == tenant_id and _matches(reservation, filters)
        ]
        rows.sort(key=lambda reservation: (reservation.check_in_date, str(reservation.id)))
        rows.reverse()
        start = (page - 1) * per_page
        return Page(items=tuple(rows[start : start + per_page]), total=len(rows))

    async def list_for_properties(
        self,
        tenant_id: uuid.UUID,
        property_ids: Collection[uuid.UUID],
        date_from: date,
        date_to: date,
        # `Sequence`, not `list`: this class defines a method called `list`, which shadows
        # the builtin inside the class body — the same trap the real port documents.
    ) -> Sequence[Reservation]:
        if not property_ids:
            return []
        wanted = set(property_ids)
        rows = [
            reservation
            for reservation in self.reservations.values()
            if reservation.tenant_id == tenant_id
            and reservation.property_id in wanted
            # Same overlap criterion as the real adapter, inclusive on both edges.
            and reservation.check_in_date <= date_to
            and reservation.check_out_date >= date_from
        ]
        rows.sort(key=lambda reservation: (reservation.check_in_date, str(reservation.id)))
        return rows

    async def add(self, tenant_id: uuid.UUID, reservation: Reservation) -> None:
        if reservation.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="reservation",
                entity_tenant_id=reservation.tenant_id,
                acting_tenant_id=tenant_id,
            )
        if reservation.external_pms_id is not None and any(
            other.tenant_id == tenant_id
            and other.external_pms_id == reservation.external_pms_id
            for other in self.reservations.values()
        ):
            raise DuplicateExternalReservationError("Duplicate external_pms_id")
        self.reservations[reservation.id] = reservation

    async def save(self, tenant_id: uuid.UUID, reservation: Reservation) -> None:
        if reservation.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="reservation",
                entity_tenant_id=reservation.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self.reservations[reservation.id] = reservation


@dataclass
class FakeTimelineEventRepository:
    events: list[TimelineEvent] = field(default_factory=list)
    fail_with: Exception | None = None

    async def add(self, tenant_id: uuid.UUID, event: TimelineEvent) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        if event.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="timeline event",
                entity_tenant_id=event.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self.events.append(event)


@dataclass
class FakeUnitOfWork:
    commits: int = 0

    async def commit(self) -> None:
        self.commits += 1


def _summary(guest: Guest) -> GuestSummary:
    return GuestSummary(
        id=guest.id,
        full_name=guest.full_name,
        email=guest.email,
        phone=guest.phone,
        preferred_language=guest.preferred_language,
        document_status=guest.document_status,
        legal_registration_status=guest.legal_registration_status,
    )


def _matches(reservation: Reservation, filters: ReservationFilters) -> bool:
    if filters.property_id is not None and reservation.property_id != filters.property_id:
        return False
    if filters.status is not None and reservation.status is not filters.status:
        return False
    if filters.date_to is not None and reservation.check_in_date > filters.date_to:
        return False
    if filters.date_from is not None and reservation.check_out_date < filters.date_from:
        return False
    return True
