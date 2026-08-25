"""Reservation use cases with in-memory ports (R1, R2, R5).

What these cover that the repository tests cannot: that the orchestration writes the
reservation AND its timeline event, that it commits exactly once, that it refuses to touch
another tenant's property, guest or reservation, and that an operation which changes
nothing records nothing.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.guests.domain.entities import Guest
from app.properties.domain.entities import Property
from app.reservations.application.use_cases import (
    CancelReservationUseCase,
    CreateReservationCommand,
    CreateReservationUseCase,
    GetReservationUseCase,
    ListReservationsUseCase,
    UpdateReservationUseCase,
)
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.domain.exceptions import (
    GuestNotFoundError,
    PropertyNotFoundError,
    ReservationNotFoundError,
)
from app.reservations.domain.repositories import ReservationFilters
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from tests.reservations.doubles import (
    FakeGuestRepository,
    FakePropertyRepository,
    FakeReservationRepository,
    FakeTimelineEventRepository,
    FakeUnitOfWork,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
CHECK_IN = date(2026, 8, 1)
CHECK_OUT = CHECK_IN + timedelta(days=3)


@pytest.fixture
def world():
    """Two tenants, one property and one guest each — the neighbour is always present."""

    class World:
        def __init__(self) -> None:
            self.tenant_a = uuid.uuid4()
            self.tenant_b = uuid.uuid4()
            self.user_a = uuid.uuid4()
            self.reservations = FakeReservationRepository()
            self.properties = FakePropertyRepository()
            self.guests = FakeGuestRepository()
            self.timeline = FakeTimelineEventRepository()
            self.uow = FakeUnitOfWork()
            self.property_a = self.properties.add_property(_property(self.tenant_a, "REDES11"))
            self.property_b = self.properties.add_property(_property(self.tenant_b, "THEIRS"))
            self.guest_a = self.guests.add_guest(_guest(self.tenant_a, "john@example.com"))
            self.guest_b = self.guests.add_guest(_guest(self.tenant_b, "their@example.com"))

        def create_use_case(self) -> CreateReservationUseCase:
            return CreateReservationUseCase(
                reservations=self.reservations,
                properties=self.properties,
                guests=self.guests,
                timeline=self.timeline,
                uow=self.uow,
            )

        def update_use_case(self) -> UpdateReservationUseCase:
            return UpdateReservationUseCase(
                reservations=self.reservations,
                guests=self.guests,
                timeline=self.timeline,
                uow=self.uow,
            )

        def cancel_use_case(self) -> CancelReservationUseCase:
            return CancelReservationUseCase(
                reservations=self.reservations, timeline=self.timeline, uow=self.uow
            )

        def get_use_case(self) -> GetReservationUseCase:
            return GetReservationUseCase(
                reservations=self.reservations,
                guests=self.guests,
                properties=self.properties,
            )

        def list_use_case(self) -> ListReservationsUseCase:
            return ListReservationsUseCase(
                reservations=self.reservations,
                properties=self.properties,
                guests=self.guests,
            )

        async def create(self, **overrides):
            command = CreateReservationCommand(
                property_id=overrides.pop("property_id", self.property_a.id),
                channel=ReservationChannel.DIRECT,
                check_in_date=CHECK_IN,
                check_out_date=CHECK_OUT,
                adults=2,
                **overrides,
            )
            return await self.create_use_case().execute(
                tenant_id=self.tenant_a,
                actor_user_id=self.user_a,
                command=command,
                now=NOW,
            )

    return World()


def _property(tenant_id: uuid.UUID, code: str) -> Property:
    return Property(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=code,
        internal_code=code,
        created_at=NOW,
        updated_at=NOW,
        pms_external_id=f"PMS-{code}",
    )


def _guest(tenant_id: uuid.UUID, email: str) -> Guest:
    return Guest(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        full_name="Somebody",
        created_at=NOW,
        updated_at=NOW,
        email=email,
    )


class TestCreate:
    @pytest.mark.asyncio
    async def test_it_stores_the_reservation_and_one_timeline_event(self, world) -> None:
        reservation = await world.create()

        assert world.reservations.reservations[reservation.id] is reservation
        assert len(world.timeline.events) == 1
        event = world.timeline.events[0]
        assert event.event_type is TimelineEventType.RESERVATION_CREATED_MANUAL
        assert event.actor_type is TimelineActorType.USER
        assert event.actor_user_id == world.user_a
        assert event.reservation_id == reservation.id
        assert event.property_id == world.property_a.id
        assert event.created_at == NOW
        assert world.uow.commits == 1

    @pytest.mark.asyncio
    async def test_a_property_of_another_tenant_is_not_found(self, world) -> None:
        """R1.4 + R5.1: indistinguishable from a property that does not exist."""
        with pytest.raises(PropertyNotFoundError):
            await world.create(property_id=world.property_b.id)

        assert world.reservations.reservations == {}
        assert world.timeline.events == []
        assert world.uow.commits == 0

    @pytest.mark.asyncio
    async def test_an_unknown_property_is_not_found(self, world) -> None:
        with pytest.raises(PropertyNotFoundError):
            await world.create(property_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_a_guest_of_another_tenant_is_not_found(self, world) -> None:
        """`guest_id` arrives as a raw UUID from the client and the FK is global, so this
        check is what keeps a booking from pointing at the neighbour's guest (design D18)."""
        with pytest.raises(GuestNotFoundError):
            await world.create(guest_id=world.guest_b.id)

        assert world.reservations.reservations == {}
        assert world.uow.commits == 0

    @pytest.mark.asyncio
    async def test_a_guest_of_the_same_tenant_is_linked(self, world) -> None:
        reservation = await world.create(guest_id=world.guest_a.id)

        assert reservation.guest_id == world.guest_a.id

    @pytest.mark.asyncio
    async def test_nothing_is_committed_when_the_timeline_write_fails(self, world) -> None:
        """R2.6 at the orchestration level: no commit, so the transaction rolls back."""
        world.timeline.fail_with = RuntimeError("timeline is down")

        with pytest.raises(RuntimeError):
            await world.create()

        assert world.uow.commits == 0


