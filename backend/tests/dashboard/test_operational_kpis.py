"""`GetOperationalKpisUseCase` (`dashboard-operational-kpis` R1, R2, R3, R4, task 5.3).

Unit tests over in-memory fakes of the three ports it composes, per
`steering/testing.md`. What they pin is design D4: a role lacking a source's permission
gets `None` for that field and the query is **skipped entirely**, never run and discarded.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.auth.domain.enums import UserRole
from app.dashboard.application.use_cases import (
    UPCOMING_CHECKIN_WINDOW_DAYS,
    GetOperationalKpisUseCase,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.maintenance.domain.value_objects import OpenIncidentCounts
from tests.dashboard.doubles import (
    FakeCleaningRepository,
    FakeIncidentReader,
    FakeReservationRepository,
    make_cleaning,
    make_reservation,
)

TENANT = uuid.uuid4()
TODAY = date(2026, 8, 9)


def _use_case(*, cleaning, reservations, incidents) -> GetOperationalKpisUseCase:
    return GetOperationalKpisUseCase(
        cleaning=cleaning, reservations=reservations, incidents=incidents
    )


def _world():
    """A tenant with something to count on all three fronts."""
    prop_id = uuid.uuid4()
    return {
        "cleaning": FakeCleaningRepository(
            {TENANT: [make_cleaning(prop_id, CleaningTaskStatus.IN_PROGRESS)]}
        ),
        "reservations": FakeReservationRepository(
            {TENANT: [make_reservation(TENANT, prop_id, check_in=TODAY)]}
        ),
        "incidents": FakeIncidentReader(
            open_for_tenant={TENANT: OpenIncidentCounts(total=3, urgent=1)}
        ),
    }


@pytest.mark.asyncio
async def test_a_role_with_all_three_permissions_gets_three_real_values() -> None:
    world = _world()
    use_case = _use_case(**world)

    kpis = await use_case.execute(tenant_id=TENANT, role=UserRole.TENANT_OWNER, today=TODAY)

    assert kpis.cleanings_today == 1
    assert kpis.upcoming_checkins == 1
    assert kpis.open_incidents is not None
    assert (kpis.open_incidents.total, kpis.open_incidents.urgent) == (3, 1)


@pytest.mark.asyncio
async def test_the_cleaner_gets_only_its_own_count_and_the_others_fakes_are_never_called() -> (
    None
):
    """`CLEANER` holds only `READ_CLEANING_TASKS` (design D4)."""
    world = _world()
    use_case = _use_case(**world)

    kpis = await use_case.execute(tenant_id=TENANT, role=UserRole.CLEANER, today=TODAY)

    assert kpis.cleanings_today == 1
    assert kpis.upcoming_checkins is None
    assert kpis.open_incidents is None
    assert world["reservations"].calls == []
    assert world["incidents"].calls == []


@pytest.mark.asyncio
async def test_the_technician_gets_only_open_incidents_and_the_others_fakes_are_never_called() -> (
    None
):
    """`TECHNICIAN` holds only `READ_INCIDENTS` (design D4)."""
    world = _world()
    use_case = _use_case(**world)

    kpis = await use_case.execute(tenant_id=TENANT, role=UserRole.TECHNICIAN, today=TODAY)

    assert kpis.cleanings_today is None
    assert kpis.upcoming_checkins is None
    assert kpis.open_incidents is not None
    assert (kpis.open_incidents.total, kpis.open_incidents.urgent) == (3, 1)
    assert world["cleaning"].calls == []
    assert world["reservations"].calls == []


@pytest.mark.asyncio
async def test_a_role_with_none_of_the_three_permissions_gets_null_everywhere_and_costs_zero_queries() -> (
    None
):
    """`SUPER_ADMIN` holds none of the three (design D4's "costs zero domain queries")."""
    world = _world()
    use_case = _use_case(**world)

    kpis = await use_case.execute(tenant_id=TENANT, role=UserRole.SUPER_ADMIN, today=TODAY)

    assert kpis.cleanings_today is None
    assert kpis.upcoming_checkins is None
    assert kpis.open_incidents is None
    assert world["cleaning"].calls == []
    assert world["reservations"].calls == []
    assert world["incidents"].calls == []


@pytest.mark.asyncio
async def test_a_tenant_with_nothing_scheduled_or_open_gets_zeroes_not_nulls() -> None:
    """R1.3, R2.3, R3.3 — a role that may read everything and finds nothing gets `0`."""
    empty = {
        "cleaning": FakeCleaningRepository(),
        "reservations": FakeReservationRepository(),
        "incidents": FakeIncidentReader(),
    }
    use_case = _use_case(**empty)

    kpis = await use_case.execute(tenant_id=TENANT, role=UserRole.TENANT_OWNER, today=TODAY)

    assert kpis.cleanings_today == 0
    assert kpis.upcoming_checkins == 0
    assert kpis.open_incidents is not None
    assert (kpis.open_incidents.total, kpis.open_incidents.urgent) == (0, 0)


@pytest.mark.asyncio
async def test_the_reservations_fake_is_called_with_the_inclusive_seven_day_window() -> None:
    """Proves `UPCOMING_CHECKIN_WINDOW_DAYS` (5.1), not a hand-rolled window, is what runs."""
    world = _world()
    use_case = _use_case(**world)

    await use_case.execute(tenant_id=TENANT, role=UserRole.TENANT_OWNER, today=TODAY)

    assert world["reservations"].calls == [
        (
            "count_check_ins_in_range",
            TENANT,
            TODAY,
            TODAY + timedelta(days=UPCOMING_CHECKIN_WINDOW_DAYS),
        )
    ]
