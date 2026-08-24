"""`PropertyRepository.list_for_ids` (`reservation-property-identity` D2, task 1.2).

The batch reader introduced so a reservations listing can resolve N properties in one
statement instead of one per row. Same shape as
`tests/cleaning/test_batch_reader.py`, the batch reader the cleaning domain already has —
and `GuestRepository.list_for_ids`, which the guests side has been using since
`dashboard-api`. Two copies of the same shape in two domains diverge in subtle ways
(both groups agreed on three things: no `IN ()`, neighbours absent not `None`, neighbours
and non-existent indistinguishable), so the parallel fixtures are deliberate.
"""

import uuid

import pytest

from app.properties.domain.entities import Property
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from tests.cleaning.conftest import insert_property
from tests.sql_counter import count_statements


def _reader(db_session) -> SqlAlchemyPropertyRepository:
    return SqlAlchemyPropertyRepository(db_session)


@pytest.mark.asyncio
async def test_an_empty_batch_returns_nothing_without_querying(
    db_session, test_engine, tenant_a
) -> None:
    """`== []` alone would pass for an implementation that emitted `IN ()`.

    Same gap the cleaning-side `test_an_empty_batch_returns_nothing_without_querying`
    catches; tracked there too so the two cannot drift.
    """
    with count_statements(test_engine) as log:
        found = await _reader(db_session).list_for_ids(tenant_a.id, [])

    assert found == []
    assert log.matching("from properties") == []


@pytest.mark.asyncio
async def test_it_returns_the_property_for_every_id_in_the_batch(
    db_session, tenant_a
) -> None:
    """Happy path: every requested id that resolves in the tenant comes back, mapped by id."""
    first = await insert_property(db_session, tenant_a, code="REDES11")
    second = await insert_property(db_session, tenant_a, code="PAJARITOS8")
    third = await insert_property(db_session, tenant_a, code="SILENCIO1")

    found = await _reader(db_session).list_for_ids(
        tenant_a.id, [first.id, second.id, third.id]
    )

    assert {property.id for property in found} == {first.id, second.id, third.id}
    assert all(isinstance(item, Property) for item in found)


@pytest.mark.asyncio
async def test_a_property_outside_the_batch_is_not_returned(
    db_session, tenant_a
) -> None:
    """A neighbour's property id is filtered at the SQL by `tenant_id`, never returned.

    R5.3 says a `reservation.property_id` pointing to another tenant's property must
    appear as `None` for the derived fields; the port here is what makes that promise
    doable, and it has to do it silently (R5.3 also forbids a 5xx for it).
    """
    mine = await insert_property(db_session, tenant_a, code="REDES11")
    theirs = await insert_property(db_session, tenant_a, code="PAJARITOS8")

    found = await _reader(db_session).list_for_ids(tenant_a.id, [mine.id])

    assert [property.id for property in found] == [mine.id]
    assert theirs.id not in {property.id for property in found}


@pytest.mark.asyncio
async def test_a_property_of_another_tenant_is_not_returned(
    db_session, tenant_a, tenant_b
) -> None:
    """The neighbouring tenant is the test the batch reader must serve (D7's twin).

    Passing `property_b.id` into a tenant-A batch is the case `dashboard-api`'s rule 1
    keeps in scope: a structurally-correct query that just filters `tenant_id` and lets
    the index drop the row, so a future widening to a JOIN cannot quietly expose it.
    """
    mine = await insert_property(db_session, tenant_a, code="REDES11")
    theirs = await insert_property(db_session, tenant_b, code="PAJARITOS8")

    found = await _reader(db_session).list_for_ids(tenant_a.id, [mine.id, theirs.id])

    assert [property.id for property in found] == [mine.id]


@pytest.mark.asyncio
async def test_a_nonexistent_property_id_is_just_absent(
    db_session, tenant_a
) -> None:
    """A missing id is indistinguishable from one of another tenant — by design.

    The caller keys by `id`, and `reservation.property_id` pointing at a row that does
    not exist at all is part of the same "FK did not resolve" case as pointing at another
    tenant's row. Lifting that into a separate return path would be the leak
    `PropertyNotFoundError` is designed to prevent in `get`.
    """
    mine = await insert_property(db_session, tenant_a, code="REDES11")
    fabricated = uuid.uuid4()

    found = await _reader(db_session).list_for_ids(tenant_a.id, [mine.id, fabricated])

    assert [property.id for property in found] == [mine.id]


@pytest.mark.asyncio
async def test_none_and_duplicate_ids_are_dropped_without_error(
    db_session, tenant_a
) -> None:
    """The two surprises a listing-row walk could produce: a `None` mid-iteration and
    the same id appearing in two rows. Both must arrive here cleanly, because
    `id = ANY(ARRAY[...])` with a NULL inside is its own kind of broken.

    A reservation with a `property_id` of `None` (none exists in the schema, but the
    use-case walk producing ids accepts `None` per row) would otherwise need a separate
    filter the port's contract removes.
    """
    first = await insert_property(db_session, tenant_a, code="REDES11")
    second = await insert_property(db_session, tenant_a, code="PAJARITOS8")

    found = await _reader(db_session).list_for_ids(
        tenant_a.id,
        [None, first.id, None, second.id, first.id],  # type: ignore[arg-type]
    )

    assert {property.id for property in found} == {first.id, second.id}
