"""In-memory fakes of the seven ports the dashboard composes (`dashboard-api` tasks 6.1-6.2).

`steering/testing.md`: "`application/`: unit tests con **fakes** en memoria de los puertos
(no la DB real, no mocks de SQLAlchemy)". Fakes and not mocks on purpose — a mock asserts
that a call was made, and what these tests need to know is what the use case *composes*,
which only a real return value can show.

Each fake implements exactly the methods its port declares and holds its rows in a dict
keyed by tenant, so passing another tenant's id returns nothing without any special-casing
— the same property the adapters get from `WHERE tenant_id`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.value_objects import CleaningTaskSummary
from app.guests.domain.value_objects import GuestSummary
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.maintenance.domain.enums import IncidentCategory, IncidentSeverity, OwnerApprovalRelatedType
from app.maintenance.domain.value_objects import (
    IncidentSummary,
    OpenIncidentCounts,
    OwnerApprovalSummary,
)
from app.properties.domain.entities import Property, PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.repositories import Page as PropertyPage
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import (
    ReservationAccessStatus,
    ReservationChannel,
    ReservationStatus,
)
from app.statements.domain.repositories import PropertyFinancialSummary
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity

NOW = datetime(2026, 8, 9, 12, 0)
TODAY = date(2026, 8, 9)


def make_property(
    tenant_id: uuid.UUID,
    *,
    code: str = "REDES11",
    state: PropertyOperationalState = PropertyOperationalState.VACANT_READY,
    property_id: uuid.UUID | None = None,
) -> Property:
    return Property(
        id=property_id or uuid.uuid4(),
        tenant_id=tenant_id,
        name=code,
        internal_code=code,
        created_at=NOW,
        updated_at=NOW,
        current_operational_state=state,
        status=PropertyStatus.ACTIVE,
    )


def make_reservation(
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    *,
    guest_id: uuid.UUID | None = None,
    check_in: date = TODAY,
    check_out: date = date(2026, 8, 12),
    external_pms_id: str | None = "BK-1",
    channel: ReservationChannel = ReservationChannel.BOOKING,
    access_status: ReservationAccessStatus = ReservationAccessStatus.DELIVERED,
    gross_amount: Decimal | None = Decimal("450.00"),
    currency: str = "EUR",
) -> Reservation:
    return Reservation(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        channel=channel,
        check_in_date=check_in,
        check_out_date=check_out,
        nights=(check_out - check_in).days,
        created_at=NOW,
        updated_at=NOW,
        guest_id=guest_id,
        external_pms_id=external_pms_id,
        status=ReservationStatus.CONFIRMED,
        gross_amount=gross_amount,
        currency=currency,
        access_status=access_status,
    )


def make_guest(guest_id: uuid.UUID, *, name: str = "Marta García") -> GuestSummary:
    return GuestSummary(
        id=guest_id,
        full_name=name,
        email=None,
        phone=None,
        preferred_language="es",
        document_status=GuestDocumentStatus.PENDING,
        legal_registration_status=LegalRegistrationStatus.PENDING_GUEST_DATA,
    )


@dataclass
class FakePropertyRepository:
    by_tenant: dict[uuid.UUID, list[Property]] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    async def list_by_status(self, tenant_id, status: PropertyStatus) -> list[Property]:
        """`dashboard-occupancy-series` R4.1's active-portfolio read.

        Filters in memory by `status`, same as every other fake here — the real adapter's
        `internal_code` ordering is not asserted by anything section 3 tests.

        Defined **before** `list` below: this class defines a method named `list`, which
        would shadow the builtin inside the class body and make a later `list[Property]`
        annotation a `TypeError` at import time (same reason the real `PropertyRepository`
        Protocol orders `list_by_status` ahead of `list`).
        """
        self.calls.append(("list_by_status", tenant_id, status))
        return [item for item in self.by_tenant.get(tenant_id, []) if item.status == status]

    async def list(self, tenant_id, *, filters, page, per_page) -> PropertyPage:
        items = self.by_tenant.get(tenant_id, [])
        start = (page - 1) * per_page
        return PropertyPage(items=tuple(items[start : start + per_page]), total=len(items))

    async def get(self, tenant_id, property_id) -> Property | None:
        for item in self.by_tenant.get(tenant_id, []):
            if item.id == property_id:
                return item
        return None


@dataclass
class FakeReservationRepository:
    by_tenant: dict[uuid.UUID, list[Reservation]] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    async def list_for_properties(
        self, tenant_id, property_ids, date_from, date_to
    ) -> Sequence[Reservation]:
        self.calls.append((tenant_id, tuple(property_ids), date_from, date_to))
        wanted = set(property_ids)
        return [
            item
            for item in self.by_tenant.get(tenant_id, [])
            if item.property_id in wanted
            and item.check_in_date <= date_to
            and item.check_out_date >= date_from
        ]

    async def count_check_ins_in_range(self, tenant_id, date_from, date_to) -> int:
        self.calls.append(("count_check_ins_in_range", tenant_id, date_from, date_to))
        return sum(
            1
            for item in self.by_tenant.get(tenant_id, [])
            if date_from <= item.check_in_date <= date_to
            and item.status not in (ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW)
        )


@dataclass
class FakePropertyStateTransitionRepository:
    """Only `history_for_properties` — the one method `GetOccupancySeriesUseCase` calls.

    Same precedent as `tests/properties/doubles.py`'s sibling fake, which omits
    `last_for_property` for the same reason: a fake covers what its use case needs, not
    the whole port.

    Mirrors the adapter's contract (`app/properties/domain/repositories.py:458`) rather than
    reading it verbatim: sparse result, and each present sequence holds the one transition
    immediately before `start` (if any) followed by every transition inside
    `[start, end]` — both resolved against the UTC calendar day, `end` inclusive.
    """

    by_tenant: dict[uuid.UUID, list[PropertyStateTransition]] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    async def history_for_properties(
        self, tenant_id, property_ids, start: date, end: date
    ) -> dict[uuid.UUID, list[PropertyStateTransition]]:
        self.calls.append(("history_for_properties", tenant_id, tuple(property_ids), start, end))
        wanted = set(property_ids)
        if not wanted:
            return {}
        start_boundary = datetime.combine(start, time.min, tzinfo=UTC)
        end_boundary = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)

        by_property: dict[uuid.UUID, list[PropertyStateTransition]] = {}
        for transition in self.by_tenant.get(tenant_id, []):
            if transition.property_id in wanted:
                by_property.setdefault(transition.property_id, []).append(transition)

        result: dict[uuid.UUID, list[PropertyStateTransition]] = {}
        for property_id, transitions in by_property.items():
            ordered = sorted(transitions, key=lambda t: (t.created_at, t.id))
            entering = [t for t in ordered if t.created_at < start_boundary]
            within = [t for t in ordered if start_boundary <= t.created_at < end_boundary]
            sequence = ([entering[-1]] if entering else []) + within
            if sequence:
                result[property_id] = sequence
        return result


@dataclass
class FakeGuestRepository:
    guests: dict[uuid.UUID, GuestSummary] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    async def list_for_ids(self, tenant_id, guest_ids) -> Sequence[GuestSummary]:
        self.calls.append((tenant_id, tuple(guest_ids)))
        return [self.guests[gid] for gid in guest_ids if gid in self.guests]


@dataclass
class FakeCleaningRepository:
    by_tenant: dict[uuid.UUID, list[CleaningTaskSummary]] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    async def list_live_for_properties(
        self, tenant_id, property_ids
    ) -> Sequence[CleaningTaskSummary]:
        self.calls.append((tenant_id, tuple(property_ids)))
        wanted = set(property_ids)
        return [
            item for item in self.by_tenant.get(tenant_id, []) if item.property_id in wanted
        ]

    async def count_live_for_day(self, tenant_id, day: date) -> int:
        self.calls.append(("count_live_for_day", tenant_id, day))
        return len(self.by_tenant.get(tenant_id, []))


@dataclass
class FakeIncidentReader:
    counts: dict[uuid.UUID, dict[uuid.UUID, int]] = field(default_factory=dict)
    open_by_property: dict[uuid.UUID, list[IncidentSummary]] = field(default_factory=dict)
    open_for_tenant: dict[uuid.UUID, OpenIncidentCounts] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)

    async def count_open_for_tenant(self, tenant_id) -> OpenIncidentCounts:
        self.calls.append(("count_open_for_tenant", tenant_id))
        return self.open_for_tenant.get(tenant_id, OpenIncidentCounts(total=0, urgent=0))

    async def count_open_for_properties(self, tenant_id, property_ids) -> dict[uuid.UUID, int]:
        wanted = set(property_ids)
        return {
            pid: count
            for pid, count in self.counts.get(tenant_id, {}).items()
            if pid in wanted
        }

    async def list_open_for_property(self, tenant_id, property_id) -> Sequence[IncidentSummary]:
        return list(self.open_by_property.get(property_id, []))

    async def list_open_for_properties(
        self, tenant_id, property_ids
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Test double for the batch sibling added by `blocked-transition-response-ids` (R3.4).

        Mirrors the production contract: returns `dict[property_id, incident_id]` (NOT a
        summary — the port is narrow per `steering/backend-architecture.md`'s "puertos
        pequeños y por rol" rule). Sparse mapping (a property with no open incident is
        absent), first occurrence per property wins. Existing tests keep
        `open_by_property[pid][0]` as the newest by convention; we project to its id.
        """
        wanted = set(property_ids)
        by_property: dict[uuid.UUID, uuid.UUID] = {}
        for pid, summaries in self.open_by_property.items():
            if pid in wanted and summaries and pid not in by_property:
                by_property[pid] = summaries[0].id
        return by_property


