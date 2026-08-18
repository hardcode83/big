"""Integration tests for the pricing adapters (R1.2, R1.7, R4.2, R5.1; design D9).

Against real Postgres, per `steering/backend-architecture.md`: "`infrastructure/`:
integration tests contra Postgres/Redis reales".
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.pricing.domain.enums import PriceRecommendationStatus
from app.pricing.domain.exceptions import PricingValidationError
from app.pricing.domain.repositories import (
    PriceRecommendationFilters,
    PricingRuleFilters,
)
from app.pricing.infrastructure.models import PriceRecommendationModel, PricingRuleModel
from tests.pricing.conftest import NOW, TODAY, horizon, make_recommendation, make_rule

pytestmark = pytest.mark.asyncio

S = PriceRecommendationStatus


# --- PricingRuleRepository ------------------------------------------------------------


async def test_a_rule_survives_a_round_trip(rules, world) -> None:
    rule = make_rule(
        world.tenant.id,
        property_id=world.property.id,
        weekday_modifiers={"saturday": 20},
        event_rules=[{"holidays": "ES_NATIONAL", "modifier_pct": 15}],
    )

    await rules.add(world.tenant.id, rule)
    stored = await rules.get(world.tenant.id, rule.id)

    assert stored is not None
    assert stored.name == rule.name
    assert stored.property_id == world.property.id
    assert stored.base_price == Decimal("100.00")
    assert stored.weekday_modifiers == {"saturday": 20}
    assert stored.event_rules == [{"holidays": "ES_NATIONAL", "modifier_pct": 15}]


async def test_an_unknown_rule_is_none(rules, world) -> None:
    assert await rules.get(world.tenant.id, uuid.uuid4()) is None


async def test_update_persists_only_the_mutable_columns(rules, world, db_session) -> None:
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    later = NOW + timedelta(hours=1)

    rule.update_details({"name": "Renamed", "active": False}, now=later)
    await rules.update(world.tenant.id, rule)

    stored = await rules.get(world.tenant.id, rule.id)
    assert stored is not None
    assert stored.name == "Renamed"
    assert stored.active is False
    assert stored.created_at == rule.created_at  # untouched by the UPDATE
    assert stored.tenant_id == world.tenant.id


async def test_list_paginates_and_reports_the_total(rules, world) -> None:
    for index in range(5):
        await rules.add(world.tenant.id, make_rule(world.tenant.id, name=f"rule {index}"))

    first = await rules.list(world.tenant.id, PricingRuleFilters(), page=1, per_page=2)
    second = await rules.list(world.tenant.id, PricingRuleFilters(), page=2, per_page=2)

    assert first.total == 5
    assert len(first.items) == 2
    assert len(second.items) == 2
    assert {rule.id for rule in first.items}.isdisjoint({rule.id for rule in second.items})


async def test_list_filters_by_property(rules, world) -> None:
    mine = make_rule(world.tenant.id, property_id=world.property.id)
    other = make_rule(world.tenant.id, property_id=world.second_property.id)
    tenant_wide = make_rule(world.tenant.id, property_id=None)
    for rule in (mine, other, tenant_wide):
        await rules.add(world.tenant.id, rule)

    page = await rules.list(
        world.tenant.id,
        PricingRuleFilters(property_id=world.property.id),
        page=1,
        per_page=50,
    )

    assert [rule.id for rule in page.items] == [mine.id]


async def test_list_can_ask_for_the_tenant_wide_rules(rules, world) -> None:
    """`property_id=None` means "no filter", so the null case needs its own flag."""
    tenant_wide = make_rule(world.tenant.id, property_id=None)
    await rules.add(world.tenant.id, tenant_wide)
    await rules.add(world.tenant.id, make_rule(world.tenant.id, property_id=world.property.id))

    page = await rules.list(
        world.tenant.id, PricingRuleFilters(property_id_is_null=True), page=1, per_page=50
    )

    assert [rule.id for rule in page.items] == [tenant_wide.id]


@pytest.mark.parametrize("active", [True, False])
async def test_list_filters_by_active(rules, world, active: bool) -> None:
    live = make_rule(world.tenant.id, name="live", active=True)
    retired = make_rule(world.tenant.id, name="retired", active=False)
    for rule in (live, retired):
        await rules.add(world.tenant.id, rule)

    page = await rules.list(
        world.tenant.id, PricingRuleFilters(active=active), page=1, per_page=50
    )

    assert [rule.name for rule in page.items] == ["live" if active else "retired"]


async def test_list_active_returns_only_active_rules(rules, world) -> None:
    live = make_rule(world.tenant.id, name="live", active=True)
    retired = make_rule(world.tenant.id, name="retired", active=False)
    for rule in (live, retired):
        await rules.add(world.tenant.id, rule)

    assert [rule.id for rule in await rules.list_active(world.tenant.id)] == [live.id]


@pytest.mark.parametrize(("page", "per_page"), [(0, 10), (1, 0), (-1, 10)])
async def test_a_non_positive_page_is_a_validation_error_not_a_500(
    rules, world, page: int, per_page: int
) -> None:
    """A negative OFFSET is a `DBAPIError`; a bad query parameter deserves a 422."""
    with pytest.raises(PricingValidationError):
        await rules.list(world.tenant.id, PricingRuleFilters(), page=page, per_page=per_page)


# --- PriceRecommendationRepository ----------------------------------------------------


async def test_a_recommendation_survives_a_round_trip(
    rules, recommendations, world
) -> None:
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    recommendation = make_recommendation(world.tenant.id, world.property.id, rule.id)

    await recommendations.upsert_many(world.tenant.id, [recommendation])
    stored = await recommendations.get(world.tenant.id, recommendation.id)

    assert stored is not None
    assert stored.recommended_price == Decimal("120.00")
    assert stored.status is S.RECOMMENDED
    assert stored.confidence == Decimal("1.00")
    assert stored.current_price is None  # R5.5: Mode 1 never calls the PMS


async def test_upsert_is_idempotent_over_the_unique(rules, recommendations, world) -> None:
    """R4.2: the second run must update, not fail against `(property_id, date)`."""
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    first = horizon(world.tenant.id, world.property.id, rule.id, days=10)

    outcome_one = await recommendations.upsert_many(world.tenant.id, first)
    # A second run builds fresh entities — new ids, same (property_id, date) pairs.
    second = horizon(
        world.tenant.id, world.property.id, rule.id, days=10, price=Decimal("130.00")
    )
    outcome_two = await recommendations.upsert_many(world.tenant.id, second)

    assert (outcome_one.created, outcome_one.updated) == (10, 0)
    assert (outcome_two.created, outcome_two.updated) == (0, 10)

    page = await recommendations.list(
        world.tenant.id, PriceRecommendationFilters(), page=1, per_page=100
    )
    assert page.total == 10  # not 20
    assert {row.recommended_price for row in page.items} == {Decimal("130.00")}


async def test_upsert_keeps_the_original_row_identity(
    rules, recommendations, world
) -> None:
    """D9 rejects delete-and-reinsert: the manager may already be looking at that id."""
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    original = make_recommendation(world.tenant.id, world.property.id, rule.id)
    await recommendations.upsert_many(world.tenant.id, [original])

    replacement = make_recommendation(
        world.tenant.id, world.property.id, rule.id, price=Decimal("99.00")
    )
    await recommendations.upsert_many(world.tenant.id, [replacement])

    assert await recommendations.get(world.tenant.id, replacement.id) is None
    kept = await recommendations.get(world.tenant.id, original.id)
    assert kept is not None
    assert kept.recommended_price == Decimal("99.00")


async def test_upsert_of_nothing_writes_nothing(recommendations, world) -> None:
    outcome = await recommendations.upsert_many(world.tenant.id, [])

    assert (outcome.created, outcome.updated, outcome.preserved) == (0, 0, 0)


async def test_the_same_property_day_twice_in_one_call_is_a_validation_error(
    rules, recommendations, world
) -> None:
    """Postgres raises `cannot affect row a second time` — an untranslated 500.

    Answered like a bad page rather than left to the driver. Raised by the section-3 QA
    panel.
    """
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    twice = [
        make_recommendation(world.tenant.id, world.property.id, rule.id),
        make_recommendation(world.tenant.id, world.property.id, rule.id),
    ]

    with pytest.raises(PricingValidationError) as caught:
        await recommendations.upsert_many(world.tenant.id, twice)

    assert caught.value.field == "recommendations"


async def test_the_stored_explanation_is_exactly_what_was_rendered(
    rules, recommendations, world
) -> None:
    """Sink 14 of rule 11 gets its test at its first writer.

    `steering/security.md`: "El contrato lo hereda el change que primero escribe en cada
    una, **con su propio test**." Raised by the section-3 security panel.
    """
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    rendered = "Base price 100.00 EUR. Weekday (saturday) +20.00% -> 120.00. Recommended 120.00 EUR."
    recommendation = make_recommendation(
        world.tenant.id, world.property.id, rule.id, explanation=rendered
    )

    await recommendations.upsert_many(world.tenant.id, [recommendation])
    stored = await recommendations.get(world.tenant.id, recommendation.id)

    assert stored is not None
    assert stored.explanation == rendered


async def test_the_explanation_is_rewritten_on_a_regeneration(
    rules, recommendations, world
) -> None:
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    first = make_recommendation(
        world.tenant.id, world.property.id, rule.id, explanation="first"
    )
    await recommendations.upsert_many(world.tenant.id, [first])

    await recommendations.upsert_many(
        world.tenant.id,
        [make_recommendation(world.tenant.id, world.property.id, rule.id,
                             explanation="second")],
    )

    stored = await recommendations.get(world.tenant.id, first.id)
    assert stored is not None
    assert stored.explanation == "second"


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
async def test_a_filter_cannot_ask_for_a_property_and_for_no_property() -> None:
    """The two together have no coherent meaning; silent precedence answered the wrong
    question. Raised by the section-3 QA panel.

    `async` only so the module-level `asyncio` mark applies cleanly; it awaits nothing.
    """
    with pytest.raises(PricingValidationError) as caught:
        PricingRuleFilters(property_id=uuid.uuid4(), property_id_is_null=True)

    assert caught.value.field == "property_id"


async def test_list_for_property_range_is_inclusive_of_both_bounds(
    rules, recommendations, world
) -> None:
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    await recommendations.upsert_many(
        world.tenant.id, horizon(world.tenant.id, world.property.id, rule.id, days=10)
    )

    found = await recommendations.list_for_property_range(
        world.tenant.id, world.property.id, TODAY, TODAY + timedelta(days=9)
    )

    assert len(found) == 10
    assert [row.date for row in found] == sorted(row.date for row in found)


async def test_list_for_property_range_does_not_cross_properties(
    rules, recommendations, world
) -> None:
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    await recommendations.upsert_many(
        world.tenant.id,
        [
            make_recommendation(world.tenant.id, world.property.id, rule.id),
            make_recommendation(world.tenant.id, world.second_property.id, rule.id),
        ],
    )

    found = await recommendations.list_for_property_range(
        world.tenant.id, world.property.id, TODAY, TODAY + timedelta(days=1)
    )

    assert [row.property_id for row in found] == [world.property.id]


async def test_recommendation_list_filters(rules, recommendations, world) -> None:
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    rows = horizon(world.tenant.id, world.property.id, rule.id, days=5)
    other_property = make_recommendation(
        world.tenant.id, world.second_property.id, rule.id
    )
    await recommendations.upsert_many(world.tenant.id, [*rows, other_property])

    by_property = await recommendations.list(
        world.tenant.id,
        PriceRecommendationFilters(property_id=world.property.id),
        page=1,
        per_page=50,
    )
    by_dates = await recommendations.list(
        world.tenant.id,
        PriceRecommendationFilters(
            property_id=world.property.id,
            date_from=TODAY + timedelta(days=1),
            date_to=TODAY + timedelta(days=3),
        ),
        page=1,
        per_page=50,
    )

    assert by_property.total == 5
    assert by_dates.total == 3


async def test_recommendation_list_filters_by_status(
    rules, recommendations, world
) -> None:
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    rows = horizon(world.tenant.id, world.property.id, rule.id, days=3)
    await recommendations.upsert_many(world.tenant.id, rows)
    rows[0].decide(S.APPROVED)
    await recommendations.update(world.tenant.id, rows[0])

    approved = await recommendations.list(
        world.tenant.id, PriceRecommendationFilters(status=S.APPROVED), page=1, per_page=50
    )

    assert [row.id for row in approved.items] == [rows[0].id]


async def test_update_persists_only_the_status(rules, recommendations, world) -> None:
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    recommendation = make_recommendation(world.tenant.id, world.property.id, rule.id)
    await recommendations.upsert_many(world.tenant.id, [recommendation])

    recommendation.decide(S.APPROVED)
    recommendation.recommended_price = Decimal("1.00")  # must NOT be written
    await recommendations.update(world.tenant.id, recommendation)

    stored = await recommendations.get(world.tenant.id, recommendation.id)
    assert stored is not None
    assert stored.status is S.APPROVED
    assert stored.recommended_price == Decimal("120.00")


@pytest.mark.parametrize(("page", "per_page"), [(0, 10), (1, 0)])
async def test_a_non_positive_recommendation_page_is_a_validation_error(
    recommendations, world, page: int, per_page: int
) -> None:
    with pytest.raises(PricingValidationError):
        await recommendations.list(
            world.tenant.id, PriceRecommendationFilters(), page=page, per_page=per_page
        )


# --- tenant isolation (DoD §28.18, R1.2, R1.7, R5.1) ----------------------------------
#
# The row-ownership assertions run on an `AsyncSession(test_engine)` that is **never
# marked**. On a marked session the listener of `app/core/db.py` rewrites even a
# single-column `select`, so the assertion would pass whatever the adapter did — the test
# would be tautological. Recorded in `sdd/project.md`'s memory of this trap.


async def test_get_does_not_cross_tenants(rules, recommendations, world) -> None:
    rule = make_rule(world.other_tenant.id)
    await rules.add(world.other_tenant.id, rule)
    recommendation = make_recommendation(
        world.other_tenant.id, world.other_property.id, rule.id
    )
    await recommendations.upsert_many(world.other_tenant.id, [recommendation])

    # R1.7: the acting tenant gets `None`, exactly as for an id that does not exist.
    assert await rules.get(world.tenant.id, rule.id) is None
    assert await recommendations.get(world.tenant.id, recommendation.id) is None
    # And the row really is there for its owner, so the None above is scoping, not absence.
    assert await rules.get(world.other_tenant.id, rule.id) is not None
    assert await recommendations.get(world.other_tenant.id, recommendation.id) is not None


async def test_list_never_crosses_tenants(rules, recommendations, world) -> None:
    mine = make_rule(world.tenant.id, name="mine")
    theirs = make_rule(world.other_tenant.id, name="theirs")
    await rules.add(world.tenant.id, mine)
    await rules.add(world.other_tenant.id, theirs)
    await recommendations.upsert_many(
        world.tenant.id, [make_recommendation(world.tenant.id, world.property.id, mine.id)]
    )
    await recommendations.upsert_many(
        world.other_tenant.id,
        [make_recommendation(world.other_tenant.id, world.other_property.id, theirs.id)],
    )

    rule_page = await rules.list(world.tenant.id, PricingRuleFilters(), page=1, per_page=50)
    recommendation_page = await recommendations.list(
        world.tenant.id, PriceRecommendationFilters(), page=1, per_page=50
    )

    assert [rule.name for rule in rule_page.items] == ["mine"]
    assert rule_page.total == 1
    assert recommendation_page.total == 1
    assert [row.tenant_id for row in recommendation_page.items] == [world.tenant.id]


async def test_list_active_never_crosses_tenants(rules, world) -> None:
    await rules.add(world.tenant.id, make_rule(world.tenant.id, name="mine"))
    await rules.add(world.other_tenant.id, make_rule(world.other_tenant.id, name="theirs"))

    active = await rules.list_active(world.tenant.id)

    assert [rule.name for rule in active] == ["mine"]


async def test_list_for_property_range_never_crosses_tenants(
    rules, recommendations, world
) -> None:
    theirs = make_rule(world.other_tenant.id)
    await rules.add(world.other_tenant.id, theirs)
    await recommendations.upsert_many(
        world.other_tenant.id,
        [make_recommendation(world.other_tenant.id, world.other_property.id, theirs.id)],
    )

    found = await recommendations.list_for_property_range(
        world.tenant.id, world.other_property.id, TODAY, TODAY + timedelta(days=1)
    )

    assert found == []


async def test_writing_an_entity_of_another_tenant_is_refused(
    rules, recommendations, world
) -> None:
    """`app/core/db.py`'s listener does not cover INSERTs, so this check is the only guard."""
    foreign_rule = make_rule(world.other_tenant.id)

    with pytest.raises(CrossTenantWriteError):
        await rules.add(world.tenant.id, foreign_rule)
    with pytest.raises(CrossTenantWriteError):
        await rules.update(world.tenant.id, foreign_rule)
    with pytest.raises(CrossTenantWriteError):
        await recommendations.upsert_many(
            world.tenant.id,
            [
                make_recommendation(
                    world.other_tenant.id, world.other_property.id, foreign_rule.id
                )
            ],
        )


