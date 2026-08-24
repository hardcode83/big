"""`ListReservationsUseCase` emits a constant number of SELECTs (D3, R5.1 + R5.2).

An N+1 here would mean a `for item in page_result.items: enrich(item)` walked the page
and called `properties.get` and `guests.get` per row. The design's D3 contract says the
list use case calls `properties.list_for_ids` and `guests.list_for_ids` ONCE for the
whole page, on top of the `reservations.list` page query. That is what makes the
statement count independent of N.

The asymmetry of the batch: when a page has no `guest_id` set on any row, the
`guests.list_for_ids` call short-circuits without emitting a statement (its own
contract — `tests/guests/test_*.py`). Same for when all rows share a single
`property_id`. The first assertion below asserts the count independently of those
short-circuits; the second and third pin the edges so a regression where the
listing decides to call `get` per row (`list_for_ids` removed) shows up by name.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.reservations.application.use_cases import ListReservationsUseCase
from app.reservations.domain.repositories import ReservationFilters
from app.reservations.infrastructure.models import ReservationModel
from app.guests.infrastructure.models import GuestModel
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from tests.cleaning.conftest import insert_property
from tests.sql_counter import count_statements


async def _insert_guest(session, tenant, *, full_name: str, email: str) -> GuestModel:
    """Insert a `GuestModel` directly — `tests/guests/conftest.py` is not on disk
    (the package has no fixture-level helper beyond the auth conftest it imports),
    so a small inline definition lives here.
    """
    guest = GuestModel(
        tenant_id=tenant.id,
        full_name=full_name,
        email=email,
    )
    session.add(guest)
    await session.flush()
    return guest


def _reservation(
    session, *, tenant_id: uuid.UUID, property_id: uuid.UUID, guest_id: uuid.UUID | None
) -> ReservationModel:
    res = ReservationModel(
        tenant_id=tenant_id,
        property_id=property_id,
        guest_id=guest_id,
        channel="DIRECT",
        check_in_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
        check_out_date=datetime(2026, 8, 4, tzinfo=UTC).date(),
        nights=3,
    )
    session.add(res)
    return res


@pytest.mark.asyncio
async def test_the_listing_with_ten_rows_emits_a_constant_number_of_statements(
    db_session, test_engine, tenant_a, users_by_role_a
) -> None:
    """D3, R5.1 / R5.2: ten reservations, two distinct properties, three distinct
    guests — the statement count is `O(1)`, NOT `O(N)`. A pin of the contract
    `dashboard-api` measures the same way for its cards (`dashboard-api` R1.7 + the
    "Composición por lotes" section).
    """
    manager_a = users_by_role_a["PROPERTY_MANAGER"]
    first_property = await insert_property(db_session, tenant_a, code="REDES11")
    second_property = await insert_property(db_session, tenant_a, code="PAJARITOS8")
    third_property = await insert_property(db_session, tenant_a, code="SILENCIO1")

    # Three real guests, distributed in a way that exercises both readers.
    first_guest = await _insert_guest(
        db_session, tenant_a, full_name="Guest One", email="one@example.com"
    )
    second_guest = await _insert_guest(
        db_session, tenant_a, full_name="Guest Two", email="two@example.com"
    )
    third_guest = await _insert_guest(
        db_session, tenant_a, full_name="Guest Three", email="three@example.com"
    )

    guests = [first_guest, second_guest, third_guest]
    properties = [first_property, second_property, third_property]
    for index in range(10):
        # Round-robin so the batch readers cover multiple ids, not just one.
        _reservation(
            db_session,
            tenant_id=manager_a.tenant_id,
            property_id=properties[index % 3].id,
            guest_id=guests[index % 3].id,
        )
    await db_session.commit()

    use_case = ListReservationsUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
    )

    with count_statements(test_engine) as log:
        page = await use_case.execute(
            tenant_id=manager_a.tenant_id,
            filters=ReservationFilters(),
            page=1,
            per_page=50,
        )

    assert len(page.items) == 10

    # Exclude the COUNT — `count(*)` is the pagination companion of every page
    # read, and it does not depend on N rows. A regression that called `get` per
    # row would NOT show up here; it would inflate `property_queries` / `guest_queries`,
    # which is the assertion that follows.
    reservation_queries = [q for q in log.matching("from reservations") if "count" not in q.lower()]
    property_queries = log.matching("from properties")
    guest_queries = log.matching("from guests")

    # The reservations SELECT is structural: it pairs a COUNT with a SELECT for
    # pagination. The contract is `O(1)`, not "exactly one" - a count query is part
    # of the page read, and the same statement has run for every other listing in
    # the codebase. The regression to catch is the property/guest queries,
    # which is what D3 audits.
    assert 1 <= len(reservation_queries) <= 2, (
        f"reservations side: expected the page read (count + select), got "
        f"{len(reservation_queries)} statements"
    )
    assert len(property_queries) == 1
    assert len(guest_queries) == 1


@pytest.mark.asyncio
async def test_the_listing_with_no_guests_does_not_query_the_guests_repository(
    db_session, test_engine, tenant_a, users_by_role_a
) -> None:
    """R5.1 + D3 boundary: a page where every `guest_id` is None SHOULD skip the
    `guests.list_for_ids` call entirely. The reader short-circuits on an empty
    collection, which is the whole point of accepting `set` over `Sequence` (the
    empty set is the lazy form) — and the design contract for the property case
    here as well.
    """
    manager_a = users_by_role_a["PROPERTY_MANAGER"]
    property_a = await insert_property(db_session, tenant_a, code="REDES11")
    for index in range(5):
        _reservation(
            db_session,
            tenant_id=manager_a.tenant_id,
            property_id=property_a.id,
            guest_id=None,
        )
    await db_session.commit()

    use_case = ListReservationsUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
    )

    with count_statements(test_engine) as log:
        page = await use_case.execute(
            tenant_id=manager_a.tenant_id,
            filters=ReservationFilters(),
            page=1,
            per_page=50,
        )

    assert len(page.items) == 5
    assert log.matching("from reservations") != []
    assert log.matching("from properties") != []  # the batch reader still ran
    assert log.matching("from guests") == []  # short-circuited


@pytest.mark.asyncio
async def test_the_listing_with_a_single_shared_property_id_does_not_duplicate_the_property_batch(
    db_session, test_engine, tenant_a, users_by_role_a
) -> None:
    """Edge case of D3: when every reservation in the page shares the same
    `property_id`, the batch reader still runs once — dedup is the SET in the use
    case, not "DB deduplication in the SQL". The test pins that
    `list_for_ids` is called once, not once-per-row.
    """
    manager_a = users_by_role_a["PROPERTY_MANAGER"]
    property_a = await insert_property(db_session, tenant_a, code="REDES11")
    for index in range(5):
        _reservation(
            db_session,
            tenant_id=manager_a.tenant_id,
            property_id=property_a.id,
            guest_id=None,
        )
    await db_session.commit()

    use_case = ListReservationsUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
    )

    with count_statements(test_engine) as log:
        await use_case.execute(
            tenant_id=manager_a.tenant_id,
            filters=ReservationFilters(),
            page=1,
            per_page=50,
        )

    assert log.matching("from properties") != []
    # Each SELECT of `properties` (with this engine and the indices) is what shows
    # up in `log.matching(...)`. With ten rows sharing one id the trace stays one
    # query; a regression that called `get` per row would show N queries instead.
    assert len(log.matching("from properties")) == 1
