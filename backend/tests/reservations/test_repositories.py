"""`SqlAlchemyReservationRepository` — scoping, idempotency, filters and paging.

Covers R1.1 (filters and pagination), R1.5 (save writes back), R3.2 (idempotency key),
R5.1 (a tenant never reaches the neighbour's bookings) and design D9/D12.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.enums import LegalRegistrationStatus
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import (
    ReservationAccessStatus,
    ReservationChannel,
    ReservationStatus,
)
from app.reservations.domain.exceptions import DuplicateExternalReservationError
from app.reservations.domain.repositories import ReservationFilters
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.models import TenantModel

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
NO_FILTERS = ReservationFilters()


async def _tenant_with_property(db_session, name: str) -> tuple[TenantModel, PropertyModel]:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(tenant_id=tenant.id, name=f"{name} flat", internal_code=f"{name}-1")
    db_session.add(prop)
    await db_session.flush()
    return tenant, prop


def _reservation(
    tenant: TenantModel,
    prop: PropertyModel,
    *,
    check_in: date = date(2026, 8, 1),
    nights: int = 3,
    external_pms_id: str | None = None,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
) -> Reservation:
    return Reservation.create(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=nights),
        now=NOW,
        adults=2,
        external_pms_id=external_pms_id,
        status=status,
    )


class TestGetAndScoping:
    @pytest.mark.asyncio
    async def test_it_returns_the_reservation_of_its_tenant(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        reservation = _reservation(tenant, prop)
        await repository.add(tenant.id, reservation)

        found = await repository.get(tenant.id, reservation.id)

        assert found is not None
        assert found.id == reservation.id
        assert found.nights == 3
        assert found.total_guests == 2

    @pytest.mark.asyncio
    async def test_it_does_not_reach_another_tenants_reservation(self, db_session) -> None:
        """R5.1: the answer must be indistinguishable from "does not exist"."""
        tenant_a, _ = await _tenant_with_property(db_session, "TenantA")
        tenant_b, prop_b = await _tenant_with_property(db_session, "TenantB")
        repository = SqlAlchemyReservationRepository(db_session)
        theirs = _reservation(tenant_b, prop_b)
        await repository.add(tenant_b.id, theirs)

        assert await repository.get(tenant_a.id, theirs.id) is None

    @pytest.mark.asyncio
    async def test_add_refuses_a_reservation_of_another_tenant(self, db_session) -> None:
        tenant_a, _ = await _tenant_with_property(db_session, "TenantA")
        tenant_b, prop_b = await _tenant_with_property(db_session, "TenantB")

        with pytest.raises(CrossTenantWriteError):
            await SqlAlchemyReservationRepository(db_session).add(
                tenant_a.id, _reservation(tenant_b, prop_b)
            )

    @pytest.mark.asyncio
    async def test_save_refuses_a_reservation_of_another_tenant(self, db_session) -> None:
        tenant_a, _ = await _tenant_with_property(db_session, "TenantA")
        tenant_b, prop_b = await _tenant_with_property(db_session, "TenantB")
        repository = SqlAlchemyReservationRepository(db_session)
        theirs = _reservation(tenant_b, prop_b)
        await repository.add(tenant_b.id, theirs)

        with pytest.raises(CrossTenantWriteError):
            await repository.save(tenant_a.id, theirs)


class TestIdempotencyKey:
    @pytest.mark.asyncio
    async def test_it_finds_a_reservation_by_external_pms_id(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        reservation = _reservation(tenant, prop, external_pms_id="PMS-1")
        await repository.add(tenant.id, reservation)

        found = await repository.find_by_external_pms_id(tenant.id, "PMS-1")

        assert found is not None
        assert found.id == reservation.id

    @pytest.mark.asyncio
    async def test_the_lookup_is_scoped_to_the_tenant(self, db_session) -> None:
        tenant_a, _ = await _tenant_with_property(db_session, "TenantA")
        tenant_b, prop_b = await _tenant_with_property(db_session, "TenantB")
        repository = SqlAlchemyReservationRepository(db_session)
        await repository.add(tenant_b.id, _reservation(tenant_b, prop_b, external_pms_id="PMS-1"))

        assert await repository.find_by_external_pms_id(tenant_a.id, "PMS-1") is None

    @pytest.mark.asyncio
    async def test_a_duplicate_external_id_raises_a_domain_error(self, db_session) -> None:
        """The constraint decides, not a prior read (design D9) — and what escapes is a
        domain error, not `IntegrityError`, so `application/` never catches SQLAlchemy."""
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        await repository.add(tenant.id, _reservation(tenant, prop, external_pms_id="PMS-1"))

        with pytest.raises(DuplicateExternalReservationError):
            await repository.add(
                tenant.id, _reservation(tenant, prop, external_pms_id="PMS-1")
            )

    @pytest.mark.asyncio
    async def test_two_reservations_without_external_id_coexist(self, db_session) -> None:
        """The unique constraint is on a nullable column: manual bookings must not collide."""
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)

        await repository.add(tenant.id, _reservation(tenant, prop))
        await repository.add(tenant.id, _reservation(tenant, prop))

        page = await repository.list(tenant.id, NO_FILTERS, page=1, per_page=20)
        assert page.total == 2


class TestSave:
    @pytest.mark.asyncio
    async def test_it_writes_the_mutable_fields_back(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        reservation = _reservation(tenant, prop)
        await repository.add(tenant.id, reservation)

        reservation.update_details(
            {"adults": 4, "gross_amount": Decimal("350.00")}, now=NOW + timedelta(hours=1)
        )
        await repository.save(tenant.id, reservation)

        reloaded = await repository.get(tenant.id, reservation.id)
        assert reloaded is not None
        assert reloaded.adults == 4
        assert reloaded.total_guests == 4
        assert reloaded.gross_amount == Decimal("350.00")

    @pytest.mark.asyncio
    async def test_a_cancellation_survives_the_round_trip(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        reservation = _reservation(tenant, prop)
        await repository.add(tenant.id, reservation)

        reservation.cancel(now=NOW + timedelta(days=1))
        await repository.save(tenant.id, reservation)

        reloaded = await repository.get(tenant.id, reservation.id)
        assert reloaded is not None
        assert reloaded.status is ReservationStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_it_cannot_write_fields_owned_by_another_module(self, db_session) -> None:
        """`access_status` and `legal_registration_status` are out of this change's scope.

        The columns `save` writes are derived from the domain allow-list, so the ingest
        path of R3 — which builds an entity from an external PMS payload — cannot
        overwrite the SES.Hospedajes registration state through the back door.
        """
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        reservation = _reservation(tenant, prop)
        await repository.add(tenant.id, reservation)

        reservation.legal_registration_status = LegalRegistrationStatus.SUBMITTED
        reservation.access_status = ReservationAccessStatus.DELIVERED
        await repository.save(tenant.id, reservation)

        reloaded = await repository.get(tenant.id, reservation.id)
        assert reloaded is not None
        assert reloaded.legal_registration_status is LegalRegistrationStatus.NOT_REQUIRED
        assert reloaded.access_status is ReservationAccessStatus.PENDING

    @pytest.mark.asyncio
    async def test_it_cannot_move_a_reservation_to_another_property(self, db_session) -> None:
        """`property_id` is identity, excluded from the columns `save` writes."""
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        other = PropertyModel(tenant_id=tenant.id, name="Other", internal_code="OTHER")
        db_session.add(other)
        await db_session.flush()
        repository = SqlAlchemyReservationRepository(db_session)
        reservation = _reservation(tenant, prop)
        await repository.add(tenant.id, reservation)

        reservation.property_id = other.id
        await repository.save(tenant.id, reservation)

        reloaded = await repository.get(tenant.id, reservation.id)
        assert reloaded is not None
        assert reloaded.property_id == prop.id


class TestListing:
    @pytest.mark.asyncio
    async def test_it_only_lists_the_tenants_own_reservations(self, db_session) -> None:
        tenant_a, prop_a = await _tenant_with_property(db_session, "TenantA")
        tenant_b, prop_b = await _tenant_with_property(db_session, "TenantB")
        repository = SqlAlchemyReservationRepository(db_session)
        mine = _reservation(tenant_a, prop_a)
        await repository.add(tenant_a.id, mine)
        await repository.add(tenant_b.id, _reservation(tenant_b, prop_b))

        page = await repository.list(tenant_a.id, NO_FILTERS, page=1, per_page=20)

        assert page.total == 1
        assert [item.id for item in page.items] == [mine.id]

    @pytest.mark.asyncio
    async def test_it_filters_by_status_and_property(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        other = PropertyModel(tenant_id=tenant.id, name="Other", internal_code="OTHER")
        db_session.add(other)
        await db_session.flush()
        repository = SqlAlchemyReservationRepository(db_session)
        confirmed = _reservation(tenant, prop, status=ReservationStatus.CONFIRMED)
        await repository.add(tenant.id, confirmed)
        await repository.add(
            tenant.id, _reservation(tenant, prop, status=ReservationStatus.CANCELLED)
        )

        by_status = await repository.list(
            tenant.id,
            ReservationFilters(status=ReservationStatus.CONFIRMED),
            page=1,
            per_page=20,
        )
        by_property = await repository.list(
            tenant.id, ReservationFilters(property_id=other.id), page=1, per_page=20
        )

        assert [item.id for item in by_status.items] == [confirmed.id]
        assert by_property.total == 0

    @pytest.mark.asyncio
    async def test_the_date_range_matches_stays_that_overlap_it(self, db_session) -> None:
        """Design D12: a guest already in the flat when the window opens belongs to the
        answer, even though they arrived before it."""
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        spanning = _reservation(tenant, prop, check_in=date(2026, 8, 1), nights=10)
        before = _reservation(tenant, prop, check_in=date(2026, 7, 1), nights=2)
        after = _reservation(tenant, prop, check_in=date(2026, 9, 1), nights=2)
        for reservation in (spanning, before, after):
            await repository.add(tenant.id, reservation)

        page = await repository.list(
            tenant.id,
            ReservationFilters(date_from=date(2026, 8, 5), date_to=date(2026, 8, 6)),
            page=1,
            per_page=20,
        )

        assert [item.id for item in page.items] == [spanning.id]

    @pytest.mark.asyncio
    async def test_it_pages_with_a_stable_order_and_a_total_of_the_whole_set(
        self, db_session
    ) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        for offset in range(5):
            await repository.add(
                tenant.id, _reservation(tenant, prop, check_in=date(2026, 8, 1 + offset))
            )

        first = await repository.list(tenant.id, NO_FILTERS, page=1, per_page=2)
        second = await repository.list(tenant.id, NO_FILTERS, page=2, per_page=2)
        third = await repository.list(tenant.id, NO_FILTERS, page=3, per_page=2)

        assert first.total == second.total == third.total == 5
        assert [len(first.items), len(second.items), len(third.items)] == [2, 2, 1]
        # Newest stay first, and no row appears on two pages.
        seen = [item.check_in_date for item in first.items + second.items + third.items]
        assert seen == sorted(seen, reverse=True)
        assert len({item.id for item in first.items + second.items + third.items}) == 5

    @pytest.mark.asyncio
    async def test_reservations_sharing_a_check_in_date_do_not_swap_between_pages(
        self, db_session
    ) -> None:
        """Without the `id` tie-break a client paging through would see one twice."""
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        for _ in range(4):
            await repository.add(tenant.id, _reservation(tenant, prop, check_in=date(2026, 8, 1)))

        first = await repository.list(tenant.id, NO_FILTERS, page=1, per_page=2)
        second = await repository.list(tenant.id, NO_FILTERS, page=2, per_page=2)

        assert len({item.id for item in first.items + second.items}) == 4


class TestListForProperties:
    """`celery-jobs` R3: the batch read its scheduled jobs use instead of paginating."""

    @pytest.mark.asyncio
    async def test_it_returns_reservations_of_the_named_properties_only(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        other = PropertyModel(tenant_id=tenant.id, name="Second", internal_code="TenantA-2")
        db_session.add(other)
        await db_session.flush()
        repository = SqlAlchemyReservationRepository(db_session)
        mine = _reservation(tenant, prop, check_in=date(2026, 8, 1))
        theirs = _reservation(tenant, other, check_in=date(2026, 8, 1))
        await repository.add(tenant.id, mine)
        await repository.add(tenant.id, theirs)

        found = await repository.list_for_properties(
            tenant.id, [prop.id], date(2026, 7, 30), date(2026, 8, 10)
        )

        assert [r.id for r in found] == [mine.id]

    @pytest.mark.asyncio
    async def test_it_matches_a_stay_that_merely_overlaps_the_window(self, db_session) -> None:
        """A guest already in the flat when the window opens is part of the answer (D12)."""
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        straddling = _reservation(tenant, prop, check_in=date(2026, 7, 28), nights=6)
        await repository.add(tenant.id, straddling)

        found = await repository.list_for_properties(
            tenant.id, [prop.id], date(2026, 8, 1), date(2026, 8, 2)
        )

        assert [r.id for r in found] == [straddling.id]

    @pytest.mark.asyncio
    async def test_the_window_bounds_are_inclusive(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        # Checks out exactly on the first day of the window.
        leaving = _reservation(tenant, prop, check_in=date(2026, 7, 29), nights=3)
        # Checks in exactly on the last day of the window.
        arriving = _reservation(tenant, prop, check_in=date(2026, 8, 2), nights=2)
        await repository.add(tenant.id, leaving)
        await repository.add(tenant.id, arriving)

        found = await repository.list_for_properties(
            tenant.id, [prop.id], date(2026, 8, 1), date(2026, 8, 2)
        )

        assert {r.id for r in found} == {leaving.id, arriving.id}

    @pytest.mark.asyncio
    async def test_a_stay_outside_the_window_is_not_returned(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        await repository.add(tenant.id, _reservation(tenant, prop, check_in=date(2026, 9, 1)))

        found = await repository.list_for_properties(
            tenant.id, [prop.id], date(2026, 8, 1), date(2026, 8, 2)
        )

        assert found == []

    @pytest.mark.asyncio
    async def test_it_does_not_filter_by_status(self, db_session) -> None:
        """Which statuses are eligible is the state machine's call, not this query's."""
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        cancelled = _reservation(
            tenant, prop, check_in=date(2026, 8, 1), status=ReservationStatus.CANCELLED
        )
        await repository.add(tenant.id, cancelled)

        found = await repository.list_for_properties(
            tenant.id, [prop.id], date(2026, 7, 30), date(2026, 8, 10)
        )

        assert [r.id for r in found] == [cancelled.id]

    @pytest.mark.asyncio
    async def test_it_does_not_reach_another_tenant(self, db_session) -> None:
        tenant_a, prop_a = await _tenant_with_property(db_session, "TenantA")
        tenant_b, prop_b = await _tenant_with_property(db_session, "TenantB")
        repository = SqlAlchemyReservationRepository(db_session)
        await repository.add(tenant_b.id, _reservation(tenant_b, prop_b, check_in=date(2026, 8, 1)))

        # Even naming the neighbour's property id explicitly, the tenant filter decides.
        found = await repository.list_for_properties(
            tenant_a.id, [prop_a.id, prop_b.id], date(2026, 7, 30), date(2026, 8, 10)
        )

        assert found == []

    @pytest.mark.asyncio
    async def test_without_property_ids_it_returns_empty(self, db_session) -> None:
        tenant, prop = await _tenant_with_property(db_session, "TenantA")
        repository = SqlAlchemyReservationRepository(db_session)
        await repository.add(tenant.id, _reservation(tenant, prop, check_in=date(2026, 8, 1)))

        assert await repository.list_for_properties(
            tenant.id, [], date(2026, 7, 30), date(2026, 8, 10)
        ) == []