class TestUpdate:
    @pytest.mark.asyncio
    async def test_it_records_only_the_fields_that_changed(self, world) -> None:
        reservation = await world.create()
        world.timeline.events.clear()

        updated = await world.update_use_case().execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            changes={"adults": 4},
            now=NOW + timedelta(hours=1),
        )

        assert updated.adults == 4
        assert updated.total_guests == 4
        assert len(world.timeline.events) == 1
        event = world.timeline.events[0]
        assert event.event_type is TimelineEventType.RESERVATION_UPDATED
        assert event.metadata == {"changed": {"adults": {"from": 2, "to": 4}}}

    @pytest.mark.asyncio
    async def test_a_patch_that_changes_nothing_records_nothing(self, world) -> None:
        reservation = await world.create()
        world.timeline.events.clear()
        commits_before = world.uow.commits

        await world.update_use_case().execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            changes={"adults": 2},
            now=NOW + timedelta(hours=1),
        )

        assert world.timeline.events == []
        assert world.uow.commits == commits_before

    @pytest.mark.asyncio
    async def test_an_empty_patch_records_nothing(self, world) -> None:
        reservation = await world.create()
        world.timeline.events.clear()

        await world.update_use_case().execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            changes={},
            now=NOW + timedelta(hours=1),
        )

        assert world.timeline.events == []

    @pytest.mark.asyncio
    async def test_a_patch_that_cancels_records_a_cancellation_not_an_update(
        self, world
    ) -> None:
        """R2.3: a PATCH to `CANCELLED` cancels as surely as a DELETE, so it must leave the
        same evidence. Without this, `cancel()` being idempotent means a later DELETE adds
        nothing either and `RESERVATION_CANCELLED` never exists for that reservation."""
        reservation = await world.create()
        world.timeline.events.clear()

        await world.update_use_case().execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            changes={"status": ReservationStatus.CANCELLED},
            now=NOW + timedelta(hours=1),
        )

        assert reservation.status is ReservationStatus.CANCELLED
        assert [event.event_type for event in world.timeline.events] == [
            TimelineEventType.RESERVATION_CANCELLED
        ]

    @pytest.mark.asyncio
    async def test_a_patch_that_changes_status_to_something_else_is_still_an_update(
        self, world
    ) -> None:
        reservation = await world.create()
        world.timeline.events.clear()

        await world.update_use_case().execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            changes={"status": ReservationStatus.CONFIRMED},
            now=NOW + timedelta(hours=1),
        )

        assert [event.event_type for event in world.timeline.events] == [
            TimelineEventType.RESERVATION_UPDATED
        ]

    @pytest.mark.asyncio
    async def test_a_cancelled_reservation_can_still_be_corrected(self, world) -> None:
        """Pinning behaviour the requirements do not forbid, so nobody has to re-derive it.

        A cancelled booking keeps accepting edits (a manager fixing the party size on a
        cancelled stay for the record), and the event is an ordinary `RESERVATION_UPDATED` —
        cancelling twice is what is idempotent, not the row itself.
        """
        reservation = await world.create()
        await world.cancel_use_case().execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            now=NOW + timedelta(days=1),
        )
        world.timeline.events.clear()

        await world.update_use_case().execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            changes={"adults": 5},
            now=NOW + timedelta(days=2),
        )

        assert reservation.adults == 5
        assert reservation.status is ReservationStatus.CANCELLED
        assert [event.event_type for event in world.timeline.events] == [
            TimelineEventType.RESERVATION_UPDATED
        ]

    @pytest.mark.asyncio
    async def test_another_tenants_reservation_is_not_found(self, world) -> None:
        reservation = await world.create()

        with pytest.raises(ReservationNotFoundError):
            await world.update_use_case().execute(
                tenant_id=world.tenant_b,
                actor_user_id=uuid.uuid4(),
                reservation_id=reservation.id,
                changes={"adults": 9},
                now=NOW,
            )

    @pytest.mark.asyncio
    async def test_relinking_to_another_tenants_guest_is_refused(self, world) -> None:
        reservation = await world.create()

        with pytest.raises(GuestNotFoundError):
            await world.update_use_case().execute(
                tenant_id=world.tenant_a,
                actor_user_id=world.user_a,
                reservation_id=reservation.id,
                changes={"guest_id": world.guest_b.id},
                now=NOW,
            )


