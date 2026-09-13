"""In-memory doubles of the ports the reservation use cases depend on.

`steering/backend-architecture.md` and `steering/testing.md` both ask for fakes at this
layer — not mocks of SQLAlchemy — so the use-case tests exercise real orchestration and
fail for behavioural reasons rather than because a call count changed.

Each fake enforces the same tenant scoping the real adapter does: a use case that forgot to
pass `tenant_id`, or passed the wrong one, must fail here too, otherwise these tests would
"prove" isolation that only the integration tests actually check.
"""

import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.core.encrypted_secret import EncryptedSecret
from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.entities import Guest
from app.guests.domain.value_objects import GuestSummary, normalize_email
from app.integrations.domain.enums import PMSProvider
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.exceptions import (
    DuplicateInternalCodeError,
    DuplicatePmsExternalIdError,
    PropertyValidationError,
)
from app.properties.domain.repositories import (
    PATCHABLE_PROPERTY_FIELDS,
    PropertyFilters,
)
from app.properties.domain.repositories import Page as PropertyPage
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationStatus
from app.reservations.domain.exceptions import DuplicateExternalReservationError
from app.reservations.domain.repositories import (
    RESERVATION_MATCH_GRACE_DAYS,
    Page,
    ReservationFilters,
)
from app.timeline.domain.entities import TimelineEvent


