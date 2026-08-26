"""Identity isolation by tenant (`reservation-property-identity` R5.3, D7).

A reservation whose `property_id` points at another tenant's row must appear in the
response with `property_name` and `property_internal_code` as `None` (with their
key), and the rest of the row's columns intact. The composition with `tenant_id`
explicit per call (`dashboard-api` D2) makes that degradation the natural outcome
of the design — this test is what pins it.

**Asymmetry between `property_id` and `guest_id` on disk**:

The schema (`backend/app/reservations/infrastructure/models.py:53-58`) puts a
composite `ForeignKeyConstraint(["tenant_id", "guest_id"], ["guests.tenant_id", "guests.id"], name="fk_reservations_guest_within_tenant")`
on `guest_id`, deliberately added by `guest_portal_api` (Alembic
`e7a3c419d82b`). That makes a cross-tenant `guest_id` **structurally
impossible** — the row cannot exist on disk, and a test that tried to seed one
hits `IntegrityError`. `property_id` keeps its plain FK to `properties.id`, so
a cross-tenant `property_id` IS reachable and this file only exercises that one.

The proposal's R5.3 / D5 also covers the `guest_id` half; the DB constraint
collapses the foreign-tenant case into the no-row case by construction, so the
application-level handling stays `None` for both. This is the resolution that
`proposal.md` R5.3 clause 3 and `design.md` D5 record: R5.3's "Igual para
`guest_id` apuntando a otro tenant" is satisfied **vacuously** by the composite
FK, and `BLOCKED.md` no longer carries an open entry on this. If a future
change relaxes the composite FK on `guest_id`, this file should grow a
cross-tenant `guest_id` test mirroring the existing property one — until then,
no follow-up is open.

**Why the reservations here go through `ReservationModel.add(...)` and not the
use case**: the `CreateReservationUseCase` holds a hard invariant — `property_id`
must be the caller's tenant's property, otherwise it raises
`PropertyNotFoundError`. We need to bypass it because we are testing the
cross-tenant case the use case refuses to write in the first place. Inserting
the model row directly is the documented way to simulate a "reservation whose
FK was rewritten by something we don't trust" — same fixture choice the
authorisation tests use to seed rows of another tenant
(`tests/reservations/conftest.py:84`).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.reservations.application.use_cases import (
    GetReservationUseCase,
    ListReservationsUseCase,
)
from app.reservations.domain.repositories import ReservationFilters
from app.reservations.infrastructure.models import ReservationModel
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from tests.auth.conftest import utc_now


def _auth(client, user) -> dict[str, str]:
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    return {"Authorization": f"Bearer {token}"}


async def _insert_reservation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    guest_id: uuid.UUID | None = None,
) -> ReservationModel:
    """Insert a `ReservationModel` directly with the given FKs — bypasses the use case
    precisely because the use case refuses a cross-tenant FK at the write side.

    Same shape `tests/reservations/conftest.py:71-95` uses to seed property rows of
    both tenants; the parallels are deliberate so the technique is one the reader
    already knows.
    """
    reservation = ReservationModel(
        tenant_id=tenant_id,
        property_id=property_id,
        guest_id=guest_id,
        channel="DIRECT",
        check_in_date=__import__("datetime").date(2026, 8, 1),
        check_out_date=__import__("datetime").date(2026, 8, 4),
        nights=3,
    )
    session.add(reservation)
    await session.flush()
    return reservation


@pytest.mark.asyncio
async def test_the_detail_with_a_cross_tenant_property_degrades_to_none(
    api, db_session, users_by_role_a, tenant_b, property_a, property_b
) -> None:
    """R2.2 + D5: a `property_id` pointing at another tenant's property MUST yield
    the two derived fields as `None` (with their key), NOT a `404`, and the rest of
    the row must remain intact.

    Possible at the DB level because `property_id` is a single-column FK to
    `properties.id` (`backend/app/reservations/infrastructure/models.py:64-66`),
    which is what makes the test reachable.
    """
    manager_a = users_by_role_a["PROPERTY_MANAGER"]
    reservation = await _insert_reservation(
        db_session,
        tenant_id=manager_a.tenant_id,
        property_id=property_a.id,
    )
    reservation.property_id = property_b.id  # cross-tenant FK
    await db_session.flush()

    response = await api.get(
        f"/api/v1/reservations/{reservation.id}",
        headers=_auth(api, manager_a),
    )

    assert response.status_code == 200, (
        "D5 forbids 404 here — the entity is the reservation and it resolved; the FK "
        "did not. A 404 would lie about the principal entity."
    )
    body = response.json()
    assert body["property_id"] == str(property_b.id)
    assert body["property_name"] is None
    assert body["property_internal_code"] is None


@pytest.mark.asyncio
async def test_the_listing_with_cross_tenant_fks_still_returns_the_reservations(
    api, db_session, users_by_role_a, tenant_a, tenant_b, property_a, property_b
) -> None:
    """R1.2 + D7: the listing keeps the cross-tenant `property_id` reservation visible
    — the FK is one fact, the response shape is the publication rule, and a listing
    that hides such rows would be lying about the principal entity.

    The guest half of this assertion lives in
    `test_a_reservation_without_a_guest_yields_none_guest_full_name` and the FK
    asymmetry note above — the composite FK prevents the cross-tenant `guest_id`
    row from existing at all, so the application-level handling collapses to
    `guest_full_name = None` on every code path that lands there.
    """
    manager_a = users_by_role_a["PROPERTY_MANAGER"]
    local = await _insert_reservation(
        db_session,
        tenant_id=manager_a.tenant_id,
        property_id=property_a.id,
        guest_id=None,
    )
    fk_property = await _insert_reservation(
        db_session,
        tenant_id=manager_a.tenant_id,
        property_id=property_a.id,
        guest_id=None,
    )
    fk_property.property_id = property_b.id  # cross-tenant FK
    await db_session.commit()

    use_case = ListReservationsUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
    )
    page = await use_case.execute(
        tenant_id=manager_a.tenant_id,
        filters=ReservationFilters(),
        page=1,
        per_page=50,
    )

    # Two reservations, both visible — the FK is one fact, the publication rule is the
    # whole row (D5), and hiding the cross-tenant one would lie about the entity.
    assert len(page.items) == 2
    by_property_id = {item.property_id: item for item in page.items}

    # local — both names populated.
    assert by_property_id[property_a.id].property_name == property_a.name
    assert by_property_id[property_a.id].property_internal_code == property_a.internal_code
    assert by_property_id[property_a.id].guest_full_name is None  # never had a guest

    # cross-tenant property id — names None, id kept.
    assert by_property_id[property_b.id].property_id == property_b.id
    assert by_property_id[property_b.id].property_name is None
    assert by_property_id[property_b.id].property_internal_code is None


@pytest.mark.asyncio
async def test_no_5xx_occurs_when_the_batch_reader_meets_a_cross_tenant_id(
    db_session, users_by_role_a, tenant_a, tenant_b, property_a, property_b
) -> None:
    """R5.3 last clause: a `reservation.property_id` pointing at another tenant's
    property MUST NEVER raise a 5xx; the batch composition is what saves us from
    that. This drills into the use case directly so an HTTP layer issue does not
    mask a backend regression on this exact path.
    """
    manager_a = users_by_role_a["PROPERTY_MANAGER"]
    reservation = await _insert_reservation(
        db_session,
        tenant_id=manager_a.tenant_id,
        property_id=property_a.id,
    )
    reservation.property_id = property_b.id
    await db_session.flush()

    use_case = ListReservationsUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
    )

    from app.reservations.domain.repositories import ReservationFilters
    page = await use_case.execute(
        tenant_id=manager_a.tenant_id,
        filters=ReservationFilters(),
        page=1,
        per_page=50,
    )

    assert len(page.items) == 1
    assert page.items[0].property_id == property_b.id
    assert page.items[0].property_name is None
    assert page.items[0].property_internal_code is None


@pytest.mark.asyncio
async def test_no_5xx_occurs_on_detail_with_a_cross_tenant_id(
    db_session, users_by_role_a, property_a, property_b
) -> None:
    """Same as above for the detail path: `GetReservationUseCase` must degrade, not
    raise. The pin of R5.3 says the FK-in-foreign-tenant MUST not surface as a 5xx;
    a `PropertyNotFoundError` raised here would be the regression to catch.
    """
    manager_a = users_by_role_a["PROPERTY_MANAGER"]
    reservation = await _insert_reservation(
        db_session,
        tenant_id=manager_a.tenant_id,
        property_id=property_a.id,
    )
    reservation.property_id = property_b.id
    await db_session.flush()

    use_case = GetReservationUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
    )

    detail = await use_case.execute(
        tenant_id=manager_a.tenant_id, reservation_id=reservation.id
    )

    assert detail.reservation.id == reservation.id
    assert detail.property_name is None
    assert detail.property_internal_code is None


@pytest.mark.asyncio
async def test_a_reservation_without_a_guest_yields_none_guest_full_name(
    api, db_session, users_by_role_a, property_a
) -> None:
    """R3.2 + R4.2: a reservation without a guest has `guest_full_name` None and
    `guest_id` None. Manual bookings are the canonical case (today the only one,
    since the PMS sync still belongs to a future change).
    """
    manager_a = users_by_role_a["PROPERTY_MANAGER"]
    reservation = await _insert_reservation(
        db_session,
        tenant_id=manager_a.tenant_id,
        property_id=property_a.id,
        guest_id=None,
    )
    assert reservation.guest_id is None

    response = await api.get(
        f"/api/v1/reservations/{reservation.id}",
        headers=_auth(api, manager_a),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["guest_id"] is None
    assert body["guest_full_name"] is None