@dataclass
class FakeOwnerApprovalReader:
    pending_by_property: dict[uuid.UUID, list[OwnerApprovalSummary]] = field(
        default_factory=dict
    )

    async def list_pending_for_property(
        self, tenant_id, property_id
    ) -> Sequence[OwnerApprovalSummary]:
        return list(self.pending_by_property.get(property_id, []))


@dataclass
class FakeExpenseReader:
    pending_by_property: dict[uuid.UUID, dict[str, Decimal]] = field(default_factory=dict)

    async def summary_for_property(self, tenant_id, property_id) -> PropertyFinancialSummary:
        return PropertyFinancialSummary(
            pending_expenses=dict(self.pending_by_property.get(property_id, {}))
        )


@dataclass
class FakeTimelineReader:
    last_by_property: dict[uuid.UUID, TimelineEvent] = field(default_factory=dict)

    async def last_for_properties(self, tenant_id, property_ids) -> dict[uuid.UUID, TimelineEvent]:
        wanted = set(property_ids)
        return {
            pid: event for pid, event in self.last_by_property.items() if pid in wanted
        }


def make_event(
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    *,
    event_type: TimelineEventType = TimelineEventType.CLEANING_COMPLETED,
    created_at: datetime = NOW,
) -> TimelineEvent:
    return TimelineEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        actor_type=TimelineActorType.SYSTEM,
        event_type=event_type,
        title="Stored English title",
        created_at=created_at,
        severity=TimelineSeverity.INFO,
    )


