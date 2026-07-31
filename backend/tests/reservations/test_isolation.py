"""R5.1 over HTTP: tenant A cannot see or touch tenant B's reservations.

Rule 1 of `steering/security.md` requires these per module, and design D6 fixes the shape of
the answer: `404`, never `403`, so the response cannot be used to learn that a booking
exists somewhere else. This is the first capability where that is testable — its endpoints
are the first to take a resource identifier.

The neighbour's rows are seeded **directly**, not through the API. In production each request
gets its own session; the test app shares one, and `get_authenticated_request` marks it with
the acting tenant (design D16), so issuing a request as tenant B would leave the shared
session scoped to B and make the next request as A fail to reload its own user. Seeding the
row is also closer to what is being asserted: how it got there is irrelevant, only that A
cannot reach it.
"""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.auth.domain.enums import UserRole
from app.guests.infrastructure.models import GuestModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.core.db import TENANT_ID_SESSION_KEY
from app.reservations.infrastructure.models import ReservationModel
from tests.reservations.conftest import auth_header


@pytest.fixture
def manager_a(users_by_role_a):
    return users_by_role_a[UserRole.PROPERTY_MANAGER]


@pytest_asyncio.fixture
async def neighbour_reservation(db_session, tenant_b, property_b) -> ReservationModel:
    model = ReservationModel(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        property_id=property_b.id,
        channel=ReservationChannel.DIRECT,
        status=ReservationStatus.CONFIRMED,
        check_in_date=date(2026, 8, 1),
        check_out_date=date(2026, 8, 4),
        nights=3,
        adults=2,
        total_guests=2,
    )
    db_session.add(model)
    await db_session.flush()
    return model


def _unscoped(db_session):
    """Drop the tenant marker so a post-condition can inspect the NEIGHBOUR's row.

    After a request the shared test session carries tenant A's marker, so the listener of
    `app/core/db.py` filters every ORM read — including the assertions below, which would
    then see `None` for tenant B's row and pass for the wrong reason. Clearing the marker is
    the test looking behind the isolation boundary on purpose; production sessions are
    per-request and never reused this way.
    """
    db_session.info.pop(TENANT_ID_SESSION_KEY, None)
    return db_session


async def _create_mine(api, manager_a, create_payload) -> str:
    response = await api.post(
        "/api/v1/reservations", json=create_payload(), headers=auth_header(api, manager_a)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_reading_a_neighbours_reservation_answers_404_not_403(
    api, manager_a, neighbour_reservation
) -> None:
    response = await api.get(
        f"/api/v1/reservations/{neighbour_reservation.id}", headers=auth_header(api, manager_a)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_patching_a_neighbours_reservation_answers_404_and_changes_nothing(
    api, manager_a, neighbour_reservation, db_session
) -> None:
    theirs = neighbour_reservation.id

    response = await api.patch(
        f"/api/v1/reservations/{theirs}",
        json={"adults": 9},
        headers=auth_header(api, manager_a),
    )

    assert response.status_code == 404
    still = await _unscoped(db_session).scalar(
        select(ReservationModel.adults).where(ReservationModel.id == theirs)
    )
    assert still == 2


@pytest.mark.asyncio
async def test_cancelling_a_neighbours_reservation_answers_404_and_changes_nothing(
    api, manager_a, neighbour_reservation, db_session
) -> None:
    theirs = neighbour_reservation.id

    response = await api.delete(
        f"/api/v1/reservations/{theirs}", headers=auth_header(api, manager_a)
    )

    assert response.status_code == 404
    status = await _unscoped(db_session).scalar(
        select(ReservationModel.status).where(ReservationModel.id == theirs)
    )
    assert status is ReservationStatus.CONFIRMED


@pytest.mark.asyncio
async def test_the_listing_never_includes_a_neighbours_reservation(
    api, manager_a, create_payload, neighbour_reservation, db_session
) -> None:
    mine = await _create_mine(api, manager_a, create_payload)

    response = await api.get("/api/v1/reservations", headers=auth_header(api, manager_a))

    body = response.json()
    assert [row["id"] for row in body["data"]] == [mine]
    assert body["total"] == 1
    # Both rows DO exist — otherwise this would pass on an almost-empty table.
    assert await _unscoped(db_session).scalar(
        select(func.count()).select_from(ReservationModel)
    ) == 2


@pytest.mark.asyncio
async def test_filtering_by_a_neighbours_property_returns_nothing(
    api, manager_a, neighbour_reservation, property_b
) -> None:
    """`property_id` is a client-supplied filter, so it is a second way in."""
    response = await api.get(
        f"/api/v1/reservations?property_id={property_b.id}", headers=auth_header(api, manager_a)
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_creating_against_a_neighbours_property_answers_404(
    api, manager_a, create_payload, property_b
) -> None:
    response = await api.post(
        "/api/v1/reservations",
        json=create_payload(property_id=str(property_b.id)),
        headers=auth_header(api, manager_a),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_linking_a_neighbours_guest_answers_404(
    api, manager_a, create_payload, db_session, tenant_b
) -> None:
    """`guest_id` is the one reference that arrives as a raw UUID from the client (D18)."""
    theirs = GuestModel(tenant_id=tenant_b.id, full_name="Their Guest", email="t@example.com")
    db_session.add(theirs)
    await db_session.flush()

    response = await api.post(
        "/api/v1/reservations",
        json=create_payload(guest_id=str(theirs.id)),
        headers=auth_header(api, manager_a),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
