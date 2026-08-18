"""The tenant every route actually passes to every port (R1.2, R5.1; rule 1 of security.md).

**Why this file exists, and why the 404 tests are not enough.** Rule 1 asks for "tests
automáticos que **demuestran** que un tenant no accede a datos de otro". The obvious shape —
seed the neighbour's row, request it, assert 404 — cannot fail here, and the mechanism is worth
stating because it recurs: the first authenticated call runs `bind_session_to_tenant`, which
installs a `with_loader_criteria(entity, entity.tenant_id == tenant_id)` on the shared session
for every later ORM `SELECT`. From that moment the neighbour's row is invisible **whatever
`tenant_id` the router, the use case or the repository actually used**. `app/core/db.py` says as
much about itself: the explicit parameter is "the authoritative mechanism" and the listener is
only "the net that stops a forgotten filter from becoming a leak". A test that observes only the
outcome is testing the net.

So this file watches the **value**. Every port method the seven routes reach is wrapped, the
whole surface is driven as one tenant's manager, and two things are asserted: that no port was
ever handed a tenant other than the caller's, and that the expected methods were genuinely
reached — the second because a spy that records nothing agrees with every hypothesis.

**And the write side is a separate blind spot from the read side, which is the part worth
saying out loud.** A read with the wrong tenant at least *has* a wrong answer to observe, so an
outcome-based test could in principle catch it (this one cannot, per the listener above). A
**write** with the wrong tenant has no wrong answer at all: the response is a 200, the caller
sees exactly what they expected, and the damage is a row deposited in somebody else's history —
`timeline_events` being append-only, permanently. No 404-shaped assertion can reach that class,
which is why `timeline.add` and `audit.add` are on the spy list even though they belong to other
modules. Measured while building this file: mutating `DecidePriceRecommendationUseCase` to hand
`timeline.add` a fresh UUID keeps every status assertion in the suite green and only these spies
go red. That mutation also showed the class is **currently** defended one layer down —
`app/timeline/infrastructure/repositories.py` raises `CrossTenantWriteError` when the event's
tenant disagrees with the acting one — so the honest reading is that the platform already guards
it and these tests now credit that guard instead of assuming it.

Raised by the tenancy and security panels of section 6, which both found the earlier version of
this coverage (one spy, on `SqlAlchemyPricingRuleRepository.get`, driven by the detail route
alone) proved nothing about the other eleven call sites. `maintenance` learned the same lesson
the same way: a spy on its detail route was green while its mutating routes went unchecked.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.pricing.domain.enums import PriceRecommendationStatus
from tests.pricing.conftest import (  # noqa: F401
    api,
    auth_header,
    make_recommendation,
    make_rule,
    world,
)

pytestmark = pytest.mark.asyncio

RULES = "/api/v1/pricing-rules"
RECOMMENDATIONS = "/api/v1/price-recommendations"

#: Every `(class, method)` a pricing route reaches that takes `tenant_id` as its first
#: argument — the four ports of this module plus the three it borrows. The cross-module three
#: matter most, not least: a wrong tenant on `timeline.add` or `audit.add` does not hide a row,
#: it **writes** one into somebody else's history, and `timeline_events` is append-only.
_SPIED: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "app.pricing.infrastructure.repositories",
        "SqlAlchemyPricingRuleRepository",
        ("add", "get", "list", "list_active", "update"),
    ),
    (
        "app.pricing.infrastructure.repositories",
        "SqlAlchemyPriceRecommendationRepository",
        ("get", "list", "list_for_property_range", "upsert_many", "update"),
    ),
    (
        "app.properties.infrastructure.repositories",
        "SqlAlchemyPropertyRepository",
        ("get", "list_by_status"),
    ),
    (
        "app.reservations.infrastructure.repositories",
        "SqlAlchemyReservationRepository",
        ("list_for_properties",),
    ),
    (
        "app.timeline.infrastructure.repositories",
        "SqlAlchemyTimelineEventRepository",
        ("add",),
    ),
    (
        "app.audit.infrastructure.repositories",
        "SqlAlchemyAuditLogRepository",
        ("add",),
    ),
)

#: What driving the whole surface must actually reach. Asserted as a subset of what was seen,
#: so this is a floor: a route that stops consulting a port fails here rather than quietly
#: reducing what the tenant assertion covers.
_EXPECTED_COVERAGE = frozenset(
    {
        ("SqlAlchemyPricingRuleRepository", "add"),
        ("SqlAlchemyPricingRuleRepository", "get"),
        ("SqlAlchemyPricingRuleRepository", "list"),
        ("SqlAlchemyPricingRuleRepository", "list_active"),
        ("SqlAlchemyPricingRuleRepository", "update"),
        ("SqlAlchemyPriceRecommendationRepository", "get"),
        ("SqlAlchemyPriceRecommendationRepository", "list"),
        ("SqlAlchemyPriceRecommendationRepository", "list_for_property_range"),
        ("SqlAlchemyPriceRecommendationRepository", "upsert_many"),
        ("SqlAlchemyPriceRecommendationRepository", "update"),
        ("SqlAlchemyPropertyRepository", "get"),
        ("SqlAlchemyPropertyRepository", "list_by_status"),
        ("SqlAlchemyReservationRepository", "list_for_properties"),
        ("SqlAlchemyTimelineEventRepository", "add"),
        ("SqlAlchemyAuditLogRepository", "add"),
    }
)


def _install_spies(monkeypatch) -> list[tuple[str, str, uuid.UUID]]:
    """Wrap every spied method so it records the `tenant_id` it was handed, then delegates.

    Recorded rather than intercepted: the call must still do its real work, or the routes stop
    behaving and the drive below proves nothing about a working system.
    """
    import importlib

    seen: list[tuple[str, str, uuid.UUID]] = []

    for module_name, class_name, methods in _SPIED:
        module = importlib.import_module(module_name)
        target = getattr(module, class_name)
        for method_name in methods:
            original = getattr(target, method_name)

            def _spy(self, tenant_id, *args, _o=original, _c=class_name, _m=method_name, **kwargs):
                seen.append((_c, _m, tenant_id))
                return _o(self, tenant_id, *args, **kwargs)

            monkeypatch.setattr(target, method_name, _spy)

    return seen


async def _drive_every_route(api, world) -> None:
    """One pass over all seven routes, as this tenant's manager, in an order that works.

    Deliberately a real working sequence rather than seven isolated calls: `PATCH` needs a rule
    that exists, `APPLIED_EXTERNAL` needs an `APPROVED` recommendation, and the generator has to
    have something to reprice. A 4xx anywhere would mean the route bailed out before reaching
    the ports this file is watching, which is why every response is asserted.
    """
    headers = auth_header(api, world.manager)

    created = await api.post(
        RULES,
        json={
            "name": "Madrid base",
            "base_price": "100.00",
            "min_price": "50.00",
            "max_price": "200.00",
            "property_id": str(world.property.id),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    listing = await api.get(RULES, headers=headers)
    assert listing.status_code == 200, listing.text

    detail = await api.get(f"{RULES}/{rule_id}", headers=headers)
    assert detail.status_code == 200, detail.text

    # `property_id` in the body on purpose: it is what makes `UpdatePricingRule` consult
    # `PropertyRepository.get` (D20), so this is the call the earlier spy never reached.
    patched = await api.patch(
        f"{RULES}/{rule_id}",
        json={"max_price": "300.00", "property_id": str(world.property.id)},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text

    # Named scope first — that is the path through `PropertyRepository.get` …
    scoped = await api.post(
        f"{RECOMMENDATIONS}/generate",
        json={"property_id": str(world.property.id)},
        headers=headers,
    )
    assert scoped.status_code == 200, scoped.text

    # … and the unscoped sweep is the path through `list_by_status`.
    swept = await api.post(f"{RECOMMENDATIONS}/generate", json={}, headers=headers)
    assert swept.status_code == 200, swept.text

    recommendations = await api.get(
        RECOMMENDATIONS, params={"per_page": 1}, headers=headers
    )
    assert recommendations.status_code == 200, recommendations.text
    target = recommendations.json()["items"][0]["id"]

    approved = await api.patch(
        f"{RECOMMENDATIONS}/{target}",
        json={"status": PriceRecommendationStatus.APPROVED.value},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text

    # The transition that emits a timeline row, so `SqlAlchemyTimelineEventRepository.add` is
    # reached by the decision path and not only by the generator's creations.
    applied = await api.patch(
        f"{RECOMMENDATIONS}/{target}",
        json={"status": PriceRecommendationStatus.APPLIED_EXTERNAL.value},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text


async def test_no_port_is_ever_handed_a_tenant_other_than_the_callers(
    api, world, monkeypatch
) -> None:
    """R1.2 and R5.1, asserted on the argument rather than on the answer.

    This is the assertion that can actually fail. If any route or use case derived `tenant_id`
    from something other than `authenticated.context.tenant_id` — a stale default, a copied
    attribute, a body field — the recorded value would differ here, while every 404-based test
    in this suite stayed green because the session listener enforces the right scope regardless.
    """
    seen = _install_spies(monkeypatch)

    await _drive_every_route(api, world)

    assert seen, "no spied port was reached: the drive below proves nothing"
    wrong = {(cls, method, tenant) for cls, method, tenant in seen if tenant != world.tenant.id}
    assert wrong == set(), (
        "a port was handed a tenant other than the caller's own "
        f"(expected {world.tenant.id!r}): {sorted(map(str, wrong))}"
    )


async def test_the_drive_reaches_every_port_the_routes_are_supposed_to_use(
    api, world, monkeypatch
) -> None:
    """The guard on the guard above — otherwise it passes by touching nothing.

    A spy list that records two calls satisfies "no wrong tenant" just as well as one that
    records fifty, so the tenant assertion is only worth what this coverage floor says it is.
    That is exactly how the section-6 panels found the previous version wanting: it watched one
    method and concluded something about twelve.
    """
    seen = _install_spies(monkeypatch)

    await _drive_every_route(api, world)

    reached = {(cls, method) for cls, method, _ in seen}
    missing = _EXPECTED_COVERAGE - reached
    assert missing == set(), f"these ports were never reached by any route: {sorted(missing)}"


async def test_a_neighbours_row_is_invisible_even_on_an_unmarked_session(
    world, db_session
) -> None:
    """The other half of rule 1: the repository's **own** filter, with the net taken away.

    Read through the ports on a session that no request has marked, so
    `_scope_statement_to_tenant` contributes nothing and the only thing that can produce the
    right answer is the explicit `tenant_id` each method carries. A regression that dropped
    that filter — the one the 404 tests cannot see — fails here.
    """
    from app.pricing.domain.repositories import (
        PriceRecommendationFilters,
        PricingRuleFilters,
    )
    from app.pricing.infrastructure.models import PriceRecommendationModel
    from app.pricing.infrastructure.repositories import (
        SqlAlchemyPriceRecommendationRepository,
        SqlAlchemyPricingRuleRepository,
    )

    rules = SqlAlchemyPricingRuleRepository(db_session)
    recommendations = SqlAlchemyPriceRecommendationRepository(db_session)

    theirs = make_rule(world.other_tenant.id, property_id=world.other_property.id)
    await rules.add(world.other_tenant.id, theirs)
    await db_session.flush()
    their_recommendation = make_recommendation(
        world.other_tenant.id, world.other_property.id, theirs.id
    )
    db_session.add(
        PriceRecommendationModel(
            id=their_recommendation.id,
            tenant_id=their_recommendation.tenant_id,
            property_id=their_recommendation.property_id,
            pricing_rule_id=their_recommendation.pricing_rule_id,
            date=their_recommendation.date,
            recommended_price=their_recommendation.recommended_price,
            explanation=their_recommendation.explanation,
            confidence=their_recommendation.confidence,
            status=their_recommendation.status,
        )
    )
    await db_session.flush()

    mine = make_rule(world.tenant.id, property_id=world.property.id)
    await rules.add(world.tenant.id, mine)
    await db_session.flush()

    # Asked as MY tenant, on a session that was never bound to it.
    assert await rules.get(world.tenant.id, theirs.id) is None
    assert await rules.get(world.tenant.id, mine.id) is not None
    assert await recommendations.get(world.tenant.id, their_recommendation.id) is None

    rule_page = await rules.list(world.tenant.id, PricingRuleFilters(), page=1, per_page=100)
    assert [item.id for item in rule_page.items] == [mine.id]
    assert rule_page.total == 1

    assert [item.id for item in await rules.list_active(world.tenant.id)] == [mine.id]

    recommendation_page = await recommendations.list(
        world.tenant.id, PriceRecommendationFilters(), page=1, per_page=100
    )
    assert recommendation_page.items == ()
    assert recommendation_page.total == 0

    window_start = date.today() - timedelta(days=365)
    assert (
        await recommendations.list_for_property_range(
            world.tenant.id,
            world.other_property.id,
            window_start,
            window_start + timedelta(days=730),
        )
        == []
    )
