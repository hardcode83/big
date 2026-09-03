"""The collection resolves in a fixed number of queries (`dashboard-api` R1.7, task 6.4).

R1.7: "THE SYSTEM SHALL resolver la colección completa **sin una consulta por propiedad**
(sin N+1), y un test SHALL demostrarlo contando las consultas emitidas."

The design says why this is an assertion and not a metric: *"Un `for` en el caso de uso que
llame a un `get` por propiedad es sintácticamente idéntico al código correcto."* Nothing
about the wrong version looks wrong in review — only the count separates them.

**Two sizes, and the ceiling is the same number for both.** A single size would pass for a
constant that happened to match it; two sizes five times apart make "does not grow with N"
the thing being asserted rather than "is under some number I picked".
"""

import pytest

from app.auth.domain.enums import UserRole
from tests.dashboard.conftest import auth_header, insert_property
from tests.sql_counter import count_statements

COLLECTION = "/api/v1/dashboard/properties"

#: The tables the collection reads. Named rather than counting every statement, so a
#: `SELECT` the auth dependency issues to load the caller cannot be mistaken for a card
#: query — that one genuinely is per *request*, not per property.
READ_TABLES = (
    "from properties",
    "from reservations",
    "from guests",
    "from cleaning_tasks",
    "from incidents",
    "from timeline_events",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("property_count", [2, 10])
async def test_the_collection_costs_the_same_whatever_the_portfolio_size(
    api, db_session, test_engine, tenant_a, users_by_role_a, property_count: int
) -> None:
    for index in range(property_count):
        await insert_property(db_session, tenant_a, code=f"FLAT-{index}")
    headers = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    with count_statements(test_engine) as log:
        response = await api.get(
            f"{COLLECTION}?per_page=100", headers=headers
        )

    assert response.status_code == 200
    assert len(response.json()["data"]) == property_count

    per_table = {table: len(log.matching(table)) for table in READ_TABLES}
    for table, count in per_table.items():
        assert count <= 2, (
            f"{table} was queried {count} times for {property_count} properties; "
            f"the collection must batch. Full tally: {per_table}"
        )


@pytest.mark.asyncio
async def test_the_ceiling_does_not_move_between_two_and_ten(
    api, db_session, test_engine, tenant_a, users_by_role_a
) -> None:
    """The assertion R1.7 actually asks for: not "few queries" but "the same number".

    Measured twice in one test so the two counts are compared directly rather than through
    a constant somebody could quietly raise.
    """
    headers = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    for index in range(2):
        await insert_property(db_session, tenant_a, code=f"SMALL-{index}")
    with count_statements(test_engine) as small_log:
        await api.get(f"{COLLECTION}?per_page=100", headers=headers)
    small = {table: len(small_log.matching(table)) for table in READ_TABLES}

    for index in range(8):
        await insert_property(db_session, tenant_a, code=f"BIG-{index}")
    with count_statements(test_engine) as big_log:
        response = await api.get(f"{COLLECTION}?per_page=100", headers=headers)
    big = {table: len(big_log.matching(table)) for table in READ_TABLES}

    assert len(response.json()["data"]) == 10
    assert small == big, (
        f"the query tally grew with the portfolio: 2 properties → {small}, "
        f"10 properties → {big}"
    )


# --- `/dashboard/occupancy-series` (`dashboard-occupancy-series` R3.2) --------------------

SERIES = "/api/v1/dashboard/occupancy-series"

#: The tables this route reads. `properties` and `reservations` cost one statement each
#: (`PropertyRepository.list_by_status`, `ReservationRepository.list_for_properties`);
#: `property_state_transitions` costs two — the entering-transition read and the in-window
#: range scan `history_for_properties` issues (task 1.2's Implementation Note), portfolio-
#: independent by the same design as the collection's own reader.
SERIES_READ_TABLES = (
    "from properties",
    "from reservations",
    "from property_state_transitions",
)
SERIES_CEILINGS = {
    "from properties": 1,
    "from reservations": 1,
    "from property_state_transitions": 2,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("property_count", [2, 10])
async def test_the_series_costs_the_same_whatever_the_portfolio_size(
    api, db_session, test_engine, tenant_a, users_by_role_a, property_count: int
) -> None:
    for index in range(property_count):
        await insert_property(db_session, tenant_a, code=f"SERIES-{index}")
    headers = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    with count_statements(test_engine) as log:
        response = await api.get(SERIES, headers=headers)

    assert response.status_code == 200
    assert len(response.json()["data"]) == 7

    per_table = {table: len(log.matching(table)) for table in SERIES_READ_TABLES}
    for table, count in per_table.items():
        assert count <= SERIES_CEILINGS[table], (
            f"{table} was queried {count} times for {property_count} properties; "
            f"the series must batch. Full tally: {per_table}"
        )


@pytest.mark.asyncio
async def test_the_series_ceiling_does_not_move_between_two_and_ten(
    api, db_session, test_engine, tenant_a, users_by_role_a
) -> None:
    """The assertion R3.2 actually asks for: not "few queries" but "the same number"."""
    headers = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    for index in range(2):
        await insert_property(db_session, tenant_a, code=f"SERIES-SMALL-{index}")
    with count_statements(test_engine) as small_log:
        await api.get(SERIES, headers=headers)
    small = {table: len(small_log.matching(table)) for table in SERIES_READ_TABLES}

    for index in range(8):
        await insert_property(db_session, tenant_a, code=f"SERIES-BIG-{index}")
    with count_statements(test_engine) as big_log:
        response = await api.get(SERIES, headers=headers)
    big = {table: len(big_log.matching(table)) for table in SERIES_READ_TABLES}

    assert len(response.json()["data"]) == 7
    assert small == big, (
        f"the query tally grew with the portfolio: 2 properties → {small}, "
        f"10 properties → {big}"
    )


@pytest.mark.asyncio
async def test_the_counter_would_notice_a_per_property_query(
    api, db_session, test_engine, tenant_a, users_by_role_a
) -> None:
    """The guard on the guard: a counting test that cannot fail is worse than none.

    Ten deliberate per-property reads are issued inside the block, and the tally must show
    them — proving the listener sees the statements this suite claims to be counting.
    """
    from sqlalchemy import select

    from app.properties.infrastructure.models import PropertyModel

    properties = [
        await insert_property(db_session, tenant_a, code=f"PROBE-{index}")
        for index in range(10)
    ]

    with count_statements(test_engine) as log:
        for item in properties:
            await db_session.execute(
                select(PropertyModel).where(PropertyModel.id == item.id)
            )

    assert len(log.matching("from properties")) == 10