async def test_the_upsert_cannot_touch_another_tenants_property(
    rules, recommendations, world, test_engine
) -> None:
    """The attack the schema leaves open, driven for real (R1.2, R4.2).

    `price_recommendations` has `UNIQUE (property_id, date)` with **no tenant**, and its FK
    to `properties` is global. So this entity is self-consistent — its `tenant_id` really is
    the acting tenant's — while being anchored to somebody else's flat, and it sails past
    `_require_same_tenant`.

    The earlier version of this test never made this call at all: it had the *owner* write a
    row and then checked the row was unchanged, so the `ON CONFLICT … WHERE` predicate was
    never evaluated and deleting it left the suite green. Raised by the section-3 security
    and tenancy panels.
    """
    theirs = make_rule(world.other_tenant.id)
    await rules.add(world.other_tenant.id, theirs)
    original = make_recommendation(
        world.other_tenant.id, world.other_property.id, theirs.id, price=Decimal("77.00")
    )
    await recommendations.upsert_many(world.other_tenant.id, [original])
    # Committed BEFORE the trespass, so the assertion at the end is about a row that
    # survives the rollback. An earlier version asserted after rolling the owner's insert
    # back too, which made `price is None` always true and the assertion vacuous — it would
    # have stayed green with the guard deleted. Raised by the section-3 security panel.
    await recommendations._session.commit()

    mine = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, mine)
    trespass = make_recommendation(
        world.tenant.id,           # my own tenant...
        world.other_property.id,   # ...anchored to their property
        mine.id,
        price=Decimal("1.00"),
    )

    with pytest.raises(CrossTenantWriteError):
        await recommendations.upsert_many(world.tenant.id, [trespass])

    await recommendations._session.rollback()
    async with AsyncSession(test_engine) as unmarked:
        price = await unmarked.scalar(
            select(PriceRecommendationModel.recommended_price).where(
                PriceRecommendationModel.id == original.id
            )
        )
    assert price == Decimal("77.00")


