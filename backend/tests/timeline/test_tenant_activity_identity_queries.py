"""`ListTenantActivityUseCase` emits a constant number of SELECTs (`dashboard-activity-feed`
design D5, R3.2).

Same shape as `tests/reservations/test_list_identity_queries.py`: the page query runs once,
and the DISTINCT `property_id`s of that page are resolved in ONE call to
`properties.list_for_ids`, never per row. Parametrized over two `per_page` values to pin that
the batch query count does not depend on how the page is sliced.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.i18n import Locale
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.timeline.application.use_cases import ListTenantActivityUseCase
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.repositories import TimelineFilters
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventReader
from tests.cleaning.conftest import insert_property
from tests.sql_counter import count_statements

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _event(*, tenant_id: uuid.UUID, property_id: uuid.UUID, created_at: datetime) -> TimelineEventModel:
    return TimelineEventModel(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        actor_type=TimelineActorType.SYSTEM,
        event_type=TimelineEventType.RESERVATION_IMPORTED,
        severity=TimelineSeverity.INFO,
        title="Stored title",
        created_at=created_at,
        metadata={"source": "beds24"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("per_page", [5, 50])
async def test_the_listing_with_ten_events_emits_a_constant_number_of_statements(
    db_session, test_engine, tenant_a, per_page
) -> None:
    """Ten events across three distinct properties of one tenant: the `properties` batch
    query runs EXACTLY ONCE per call, independent of `per_page`.
    """
    first_property = await insert_property(db_session, tenant_a, code="REDES11")
    second_property = await insert_property(db_session, tenant_a, code="PAJARITOS8")
    third_property = await insert_property(db_session, tenant_a, code="SILENCIO1")
    properties = [first_property, second_property, third_property]

    for index in range(10):
        db_session.add(
            _event(
                tenant_id=tenant_a.id,
                property_id=properties[index % 3].id,
                created_at=NOW,
            )
        )
    await db_session.commit()

    use_case = ListTenantActivityUseCase(
        properties=SqlAlchemyPropertyRepository(db_session),
        events=SqlAlchemyTimelineEventReader(db_session),
    )

    with count_statements(test_engine) as log:
        page = await use_case.execute(
            tenant_id=tenant_a.id,
            filters=TimelineFilters(),
            page=1,
            per_page=per_page,
            locale=Locale.EN,
        )

    assert len(page.entries) == min(10, per_page)
    assert page.total == 10
    assert len(log.matching("from properties")) == 1

    # R3.1: not just that a batch call happened, but that each entry carries the
    # identity of the property its own event belongs to — a wrong dict key or a
    # misaligned `zip` would still pass every assertion above.
    properties_by_id = {property.id: property for property in properties}
    for entry in page.entries:
        expected = properties_by_id[entry.property_id]
        assert entry.property_name == expected.name
        assert entry.property_internal_code == expected.internal_code


@pytest.mark.asyncio
async def test_the_listing_with_a_single_shared_property_id_still_queries_properties_once(
    db_session, test_engine, tenant_a
) -> None:
    """A page whose rows all share ONE `property_id` still queries `properties` exactly
    once — not zero (the id set is non-empty even with a single member) and not
    once-per-row.
    """
    property_a = await insert_property(db_session, tenant_a, code="REDES11")
    for _ in range(5):
        db_session.add(
            _event(tenant_id=tenant_a.id, property_id=property_a.id, created_at=NOW)
        )
    await db_session.commit()

    use_case = ListTenantActivityUseCase(
        properties=SqlAlchemyPropertyRepository(db_session),
        events=SqlAlchemyTimelineEventReader(db_session),
    )

    with count_statements(test_engine) as log:
        page = await use_case.execute(
            tenant_id=tenant_a.id,
            filters=TimelineFilters(),
            page=1,
            per_page=50,
            locale=Locale.EN,
        )

    assert len(page.entries) == 5
    assert len(log.matching("from properties")) == 1


@pytest.mark.asyncio
async def test_the_locale_argument_changes_the_title_but_not_the_description(
    db_session, tenant_a
) -> None:
    """R4.2: `ListTenantActivityUseCase.execute` forwards `locale` to `rendering.render()`
    — no test in this section's scope called it with more than one locale or looked at
    `entry.title`/`entry.description`, so a future refactor that hardcoded a locale or
    post-processed `description` would slip through untested.

    `CLEANING_COMPLETED` is the type `test_rendering.py::test_the_two_locales_differ_where_the_language_differs`
    already uses for its ES/EN title assertions, and its template is static (no metadata
    placeholder), which keeps this test about locale wiring and not about rendering itself.
    """
    property_a = await insert_property(db_session, tenant_a, code="REDES11")
    stored_description = "Cleaner confirmed every checklist item."
    db_session.add(
        TimelineEventModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            actor_type=TimelineActorType.SYSTEM,
            event_type=TimelineEventType.CLEANING_COMPLETED,
            severity=TimelineSeverity.INFO,
            title="Stored title",
            description=stored_description,
            created_at=NOW,
        )
    )
    await db_session.commit()

    use_case = ListTenantActivityUseCase(
        properties=SqlAlchemyPropertyRepository(db_session),
        events=SqlAlchemyTimelineEventReader(db_session),
    )

    es_page = await use_case.execute(
        tenant_id=tenant_a.id, filters=TimelineFilters(), page=1, per_page=20, locale=Locale.ES
    )
    en_page = await use_case.execute(
        tenant_id=tenant_a.id, filters=TimelineFilters(), page=1, per_page=20, locale=Locale.EN
    )

    assert len(es_page.entries) == 1
    assert len(en_page.entries) == 1
    es_entry, en_entry = es_page.entries[0], en_page.entries[0]
    assert es_entry.title == "Limpieza completada"
    assert en_entry.title == "Cleaning completed"
    assert es_entry.title != en_entry.title
    assert es_entry.description == stored_description
    assert en_entry.description == stored_description