class TestCancel:
    @pytest.mark.asyncio
    async def test_it_cancels_and_records_the_previous_status(self, world) -> None:
        reservation = await world.create()
        world.timeline.events.clear()

        await world.cancel_use_case().execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            now=NOW + timedelta(days=1),
        )

        assert reservation.status is ReservationStatus.CANCELLED
        assert len(world.timeline.events) == 1
        event = world.timeline.events[0]
        assert event.event_type is TimelineEventType.RESERVATION_CANCELLED
        assert event.metadata == {"previous_status": "PENDING"}

    @pytest.mark.asyncio
    async def test_a_second_cancellation_adds_no_second_event(self, world) -> None:
        """R1.7: `DELETE` is idempotent, and the timeline must not repeat itself."""
        reservation = await world.create()
        use_case = world.cancel_use_case()
        await use_case.execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            now=NOW + timedelta(days=1),
        )
        world.timeline.events.clear()
        commits_before = world.uow.commits

        await use_case.execute(
            tenant_id=world.tenant_a,
            actor_user_id=world.user_a,
            reservation_id=reservation.id,
            now=NOW + timedelta(days=2),
        )

        assert world.timeline.events == []
        assert world.uow.commits == commits_before

    @pytest.mark.asyncio
    async def test_another_tenants_reservation_is_not_found(self, world) -> None:
        reservation = await world.create()

        with pytest.raises(ReservationNotFoundError):
            await world.cancel_use_case().execute(
                tenant_id=world.tenant_b,
                actor_user_id=uuid.uuid4(),
                reservation_id=reservation.id,
                now=NOW,
            )