def make_cleaning(property_id: uuid.UUID, status: CleaningTaskStatus) -> CleaningTaskSummary:
    return CleaningTaskSummary(id=uuid.uuid4(), property_id=property_id, status=status)


def make_incident(
    *,
    category: IncidentCategory = IncidentCategory.APPLIANCE,
    severity: IncidentSeverity = IncidentSeverity.HIGH,
) -> IncidentSummary:
    return IncidentSummary(
        id=uuid.uuid4(), category=category, severity=severity, opened_at=NOW
    )


def make_approval(*, amount: Decimal = Decimal("180.00")) -> OwnerApprovalSummary:
    return OwnerApprovalSummary(
        id=uuid.uuid4(),
        related_type=OwnerApprovalRelatedType.INCIDENT,
        amount=amount,
        requested_at=NOW,
    )


__all__ = [
    "NOW",
    "TODAY",
    "FakeCleaningRepository",
    "FakeExpenseReader",
    "FakeGuestRepository",
    "FakeIncidentReader",
    "FakeOwnerApprovalReader",
    "FakePropertyRepository",
    "FakePropertyStateTransitionRepository",
    "FakeReservationRepository",
    "FakeTimelineReader",
    "make_approval",
    "make_cleaning",
    "make_event",
    "make_guest",
    "make_incident",
    "make_property",
    "make_reservation",
    "replace",
]