class FakeGuestEmailExclusion:
    """Explicit transaction-exclusion fake for reservation use-case tests."""

    async def acquire(self, tenant_id: uuid.UUID, normalized_email: str) -> None:
        return None


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

    async def list_for_ids(
        self, tenant_id: uuid.UUID, property_ids: Collection[uuid.UUID]
    ) -> Sequence[Property]:
        """Mirror of `SqlAlchemyPropertyRepository.list_for_ids` (`reservation-property-identity` D2).

        Same three rules the real adapter enforces: empty input returns `[]`, ids not of
        this tenant are absent rather than mapped to `None`, and `None`/duplicate ids in
        the input are filtered before the comparison. The fake keeps the same shape so a
        use-case test that exercises the listing composition cannot accidentally rely on
        a real-only behaviour.
        """
        cleaned = {property_id for property_id in property_ids if property_id is not None}
        if not cleaned:
            return []
        rows = [
            prop
            for prop in self.properties.values()
            if prop.tenant_id == tenant_id and prop.id in cleaned
        ]
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

    async def save(self, tenant_id: uuid.UUID, property: Property) -> None:
        if property.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property",
                entity_tenant_id=property.tenant_id,
                acting_tenant_id=tenant_id,
            )
        # Mirrors the real adapter's narrowness (`celery-jobs` design D6): only the
        # operational state is persisted, so a use case that mutated anything else on the
        # entity must not see the change survive here either.
        stored = self.properties[property.id]
        stored.current_operational_state = property.current_operational_state

    async def list_by_status(
        self, tenant_id: uuid.UUID, status: PropertyStatus
    ) -> list[Property]:
        rows = [
            prop
            for prop in self.properties.values()
            if prop.tenant_id == tenant_id and prop.status is status
        ]
        return sorted(rows, key=lambda prop: prop.internal_code)

    async def states_for(
        self, tenant_id: uuid.UUID, property_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, PropertyOperationalState]:
        if not property_ids:
            return {}
        wanted = set(property_ids)
        return {
            prop.id: prop.current_operational_state
            for prop in self.properties.values()
            if prop.tenant_id == tenant_id and prop.id in wanted
        }

    async def set_pms_provider(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, provider: PMSProvider | None
    ) -> None:
        prop = self.properties.get(property_id)
        if prop is None or prop.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property", entity_tenant_id="unknown", acting_tenant_id=tenant_id
            )
        prop.pms_provider = provider

    async def add(
        self,
        tenant_id: uuid.UUID,
        property: Property,
        *,
        wifi_secret: EncryptedSecret | None = None,
    ) -> None:
        if property.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property",
                entity_tenant_id=property.tenant_id,
                acting_tenant_id=tenant_id,
            )
        if property.current_operational_state is not PropertyOperationalState.VACANT_READY:
            raise PropertyValidationError(
                "A newly added property must start VACANT_READY"
            )
        if any(
            other.tenant_id == tenant_id and other.internal_code == property.internal_code
            for other in self.properties.values()
        ):
            raise DuplicateInternalCodeError()
        if property.pms_external_id is not None and any(
            other.tenant_id == tenant_id and other.pms_external_id == property.pms_external_id
            for other in self.properties.values()
        ):
            raise DuplicatePmsExternalIdError()
        self.properties[property.id] = property

    async def update_details(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, changes: Mapping[str, Any]
    ) -> bool:
        if not changes:
            raise PropertyValidationError("update_details was called with no changes")
        rejected = sorted(set(changes) - PATCHABLE_PROPERTY_FIELDS)
        if rejected:
            raise PropertyValidationError(
                f"Fields {rejected} are not patchable on a property."
            )
        prop = self.properties.get(property_id)
        if prop is None or prop.tenant_id != tenant_id:
            return False
        if "internal_code" in changes and any(
            other.id != property_id
            and other.tenant_id == tenant_id
            and other.internal_code == changes["internal_code"]
            for other in self.properties.values()
        ):
            raise DuplicateInternalCodeError()
        if (
            "pms_external_id" in changes
            and changes["pms_external_id"] is not None
            and any(
                other.id != property_id
                and other.tenant_id == tenant_id
                and other.pms_external_id == changes["pms_external_id"]
                for other in self.properties.values()
            )
        ):
            raise DuplicatePmsExternalIdError()
        for field_name, value in changes.items():
            setattr(prop, field_name, value)
        return True

    async def set_wifi_password(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, secret: EncryptedSecret | None
    ) -> bool:
        prop = self.properties.get(property_id)
        if prop is None or prop.tenant_id != tenant_id:
            return False
        prop.has_wifi_password = secret is not None
        return True

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        filters: PropertyFilters,
        page: int,
        per_page: int,
    ) -> PropertyPage:
        rows = [
            prop
            for prop in self.properties.values()
            if prop.tenant_id == tenant_id
            and (filters.status is None or prop.status is filters.status)
            and (
                filters.current_operational_state is None
                or prop.current_operational_state is filters.current_operational_state
            )
        ]
        rows.sort(key=lambda prop: (prop.name, str(prop.id)))
        start = (page - 1) * per_page
        return PropertyPage(items=tuple(rows[start : start + per_page]), total=len(rows))


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

    async def list_for_ids(
        self, tenant_id: uuid.UUID, guest_ids: Collection[uuid.UUID]
    ) -> Sequence[GuestSummary]:
        """Mirror of `SqlAlchemyGuestRepository.list_for_ids` (`dashboard-api` R1.7).

        Same three rules as the real adapter — empty input short-circuits without work,
        ids not of this tenant are absent (not `None`), and `None`/duplicate ids are
        filtered before the membership check.
        """
        cleaned = {guest_id for guest_id in guest_ids if guest_id is not None}
        if not cleaned:
            return []
        rows = [
            _summary(guest)
            for guest in self.guests.values()
            if guest.tenant_id == tenant_id and guest.id in cleaned
        ]
        return sorted(rows, key=lambda summary: str(summary.id))

    async def find_by_phone(self, tenant_id: uuid.UUID, phone: str) -> list[GuestSummary]:
        if not phone:
            return []
        return [
            _summary(guest)
            for guest in self.guests.values()
            if guest.tenant_id == tenant_id and guest.phone == phone
        ]

    async def get_full(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None:
        guest = self.guests.get(guest_id)
        return guest if guest is not None and guest.tenant_id == tenant_id else None

    async def save_document(self, tenant_id: uuid.UUID, guest: Guest) -> None:
        if guest.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="guest",
                entity_tenant_id=guest.tenant_id,
                acting_tenant_id=tenant_id,
            )
        # Mirrors the real adapter's narrowness: exactly the seven columns
        # `GuestRepository.save_document`'s docstring names, nothing else.
        stored = self.guests[guest.id]
        stored.full_name = guest.full_name
        stored.nationality = guest.nationality
        stored.date_of_birth = guest.date_of_birth
        stored.document_type = guest.document_type
        stored.document_number_encrypted = guest.document_number_encrypted
        stored.document_expiry_date = guest.document_expiry_date
        stored.document_status = guest.document_status


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

    async def find_active_for_guest(
        self, tenant_id: uuid.UUID, guest_id: uuid.UUID, *, on_date: date
    ) -> Sequence[Reservation]:
        grace = timedelta(days=RESERVATION_MATCH_GRACE_DAYS)
        rows = [
            reservation
            for reservation in self.reservations.values()
            if reservation.tenant_id == tenant_id
            and reservation.guest_id == guest_id
            and reservation.check_in_date - grace <= on_date
            and reservation.check_out_date + grace >= on_date
        ]
        rows.sort(key=lambda reservation: (reservation.check_in_date, str(reservation.id)))
        return rows

    async def count_check_ins_in_range(
        self, tenant_id: uuid.UUID, date_from: date, date_to: date
    ) -> int:
        excluded = (ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW)
        return sum(
            1
            for reservation in self.reservations.values()
            if reservation.tenant_id == tenant_id
            and date_from <= reservation.check_in_date <= date_to
            and reservation.status not in excluded
        )


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
    rollbacks: int = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


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
