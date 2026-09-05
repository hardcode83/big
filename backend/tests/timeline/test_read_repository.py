"""`SqlAlchemyTimelineEventReader` (`dashboard-api` R4, design D8, task 2.3).

The read side of `timeline_events`: order, filters, pagination and tenant isolation.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.repositories import TimelineFilters
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventReader
from tests.sql_counter import count_statements

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


async def _tenant_and_property(db_session, name: str) -> tuple[TenantModel, PropertyModel]:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(tenant_id=tenant.id, name=f"{name} flat", internal_code=f"{name}-1")
    db_session.add(prop)
    await db_session.flush()
    return tenant, prop


async def _add_event(
    db_session,
    tenant: TenantModel,
    prop: PropertyModel,
    *,
    created_at: datetime,
    event_id: uuid.UUID | None = None,
    event_type: TimelineEventType = TimelineEventType.RESERVATION_IMPORTED,
    severity: TimelineSeverity = TimelineSeverity.INFO,
    actor_type: TimelineActorType = TimelineActorType.SYSTEM,
) -> TimelineEventModel:
    model = TimelineEventModel(
        id=event_id or uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        actor_type=actor_type,
        event_type=event_type,
        severity=severity,
        title="Stored title",
        created_at=created_at,
    )
    db_session.add(model)
    await db_session.flush()
    return model


def _reader(db_session) -> SqlAlchemyTimelineEventReader:
    return SqlAlchemyTimelineEventReader(db_session)


async def _list(db_session, tenant, prop, *, filters=None, page=1, per_page=20):
    return await _reader(db_session).list_for_property(
        tenant.id, prop.id, filters=filters or TimelineFilters(), page=page, per_page=per_page
    )


async def _list_tenant(db_session, tenant, *, filters=None, page=1, per_page=20):
    return await _reader(db_session).list_for_tenant(
        tenant.id, filters=filters or TimelineFilters(), page=page, per_page=per_page
    )


# --- order (R4.1) ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_come_back_newest_first(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    oldest = await _add_event(db_session, tenant, prop, created_at=NOW - timedelta(hours=2))
    middle = await _add_event(db_session, tenant, prop, created_at=NOW - timedelta(hours=1))
    newest = await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list(db_session, tenant, prop)

    assert [item.id for item in page.items] == [newest.id, middle.id, oldest.id]
    assert page.total == 3


@pytest.mark.asyncio
async def test_events_sharing_an_instant_break_the_tie_by_id_descending(db_session) -> None:
    """Design D8. The adapter writes `created_at` from the event, so every event of one
    business operation shares it — the tiebreaker is what keeps the order total."""
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    low = uuid.UUID("00000000-0000-4000-8000-000000000001")
    high = uuid.UUID("ffffffff-0000-4000-8000-000000000002")
    await _add_event(db_session, tenant, prop, created_at=NOW, event_id=low)
    await _add_event(db_session, tenant, prop, created_at=NOW, event_id=high)

    page = await _list(db_session, tenant, prop)

    assert [item.id for item in page.items] == [high, low]


# --- pagination (R4.1) -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_paging_through_identical_timestamps_neither_repeats_nor_omits(
    db_session,
) -> None:
    """The failure R4.1 names, reproduced at the shape that produces it: ten events at the
    very same instant, walked one page at a time."""
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    created = [
        (await _add_event(db_session, tenant, prop, created_at=NOW)).id for _ in range(10)
    ]

    seen: list[uuid.UUID] = []
    for page_number in (1, 2, 3, 4):
        page = await _list(db_session, tenant, prop, page=page_number, per_page=3)
        seen.extend(item.id for item in page.items)
        assert page.total == 10

    assert len(seen) == 10, "a page repeated or omitted an entry"
    assert set(seen) == set(created)
    assert len(set(seen)) == 10


@pytest.mark.asyncio
async def test_a_page_beyond_the_end_is_empty_but_still_reports_the_total(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list(db_session, tenant, prop, page=5, per_page=20)

    assert page.items == ()
    assert page.total == 1


# --- filters (R4.2) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_event_type_filter_narrows_the_set_and_the_total(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    wanted = await _add_event(
        db_session, tenant, prop, created_at=NOW, event_type=TimelineEventType.CLEANING_COMPLETED
    )
    await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list(
        db_session,
        tenant,
        prop,
        filters=TimelineFilters(event_type=TimelineEventType.CLEANING_COMPLETED),
    )

    assert [item.id for item in page.items] == [wanted.id]
    assert page.total == 1, "the total must count the filtered set, not the whole property"


@pytest.mark.asyncio
async def test_the_severity_filter_narrows_the_set(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    wanted = await _add_event(
        db_session, tenant, prop, created_at=NOW, severity=TimelineSeverity.CRITICAL
    )
    await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list(
        db_session, tenant, prop, filters=TimelineFilters(severity=TimelineSeverity.CRITICAL)
    )

    assert [item.id for item in page.items] == [wanted.id]


@pytest.mark.asyncio
async def test_the_actor_type_filter_narrows_the_set(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    wanted = await _add_event(
        db_session, tenant, prop, created_at=NOW, actor_type=TimelineActorType.GUEST
    )
    await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list(
        db_session, tenant, prop, filters=TimelineFilters(actor_type=TimelineActorType.GUEST)
    )

    assert [item.id for item in page.items] == [wanted.id]


@pytest.mark.asyncio
async def test_the_date_bounds_are_inclusive_on_both_ends(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    before = await _add_event(db_session, tenant, prop, created_at=NOW - timedelta(days=2))
    on_lower = await _add_event(db_session, tenant, prop, created_at=NOW - timedelta(days=1))
    on_upper = await _add_event(db_session, tenant, prop, created_at=NOW)
    after = await _add_event(db_session, tenant, prop, created_at=NOW + timedelta(days=1))

    page = await _list(
        db_session,
        tenant,
        prop,
        filters=TimelineFilters(occurred_from=NOW - timedelta(days=1), occurred_to=NOW),
    )

    assert {item.id for item in page.items} == {on_lower.id, on_upper.id}
    assert before.id not in {item.id for item in page.items}
    assert after.id not in {item.id for item in page.items}


@pytest.mark.asyncio
async def test_the_filters_combine_with_and(db_session) -> None:
    """R4.2: "SHALL combinarlos con AND" — matching only some of them is not a match."""
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    wanted = await _add_event(
        db_session,
        tenant,
        prop,
        created_at=NOW,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
        actor_type=TimelineActorType.GUEST,
    )
    # Right type and severity, wrong actor.
    await _add_event(
        db_session,
        tenant,
        prop,
        created_at=NOW,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
        actor_type=TimelineActorType.SYSTEM,
    )
    # Right type and actor, wrong severity.
    await _add_event(
        db_session,
        tenant,
        prop,
        created_at=NOW,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.INFO,
        actor_type=TimelineActorType.GUEST,
    )

    page = await _list(
        db_session,
        tenant,
        prop,
        filters=TimelineFilters(
            event_type=TimelineEventType.INCIDENT_CREATED,
            severity=TimelineSeverity.CRITICAL,
            actor_type=TimelineActorType.GUEST,
            occurred_from=NOW - timedelta(minutes=1),
            occurred_to=NOW + timedelta(minutes=1),
        ),
    )

    assert [item.id for item in page.items] == [wanted.id]
    assert page.total == 1


# --- tenant isolation (DoD §28.18) ------------------------------------------------------


@pytest.mark.asyncio
async def test_it_never_returns_an_event_of_another_tenant(db_session) -> None:
    tenant_a, prop_a = await _tenant_and_property(db_session, "TenantA")
    tenant_b, prop_b = await _tenant_and_property(db_session, "TenantB")
    mine = await _add_event(db_session, tenant_a, prop_a, created_at=NOW)
    await _add_event(db_session, tenant_b, prop_b, created_at=NOW)

    page = await _list(db_session, tenant_a, prop_a)

    assert [item.id for item in page.items] == [mine.id]
    assert page.total == 1


@pytest.mark.asyncio
async def test_a_property_of_another_tenant_reads_as_empty_not_as_its_events(
    db_session,
) -> None:
    """Design D11: the repository returns nothing outside the tenant, which is what lets
    the route answer `404` rather than `403` without a check of its own."""
    tenant_a, _ = await _tenant_and_property(db_session, "TenantA")
    tenant_b, prop_b = await _tenant_and_property(db_session, "TenantB")
    await _add_event(db_session, tenant_b, prop_b, created_at=NOW)

    page = await _reader(db_session).list_for_property(
        tenant_a.id, prop_b.id, filters=TimelineFilters(), page=1, per_page=20
    )

    assert page.items == ()
    assert page.total == 0


@pytest.mark.asyncio
async def test_another_property_of_the_same_tenant_is_not_mixed_in(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    other = PropertyModel(tenant_id=tenant.id, name="Second flat", internal_code="A-2")
    db_session.add(other)
    await db_session.flush()
    mine = await _add_event(db_session, tenant, prop, created_at=NOW)
    await _add_event(db_session, tenant, other, created_at=NOW)

    page = await _list(db_session, tenant, prop)

    assert [item.id for item in page.items] == [mine.id]


# --- list_for_tenant (`dashboard-activity-feed` R1.1, R1.2, R1.3, R2.1, R4.3) -----------


@pytest.mark.asyncio
async def test_list_for_tenant_merges_several_properties_newest_first_with_id_tiebreak(
    db_session,
) -> None:
    tenant, one = await _tenant_and_property(db_session, "TenantA")
    two = PropertyModel(tenant_id=tenant.id, name="Second", internal_code="A-2")
    db_session.add(two)
    await db_session.flush()
    low = uuid.UUID("00000000-0000-4000-8000-000000000001")
    high = uuid.UUID("ffffffff-0000-4000-8000-000000000002")
    oldest = await _add_event(db_session, tenant, one, created_at=NOW - timedelta(hours=1))
    tied_low = await _add_event(db_session, tenant, two, created_at=NOW, event_id=low)
    tied_high = await _add_event(db_session, tenant, one, created_at=NOW, event_id=high)

    page = await _list_tenant(db_session, tenant)

    assert [item.id for item in page.items] == [tied_high.id, tied_low.id, oldest.id]
    assert page.total == 3


@pytest.mark.asyncio
async def test_list_for_tenant_paging_through_identical_timestamps_neither_repeats_nor_omits(
    db_session,
) -> None:
    """Same failure mode `test_paging_through_identical_timestamps_neither_repeats_nor_omits`
    reproduces for `list_for_property`, here spread across several properties of one tenant."""
    tenant, one = await _tenant_and_property(db_session, "TenantA")
    two = PropertyModel(tenant_id=tenant.id, name="Second", internal_code="A-2")
    db_session.add(two)
    await db_session.flush()
    created = [
        (await _add_event(db_session, tenant, one if i % 2 == 0 else two, created_at=NOW)).id
        for i in range(10)
    ]

    seen: list[uuid.UUID] = []
    for page_number in (1, 2, 3, 4):
        page = await _list_tenant(db_session, tenant, page=page_number, per_page=3)
        seen.extend(item.id for item in page.items)
        assert page.total == 10

    assert len(seen) == 10, "a page repeated or omitted an entry"
    assert set(seen) == set(created)
    assert len(set(seen)) == 10


@pytest.mark.asyncio
async def test_list_for_tenant_event_type_filter_narrows_the_set_and_the_total(
    db_session,
) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    wanted = await _add_event(
        db_session, tenant, prop, created_at=NOW, event_type=TimelineEventType.CLEANING_COMPLETED
    )
    await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list_tenant(
        db_session,
        tenant,
        filters=TimelineFilters(event_type=TimelineEventType.CLEANING_COMPLETED),
    )

    assert [item.id for item in page.items] == [wanted.id]
    assert page.total == 1, "the total must count the filtered set, not the whole tenant"


@pytest.mark.asyncio
async def test_list_for_tenant_severity_filter_narrows_the_set(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    wanted = await _add_event(
        db_session, tenant, prop, created_at=NOW, severity=TimelineSeverity.CRITICAL
    )
    await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list_tenant(
        db_session, tenant, filters=TimelineFilters(severity=TimelineSeverity.CRITICAL)
    )

    assert [item.id for item in page.items] == [wanted.id]


@pytest.mark.asyncio
async def test_list_for_tenant_actor_type_filter_narrows_the_set(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    wanted = await _add_event(
        db_session, tenant, prop, created_at=NOW, actor_type=TimelineActorType.GUEST
    )
    await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list_tenant(
        db_session, tenant, filters=TimelineFilters(actor_type=TimelineActorType.GUEST)
    )

    assert [item.id for item in page.items] == [wanted.id]


@pytest.mark.asyncio
async def test_list_for_tenant_date_bounds_are_inclusive_on_both_ends(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    before = await _add_event(db_session, tenant, prop, created_at=NOW - timedelta(days=2))
    on_lower = await _add_event(db_session, tenant, prop, created_at=NOW - timedelta(days=1))
    on_upper = await _add_event(db_session, tenant, prop, created_at=NOW)
    after = await _add_event(db_session, tenant, prop, created_at=NOW + timedelta(days=1))

    page = await _list_tenant(
        db_session,
        tenant,
        filters=TimelineFilters(occurred_from=NOW - timedelta(days=1), occurred_to=NOW),
    )

    assert {item.id for item in page.items} == {on_lower.id, on_upper.id}
    assert before.id not in {item.id for item in page.items}
    assert after.id not in {item.id for item in page.items}


@pytest.mark.asyncio
async def test_list_for_tenant_filters_combine_with_and(db_session) -> None:
    """R2.1: the same AND-combined contract `list_for_property` gives — matching only some
    of the filters is not a match."""
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    wanted = await _add_event(
        db_session,
        tenant,
        prop,
        created_at=NOW,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
        actor_type=TimelineActorType.GUEST,
    )
    # Right type and severity, wrong actor.
    await _add_event(
        db_session,
        tenant,
        prop,
        created_at=NOW,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
        actor_type=TimelineActorType.SYSTEM,
    )
    # Right type and actor, wrong severity.
    await _add_event(
        db_session,
        tenant,
        prop,
        created_at=NOW,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.INFO,
        actor_type=TimelineActorType.GUEST,
    )

    page = await _list_tenant(
        db_session,
        tenant,
        filters=TimelineFilters(
            event_type=TimelineEventType.INCIDENT_CREATED,
            severity=TimelineSeverity.CRITICAL,
            actor_type=TimelineActorType.GUEST,
            occurred_from=NOW - timedelta(minutes=1),
            occurred_to=NOW + timedelta(minutes=1),
        ),
    )

    assert [item.id for item in page.items] == [wanted.id]
    assert page.total == 1


@pytest.mark.asyncio
async def test_list_for_tenant_a_single_date_bound_alone_still_filters(db_session) -> None:
    """R2.1: the AND-combination tests above only ever supplied `occurred_from` and
    `occurred_to` together. A single bound with the other left `None` is a distinct code
    path — this confirms it still excludes events on the wrong side of the one bound
    given, and still includes the boundary instant itself."""
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    before = await _add_event(db_session, tenant, prop, created_at=NOW - timedelta(days=2))
    on_bound = await _add_event(db_session, tenant, prop, created_at=NOW - timedelta(days=1))
    after = await _add_event(db_session, tenant, prop, created_at=NOW + timedelta(days=1))

    from_only = await _list_tenant(
        db_session, tenant, filters=TimelineFilters(occurred_from=NOW - timedelta(days=1))
    )
    assert {item.id for item in from_only.items} == {on_bound.id, after.id}
    assert before.id not in {item.id for item in from_only.items}

    to_only = await _list_tenant(
        db_session, tenant, filters=TimelineFilters(occurred_to=NOW - timedelta(days=1))
    )
    assert {item.id for item in to_only.items} == {before.id, on_bound.id}
    assert after.id not in {item.id for item in to_only.items}


@pytest.mark.asyncio
async def test_list_for_tenant_never_returns_a_neighbour_tenants_events(db_session) -> None:
    """DoD §28.18. The neighbour's event shares `event_type` and `severity` with the one
    under test, so isolation being real (tenant_id in the WHERE) rather than accidental
    (the values happening to differ) is what this actually proves."""
    tenant_a, prop_a = await _tenant_and_property(db_session, "TenantA")
    tenant_b, prop_b = await _tenant_and_property(db_session, "TenantB")
    mine = await _add_event(
        db_session,
        tenant_a,
        prop_a,
        created_at=NOW,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
    )
    await _add_event(
        db_session,
        tenant_b,
        prop_b,
        created_at=NOW,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
    )

    page = await _list_tenant(db_session, tenant_a)

    assert [item.id for item in page.items] == [mine.id]
    assert page.total == 1


@pytest.mark.asyncio
async def test_list_for_tenant_with_no_properties_is_empty(db_session) -> None:
    tenant = TenantModel(name="Empty", billing_email="empty@example.com")
    db_session.add(tenant)
    await db_session.flush()

    page = await _list_tenant(db_session, tenant)

    assert page.items == ()
    assert page.total == 0


@pytest.mark.asyncio
async def test_list_for_tenant_with_properties_but_no_events_is_empty(db_session) -> None:
    tenant, _prop = await _tenant_and_property(db_session, "TenantA")

    page = await _list_tenant(db_session, tenant)

    assert page.items == ()
    assert page.total == 0


# --- last_for_properties (R1.7, task 4.4) ------------------------------------------------


@pytest.mark.asyncio
async def test_the_batch_reader_returns_nothing_for_an_empty_batch(
    db_session, test_engine
) -> None:
    tenant, _ = await _tenant_and_property(db_session, "TenantA")

    with count_statements(test_engine) as log:
        found = await _reader(db_session).last_for_properties(tenant.id, [])

    assert found == {}
    assert log.matching("timeline_events") == [], "an empty batch must not query"


@pytest.mark.asyncio
async def test_the_batch_reader_returns_the_newest_event_of_each_property(
    db_session,
) -> None:
    tenant, one = await _tenant_and_property(db_session, "TenantA")
    two = PropertyModel(tenant_id=tenant.id, name="Second", internal_code="A-2")
    db_session.add(two)
    await db_session.flush()
    await _add_event(db_session, tenant, one, created_at=NOW - timedelta(days=1))
    newest_one = await _add_event(db_session, tenant, one, created_at=NOW)
    newest_two = await _add_event(db_session, tenant, two, created_at=NOW - timedelta(hours=3))
    await _add_event(db_session, tenant, two, created_at=NOW - timedelta(days=5))

    found = await _reader(db_session).last_for_properties(tenant.id, [one.id, two.id])

    assert set(found) == {one.id, two.id}
    assert found[one.id].id == newest_one.id
    assert found[two.id].id == newest_two.id


@pytest.mark.asyncio
async def test_a_property_with_no_events_is_absent_rather_than_mapped_to_none(
    db_session,
) -> None:
    tenant, one = await _tenant_and_property(db_session, "TenantA")
    quiet = PropertyModel(tenant_id=tenant.id, name="Quiet", internal_code="A-2")
    db_session.add(quiet)
    await db_session.flush()
    await _add_event(db_session, tenant, one, created_at=NOW)

    found = await _reader(db_session).last_for_properties(tenant.id, [one.id, quiet.id])

    assert set(found) == {one.id}
    assert quiet.id not in found


@pytest.mark.asyncio
async def test_the_batch_reader_breaks_a_shared_instant_by_id(db_session) -> None:
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    low = uuid.UUID("00000000-0000-4000-8000-000000000001")
    high = uuid.UUID("ffffffff-0000-4000-8000-000000000002")
    await _add_event(db_session, tenant, prop, created_at=NOW, event_id=high)
    await _add_event(db_session, tenant, prop, created_at=NOW, event_id=low)

    found = await _reader(db_session).last_for_properties(tenant.id, [prop.id])

    assert found[prop.id].id == high


@pytest.mark.asyncio
async def test_the_batch_reader_never_crosses_a_tenant_boundary(db_session) -> None:
    """DoD §28.18 — the neighbour's property id is passed in explicitly, so the tenant
    argument is what excludes it rather than the caller happening not to ask."""
    tenant_a, mine = await _tenant_and_property(db_session, "TenantA")
    tenant_b, theirs = await _tenant_and_property(db_session, "TenantB")
    await _add_event(db_session, tenant_a, mine, created_at=NOW)
    await _add_event(db_session, tenant_b, theirs, created_at=NOW)

    found = await _reader(db_session).last_for_properties(tenant_a.id, [mine.id, theirs.id])

    assert set(found) == {mine.id}


@pytest.mark.asyncio
@pytest.mark.parametrize("property_count", [2, 10])
async def test_the_batch_reader_emits_one_statement_whatever_the_batch_size(
    db_session, test_engine, property_count: int
) -> None:
    """R1.7, and the reason the design calls this an assertion rather than a metric: the
    N+1 version of this code is syntactically identical to the correct one.

    The count is fixed at one and does not grow with the batch — verified at two sizes, so
    a constant that happened to match one of them cannot pass.
    """
    tenant, first = await _tenant_and_property(db_session, "TenantA")
    properties = [first]
    for index in range(property_count - 1):
        extra = PropertyModel(
            tenant_id=tenant.id, name=f"Flat {index}", internal_code=f"A-{index}"
        )
        db_session.add(extra)
        await db_session.flush()
        properties.append(extra)
    for prop in properties:
        await _add_event(db_session, tenant, prop, created_at=NOW)

    with count_statements(test_engine) as log:
        found = await _reader(db_session).last_for_properties(
            tenant.id, [prop.id for prop in properties]
        )

    assert len(found) == property_count
    assert len(log.matching("timeline_events")) == 1, (
        f"{property_count} properties took {len(log.matching('timeline_events'))} "
        "statements; the batch reader must stay at one"
    )


# --- the entity it returns --------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_returns_domain_entities_with_metadata_defaulted_to_a_dict(
    db_session,
) -> None:
    """`metadata` is nullable in the column and a `dict` in the entity; the renderer
    iterates it, so `None` would be a `TypeError` on the read path."""
    tenant, prop = await _tenant_and_property(db_session, "TenantA")
    await _add_event(db_session, tenant, prop, created_at=NOW)

    page = await _list(db_session, tenant, prop)

    assert page.items[0].metadata == {}
    assert page.items[0].title == "Stored title"
    assert page.items[0].tenant_id == tenant.id