class TestReads:
    @pytest.mark.asyncio
    async def test_the_detail_carries_the_guest_without_document_data(self, world) -> None:
        reservation = await world.create(guest_id=world.guest_a.id)

        detail = await world.get_use_case().execute(
            tenant_id=world.tenant_a, reservation_id=reservation.id
        )

        assert detail.reservation.id == reservation.id
        assert detail.guest is not None
        assert detail.guest.full_name == "Somebody"
        assert not set(vars(detail.guest)) & {"document_number_encrypted", "date_of_birth"}

    @pytest.mark.asyncio
    async def test_the_detail_of_a_reservation_without_guest_has_none(self, world) -> None:
        reservation = await world.create()

        detail = await world.get_use_case().execute(
            tenant_id=world.tenant_a, reservation_id=reservation.id
        )

        assert detail.guest is None

    @pytest.mark.asyncio
    async def test_the_detail_of_another_tenant_is_not_found(self, world) -> None:
        reservation = await world.create()

        with pytest.raises(ReservationNotFoundError):
            await world.get_use_case().execute(
                tenant_id=world.tenant_b, reservation_id=reservation.id
            )

    @pytest.mark.asyncio
    async def test_the_detail_carries_the_property_identity_when_it_resolves(
        self, world
    ) -> None:
        """R2.1: the detail populates `property_name`/`property_internal_code` from the
        resolved Property in the SAME request, not from a second client call.
        """
        reservation = await world.create()

        detail = await world.get_use_case().execute(
            tenant_id=world.tenant_a, reservation_id=reservation.id
        )

        assert detail.property_name == world.property_a.name
        assert detail.property_internal_code == world.property_a.internal_code

    @pytest.mark.asyncio
    async def test_the_detail_degrades_to_none_when_property_is_of_another_tenant(
        self, world
    ) -> None:
        """R2.2 + D5: a `property_id` pointing at another tenant's row does NOT 404 the
        reservation; the reservation resolves, the property-derived fields are None with
        their key, and the rest of the response is intact.

        Constructed by replacing the reservation's `property_id` with the neighbour's
        AFTER creation; the aggregate has no "create cross-tenant" path by design.
        """
        reservation = await world.create()
        reservation.property_id = world.property_b.id

        detail = await world.get_use_case().execute(
            tenant_id=world.tenant_a, reservation_id=reservation.id
        )

        assert detail.property_name is None
        assert detail.property_internal_code is None
        # `property_id` itself is preserved — the FK is the truth, the derived labels
        # are the projection (R1.3 / R3.1 analogue for the detail, and D5).
        assert detail.reservation.property_id == world.property_b.id
        assert detail.guest is None  # the reservation was created without a guest

    @pytest.mark.asyncio
    async def test_the_detail_carries_the_guest_full_name_when_it_resolves(
        self, world
    ) -> None:
        """R4.1: detail exposes `guest_full_name` (in the response DTO) — the model
        carries it via `Reservation.guest_full_name`. The source is `GuestSummary`,
        not the entity (D4)."""
        reservation = await world.create(guest_id=world.guest_a.id)

        detail = await world.get_use_case().execute(
            tenant_id=world.tenant_a, reservation_id=reservation.id
        )

        assert detail.reservation.guest_full_name == world.guest_a.full_name

    @pytest.mark.asyncio
    async def test_the_detail_carries_none_guest_full_name_when_no_guest(
        self, world
    ) -> None:
        """R3.2 / R4.2: a reservation without a guest has `guest_full_name` None."""
        reservation = await world.create()

        detail = await world.get_use_case().execute(
            tenant_id=world.tenant_a, reservation_id=reservation.id
        )

        assert detail.reservation.guest_full_name is None

    @pytest.mark.asyncio
    async def test_the_listing_never_includes_another_tenants_rows(self, world) -> None:
        mine = await world.create()
        theirs = await world.create_use_case().execute(
            tenant_id=world.tenant_b,
            actor_user_id=uuid.uuid4(),
            command=CreateReservationCommand(
                property_id=world.property_b.id,
                channel=ReservationChannel.DIRECT,
                check_in_date=CHECK_IN,
                check_out_date=CHECK_OUT,
            ),
            now=NOW,
        )

        page = await world.list_use_case().execute(
            tenant_id=world.tenant_a, filters=ReservationFilters(), page=1, per_page=20
        )

        assert [item.id for item in page.items] == [mine.id]
        assert page.total == 1
        assert theirs.id not in {item.id for item in page.items}

    @pytest.mark.asyncio
    async def test_the_listing_enriches_every_item_with_property_and_guest_identity(
        self, world
    ) -> None:
        """R1.1+R3.1: the list resolves the property and the guest of every row in the
        page via batch reads, then attaches their identity fields. Two reservations with
        distinct properties and a guest each exercise both readers.
        """
        other_property = world.properties.add_property(
            _property(world.tenant_a, "PAJARITOS8")
        )
        first = await world.create()
        second = await world.create(
            property_id=other_property.id, guest_id=world.guest_a.id
        )

        page = await world.list_use_case().execute(
            tenant_id=world.tenant_a, filters=ReservationFilters(), page=1, per_page=20
        )

        ordered = sorted(page.items, key=lambda item: str(item.id))
        assert len(ordered) == 2
        by_id = {item.id: item for item in ordered}

        assert by_id[first.id].property_name == world.property_a.name
        assert by_id[first.id].property_internal_code == world.property_a.internal_code
        # First was created without a guest.
        assert by_id[first.id].guest_full_name is None

        assert by_id[second.id].property_name == other_property.name
        assert by_id[second.id].property_internal_code == other_property.internal_code
        assert by_id[second.id].guest_full_name == world.guest_a.full_name

    @pytest.mark.asyncio
    async def test_the_listing_degrades_to_none_when_property_is_of_another_tenant(
        self, world
    ) -> None:
        """R1.2 / R3.3 + D5: a reservation whose `property_id` points at the neighbour's
        property still appears in the listing with `property_name` and
        `property_internal_code` as None (with their key), the same shape the detail
        gives. Id and `gross_amount` etc. are still set.
        """
        reservation = await world.create()
        reservation.property_id = world.property_b.id

        page = await world.list_use_case().execute(
            tenant_id=world.tenant_a, filters=ReservationFilters(), page=1, per_page=20
        )

        assert len(page.items) == 1
        item = page.items[0]
        assert item.id == reservation.id
        assert item.property_name is None
        assert item.property_internal_code is None
        assert item.guest_full_name is None
        # `property_id` is the FK truth and stays — R1.3.
        assert item.property_id == world.property_b.id
