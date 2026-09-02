"""Tenant isolation of the `dashboard` module (DoD §28.18, `dashboard-api` task 6.5).

R1.1: "una card por propiedad **de su tenant**, y ninguna de otro tenant."

The module reads seven other domains' tables, so this is the test that says a user of tenant
A sees nothing of tenant B **through any of the four routes** — not just that each adapter
is scoped, which their own suites already prove one table at a time.

The neighbour's data is seeded directly through the ORM rather than through the API, for the
reason `tests/properties/conftest.py` records: these tests share one session, and a request
as tenant B would leave it bound to B, so the next call as tenant A would answer `401`
instead of the `404` or the filtered `200` under test.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.auth.domain.enums import UserRole
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import CleaningTaskModel
from app.guests.infrastructure.models import GuestModel
from app.maintenance.domain.enums import IncidentSeverity, IncidentSource, IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.infrastructure.models import TimelineEventModel
from tests.cleaning.conftest import insert_template
from tests.dashboard.conftest import TODAY, auth_header

COLLECTION = "/api/v1/dashboard/properties"
NEIGHBOUR_MARKERS = (
    "PAJARITOS8",
    "NEIGHBOUR-REF",
    "Neighbour stored title",
    "Neighbour Guest",
)


@pytest.fixture
def owner_headers(api, users_by_role_a):
    return auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])


@pytest_asyncio.fixture
async def neighbour_world(db_session, tenant_b, property_b):
    """A fully populated property in tenant B: reservation, cleaning task, incident, event.

    Every one of them is something a leak would show, and each carries a marker string so a
    response can be searched for it rather than only counted.
    """
    # The neighbour's reservation carries a **guest**, and that is load-bearing rather than
    # decoration: without it, `guest_ids` reaching `GuestRepository.list_for_ids` is always
    # empty and this file's assertions would pass whether or not that adapter filtered by
    # tenant at all. The tenancy panel of sections 6-7 caught exactly that.
    neighbour_guest = GuestModel(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        full_name="Neighbour Guest",
        email="neighbour@example.com",
    )
    db_session.add(neighbour_guest)
    await db_session.flush()

    reservation = ReservationModel(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        property_id=property_b.id,
        guest_id=neighbour_guest.id,
        channel=ReservationChannel.BOOKING,
        external_pms_id="NEIGHBOUR-REF",
        status=ReservationStatus.CONFIRMED,
        check_in_date=TODAY,
        check_out_date=TODAY + timedelta(days=1),
        nights=1,
        adults=2,
    )
    db_session.add(reservation)

    # Built through `cleaning`'s own helper: the template has required JSONB columns, and
    # re-deriving them here would be a second definition of that module's fixture shape.
    template = await insert_template(db_session, tenant_b, name="Neighbour template")
    db_session.add(
        CleaningTaskModel(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            property_id=property_b.id,
            checklist_template_id=template.id,
            status=CleaningTaskStatus.IN_PROGRESS,
            # `dashboard-operational-kpis` R1/R4.4: scheduled today, so a leaking
            # `count_live_for_day` would show up in tenant A's `cleanings_today`.
            scheduled_start=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
        )
    )

    db_session.add(
        IncidentModel(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            property_id=property_b.id,
            source=IncidentSource.GUEST,
            title="Neighbour incident",
            description="Neighbour description",
            status=IncidentStatus.OPEN,
            # `dashboard-operational-kpis` R3/R4.4: urgent, so a leaking
            # `count_open_for_tenant` would show up in both `total` and `urgent`.
            severity=IncidentSeverity.CRITICAL,
        )
    )

    db_session.add(
        TimelineEventModel(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            property_id=property_b.id,
            actor_type=TimelineActorType.SYSTEM,
            event_type=TimelineEventType.CLEANING_COMPLETED,
            severity=TimelineSeverity.INFO,
            title="Neighbour stored title",
            created_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        )
    )
    await db_session.flush()
    return property_b


@pytest.mark.asyncio
async def test_the_collection_shows_no_property_of_another_tenant(
    api, owner_headers, property_a, neighbour_world
) -> None:
    response = await api.get(COLLECTION, headers=owner_headers)

    body = response.json()
    assert body["total"] == 1, "the neighbour's property was counted"
    assert [card["property_code"] for card in body["data"]] == ["REDES11"]
    for marker in NEIGHBOUR_MARKERS:
        assert marker not in response.text


@pytest.mark.asyncio
async def test_the_collection_shows_no_neighbour_data_on_its_own_cards(
    api, owner_headers, property_a, neighbour_world
) -> None:
    """The subtler leak: the right properties, carrying someone else's reservation,
    cleaning status, incident count or last event."""
    card = (await api.get(COLLECTION, headers=owner_headers)).json()["data"][0]

    assert card["current_or_next_reservation"] is None
    assert card["cleaning_status"] is None
    assert card["open_incidents_count"] == 0
    assert card["last_event_label"] is None


@pytest.mark.asyncio
async def test_the_guest_join_resolves_only_within_the_tenant(
    api, db_session, tenant_a, owner_headers, property_a, neighbour_world
) -> None:
    """The aggregate does not merge a neighbour's reservation or guest onto a shared card.

    **What this proves, precisely.** Both tenants have a reservation with a guest, so the
    aggregate runs its full join — `list_for_ids` is called with a non-empty batch — and
    tenant A gets its own guest and nothing of tenant B's.

    **What it does not prove**, and the tenancy panel of sections 6-7 was right to insist on
    the distinction: it is *not* the regression guard for `list_for_ids`' own tenant
    predicate. The neighbour's guest id never enters the batch, because the neighbour's
    reservation is already excluded one layer up by `property_id` — so removing that
    predicate would leave this test green. The guard for it is
    `tests/guests/test_repositories.py::test_list_for_ids_never_reads_another_tenants_guest`,
    which passes the foreign id in explicitly.

    A first version of this docstring claimed the stronger thing. That claim is exactly the
    failure this whole finding was about — a test that looks like it covers a path and never
    reaches it — so it is corrected rather than quietly dropped.
    """
    own_guest = GuestModel(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        full_name="Marta Propia",
        email="marta@example.com",
    )
    db_session.add(own_guest)
    await db_session.flush()
    db_session.add(
        ReservationModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            guest_id=own_guest.id,
            channel=ReservationChannel.DIRECT,
            external_pms_id="OWN-REF",
            status=ReservationStatus.CONFIRMED,
            check_in_date=TODAY,
            check_out_date=TODAY + timedelta(days=1),
            nights=1,
            adults=2,
        )
    )
    await db_session.flush()

    response = await api.get(COLLECTION, headers=owner_headers)

    card = response.json()["data"][0]
    assert card["current_or_next_reservation"] is not None, (
        "tenant A's own reservation must resolve, or this test is vacuous"
    )
    assert card["current_or_next_reservation"]["guest_name"] == "Marta Propia"
    assert "Neighbour Guest" not in response.text
    for marker in NEIGHBOUR_MARKERS:
        assert marker not in response.text


@pytest.mark.asyncio
async def test_the_aggregate_of_a_neighbours_property_is_404(
    api, owner_headers, neighbour_world
) -> None:
    response = await api.get(
        f"/api/v1/properties/{neighbour_world.id}/dashboard", headers=owner_headers
    )

    assert response.status_code == 404
    for marker in NEIGHBOUR_MARKERS:
        assert marker not in response.text


@pytest.mark.asyncio
async def test_the_property_state_of_a_neighbours_property_is_404(
    api, owner_headers, neighbour_world
) -> None:
    response = await api.get(
        f"/api/v1/properties/{neighbour_world.id}/state", headers=owner_headers
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_timeline_of_a_neighbours_property_is_404(
    api, owner_headers, neighbour_world
) -> None:
    """R4.5 — and the neighbour genuinely has an event, so an empty page would not have
    produced this answer by accident."""
    response = await api.get(
        f"/api/v1/timeline/{neighbour_world.id}", headers=owner_headers
    )

    assert response.status_code == 404
    assert "Neighbour stored title" not in response.text


@pytest.mark.asyncio
async def test_the_aggregate_of_an_own_property_carries_none_of_the_neighbours_rows(
    api, owner_headers, property_a, neighbour_world
) -> None:
    """The four routes agree: nothing of tenant B reaches tenant A by any path."""
    response = await api.get(
        f"/api/v1/properties/{property_a.id}/dashboard", headers=owner_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_or_next_reservation"] is None
    assert body["cleaning_status"] is None
    assert body["open_incidents"] == []
    assert body["pending_approvals"] == []
    for marker in (*NEIGHBOUR_MARKERS, "Neighbour description", "Neighbour incident"):
        assert marker not in response.text


# --- `/dashboard/operational-kpis` (`dashboard-operational-kpis` R4.4) --------------------
#
# One test per count, per the design's mitigation for section 6's risk that a fourth
# permission-redacted response is "one more combination for a matrix to miss" — a single
# test asserting all three would still catch a leak, but would not say which count leaked.


@pytest.mark.asyncio
async def test_cleanings_today_does_not_include_a_neighbours_live_task(
    api, owner_headers, property_a, neighbour_world
) -> None:
    """Tenant A has nothing scheduled; tenant B has a live task scheduled today."""
    response = await api.get("/api/v1/dashboard/operational-kpis", headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["cleanings_today"] == 0


@pytest.mark.asyncio
async def test_upcoming_checkins_does_not_include_a_neighbours_check_in(
    api, owner_headers, property_a, neighbour_world
) -> None:
    """Tenant A has no reservation; tenant B has a check-in inside the window."""
    response = await api.get("/api/v1/dashboard/operational-kpis", headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["upcoming_checkins"] == 0


@pytest.mark.asyncio
async def test_open_incidents_does_not_include_a_neighbours_urgent_incident(
    api, owner_headers, property_a, neighbour_world
) -> None:
    """Tenant A has no incident; tenant B has one open **and** urgent (`CRITICAL`), so a
    leak into either `total` or `urgent` alone would show up here."""
    response = await api.get("/api/v1/dashboard/operational-kpis", headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["open_incidents"] == {"total": 0, "urgent": 0}