async def test_the_upsert_refuses_to_squat_a_free_property_day(
    rules, recommendations, world
) -> None:
    """The half the `ON CONFLICT` predicate cannot reach, because there is no conflict.

    Inserting first on `(their property, date)` takes the unique key. Every later upsert by
    the real owner would then collide, fail the predicate and be **skipped silently and for
    ever** — a cross-tenant denial of service with nothing raised anywhere. This is why the
    property-ownership check runs before the statement is built, not only inside it.
    """
    mine = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, mine)
    squat = make_recommendation(world.tenant.id, world.other_property.id, mine.id)

    with pytest.raises(CrossTenantWriteError):
        await recommendations.upsert_many(world.tenant.id, [squat])


async def test_a_property_of_the_acting_tenant_is_accepted(
    rules, recommendations, world
) -> None:
    """The ownership guard must not reject the ordinary case it exists to bracket."""
    mine = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, mine)

    outcome = await recommendations.upsert_many(
        world.tenant.id,
        [
            make_recommendation(world.tenant.id, world.property.id, mine.id),
            make_recommendation(world.tenant.id, world.second_property.id, mine.id),
        ],
    )

    assert (outcome.created, outcome.updated) == (2, 0)


async def test_a_rule_row_belongs_to_the_tenant_that_wrote_it(
    rules, world, test_engine
) -> None:
    """Read back on an unmarked session, so the global filter cannot fake the answer."""
    rule = make_rule(world.tenant.id)
    await rules.add(world.tenant.id, rule)
    await rules._session.commit()

    async with AsyncSession(test_engine) as unmarked:
        owner = await unmarked.scalar(
            select(PricingRuleModel.tenant_id).where(PricingRuleModel.id == rule.id)
        )

    assert owner == world.tenant.id
