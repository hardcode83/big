"""Who may reach the seven routes, and what they see when they may not (R1.2, R1.7, R5.1).

This is where D11's RBAC is proved as *wiring*. `tests/auth/test_policy.py` fixes the role ×
permission matrix; what it cannot show is that each route hangs off the permission it should —
a route decorated with `READ_PRICING_RULES` where it needed `MANAGE_PRICING_RULES` leaves that
file perfectly green.

Two things get walked here, both structurally so a route added later cannot slip past:

* the whole surface per role, for the two roles D11 grants nothing to and for the anonymous
  caller;
* the four routes with an `{id}` in the path, which must answer **404 and not 403** for an
  identifier of another tenant (R1.7) — with the same body as for an unknown one, or the
  difference is a tenant-enumeration oracle.
"""

import uuid

import pytest

from app.auth.domain.enums import UserRole
from app.auth.domain.policy import ROLE_PERMISSIONS, Permission
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

#: The seven routes of PRD §23 as (method, path template, permission). The permission column
#: is what makes this a matrix rather than a smoke test: it is the pairing D11 decided, and a
#: route wired to the wrong one fails `test_each_route_declares_the_permission_d11_gave_it`
#: even while every status assertion below still passes.
ROUTES: tuple[tuple[str, str, Permission], ...] = (
    ("GET", RULES, Permission.READ_PRICING_RULES),
    ("POST", RULES, Permission.MANAGE_PRICING_RULES),
    ("GET", RULES + "/{rule_id}", Permission.READ_PRICING_RULES),
    ("PATCH", RULES + "/{rule_id}", Permission.MANAGE_PRICING_RULES),
    ("GET", RECOMMENDATIONS, Permission.READ_PRICE_RECOMMENDATIONS),
    ("POST", RECOMMENDATIONS + "/generate", Permission.MANAGE_PRICE_RECOMMENDATIONS),
    (
        "PATCH",
        RECOMMENDATIONS + "/{recommendation_id}",
        Permission.MANAGE_PRICE_RECOMMENDATIONS,
    ),
)

#: A body per route that needs one. Deliberately **valid**, so a `403` or `401` cannot be
#: mistaken for a schema refusal: authorisation runs in the dependencies, before the endpoint,
#: but a 422 in this file would still hide which wall actually stopped the caller.
_BODIES: dict[tuple[str, str], dict] = {
    ("POST", RULES): {
        "name": "Madrid base",
        "base_price": "100.00",
        "min_price": "50.00",
        "max_price": "200.00",
    },
    ("POST", RECOMMENDATIONS + "/generate"): {},
    ("PATCH", RULES + "/{rule_id}"): {"max_price": "300.00"},
    ("PATCH", RECOMMENDATIONS + "/{recommendation_id}"): {
        "status": PriceRecommendationStatus.APPROVED.value
    },
}


def _path(template: str, *, rule_id, recommendation_id) -> str:
    return template.format(rule_id=rule_id, recommendation_id=recommendation_id)


async def _call(api, method: str, template: str, headers: dict, *, rule_id, recommendation_id):
    return await api.request(
        method,
        _path(template, rule_id=rule_id, recommendation_id=recommendation_id),
        json=_BODIES.get((method, template)),
        headers=headers,
    )


async def _seed(db_session, world) -> tuple[uuid.UUID, uuid.UUID]:
    """One rule and one recommendation of the caller's own tenant, written directly.

    Directly rather than through the API because these tests must be able to run for a role
    that cannot create anything — and because a request as another tenant's user would bind
    the shared session and answer the next caller `401` (see `test_api_rules.py`).
    """
    from app.pricing.infrastructure.models import PriceRecommendationModel
    from app.pricing.infrastructure.repositories import SqlAlchemyPricingRuleRepository

    rule = make_rule(world.tenant.id, property_id=world.property.id)
    await SqlAlchemyPricingRuleRepository(db_session).add(world.tenant.id, rule)
    await db_session.flush()

    recommendation = make_recommendation(world.tenant.id, world.property.id, rule.id)
    db_session.add(
        PriceRecommendationModel(
            id=recommendation.id,
            tenant_id=recommendation.tenant_id,
            property_id=recommendation.property_id,
            pricing_rule_id=recommendation.pricing_rule_id,
            date=recommendation.date,
            recommended_price=recommendation.recommended_price,
            explanation=recommendation.explanation,
            confidence=recommendation.confidence,
            status=recommendation.status,
        )
    )
    await db_session.flush()
    return rule.id, recommendation.id


# --- the roles D11 grants nothing to ------------------------------------------------------


@pytest.mark.parametrize("role", ["cleaner", "technician"])
async def test_a_role_without_the_permissions_is_refused_on_every_route(
    api, world, db_session, role: str
) -> None:
    """D11: `CLEANER` and `TECHNICIAN` receive none of the four permissions, and pricing is
    not their job — neither reads a price nor sets one."""
    rule_id, recommendation_id = await _seed(db_session, world)
    headers = auth_header(api, getattr(world, role))

    for method, template, _ in ROUTES:
        response = await _call(
            api,
            method,
            template,
            headers,
            rule_id=rule_id,
            recommendation_id=recommendation_id,
        )
        assert response.status_code == 403, f"{method} {template} -> {response.status_code}"


async def test_an_anonymous_caller_is_refused_on_every_route(api, world, db_session) -> None:
    """There is no anonymous door into this module. The nightly generator reaches the same use
    case through the scheduler, not through a route, so no route needs to be open."""
    rule_id, recommendation_id = await _seed(db_session, world)

    for method, template, _ in ROUTES:
        response = await _call(
            api, method, template, {}, rule_id=rule_id, recommendation_id=recommendation_id
        )
        assert response.status_code == 401, f"{method} {template} -> {response.status_code}"


async def test_a_token_that_is_not_a_user_jwt_reaches_nothing(api, world, db_session) -> None:
    """A guest-portal link is not a credential here: `require(...)` accepts only the user JWT."""
    rule_id, _ = await _seed(db_session, world)

    response = await api.get(
        f"{RULES}/{rule_id}", headers={"Authorization": "Bearer not-a-jwt"}
    )

    assert response.status_code == 401


# --- the two roles D11 grants everything to -----------------------------------------------


@pytest.mark.parametrize("role", ["manager", "owner"])
async def test_both_permitted_roles_reach_every_route(
    api, world, db_session, role: str
) -> None:
    """D11's conscious divergence from "the owner sees, the manager operates".

    The owner gets `MANAGE_*` too, because `min_price`/`max_price`/`max_daily_change_pct` are
    the limits of her own money (R3's user story) and PRD §19 Mode 1 says literally
    "Manager/owner aprueba manualmente". Asserted as "not 401 and not 403": what each route
    then answers is the business of the other two API test files, and folding it in here would
    make this matrix fail for reasons that are not about authorisation.
    """
    rule_id, recommendation_id = await _seed(db_session, world)
    headers = auth_header(api, getattr(world, role))

    for method, template, _ in ROUTES:
        response = await _call(
            api,
            method,
            template,
            headers,
            rule_id=rule_id,
            recommendation_id=recommendation_id,
        )
        assert response.status_code not in (401, 403), (
            f"{method} {template} -> {response.status_code}: {response.text}"
        )


async def test_each_route_declares_the_permission_d11_gave_it() -> None:
    """The pairing itself, read off the mounted app rather than off this file's table.

    Without this, `ROUTES` would only be a list of paths: every status assertion above passes
    identically whether `PATCH /pricing-rules/{id}` requires `MANAGE_PRICING_RULES` or
    `READ_PRICING_RULES`, because the same two roles hold both. That is exactly the swap a
    copied decorator makes, and the reason D11 split read from manage in the first place.
    """
    from app.main import create_app
    from tests.route_walk import flatten_routes

    found, _ = flatten_routes(create_app())
    declared = {
        (method, path): _required_permissions(route)
        for path, route in found
        for method in (route.methods or set())
    }

    for method, template, permission in ROUTES:
        assert declared.get((method, template)) == {permission}, (
            f"{method} {template} does not declare exactly {permission}"
        )


def _required_permissions(route) -> set:
    """The permissions a route's dependencies demand, dug out of `require(...)`'s closure."""
    required = set()
    for dependency in route.dependant.dependencies:
        call = dependency.call
        for cell in getattr(call, "__closure__", None) or ():
            value = cell.cell_contents
            if isinstance(value, Permission):
                required.add(value)
    return required


async def test_no_role_outside_the_two_holds_any_pricing_permission() -> None:
    """D11's other half, and the reason the 403 walk above is only two roles long.

    `tests/auth/test_policy.py` owns the matrix; this asserts the *closure* it depends on, so
    a third role quietly granted `READ_PRICING_RULES` makes the parametrised walk above
    incomplete and this test is what says so.
    """
    pricing_permissions = {
        Permission.READ_PRICING_RULES,
        Permission.MANAGE_PRICING_RULES,
        Permission.READ_PRICE_RECOMMENDATIONS,
        Permission.MANAGE_PRICE_RECOMMENDATIONS,
    }
    holders = {
        role
        for role in UserRole
        if ROLE_PERMISSIONS.get(role, frozenset()) & pricing_permissions
    }

    assert holders == {UserRole.TENANT_OWNER, UserRole.PROPERTY_MANAGER}


# --- R1.7: another tenant's identifier is a 404, never a 403 -------------------------------


async def _seed_neighbour(db_session, world) -> tuple[uuid.UUID, uuid.UUID]:
    from app.pricing.infrastructure.models import PriceRecommendationModel
    from app.pricing.infrastructure.repositories import SqlAlchemyPricingRuleRepository

    rule = make_rule(world.other_tenant.id, property_id=world.other_property.id)
    await SqlAlchemyPricingRuleRepository(db_session).add(world.other_tenant.id, rule)
    await db_session.flush()

    recommendation = make_recommendation(
        world.other_tenant.id, world.other_property.id, rule.id
    )
    db_session.add(
        PriceRecommendationModel(
            id=recommendation.id,
            tenant_id=recommendation.tenant_id,
            property_id=recommendation.property_id,
            pricing_rule_id=recommendation.pricing_rule_id,
            date=recommendation.date,
            recommended_price=recommendation.recommended_price,
            explanation=recommendation.explanation,
            confidence=recommendation.confidence,
            status=recommendation.status,
        )
    )
    await db_session.flush()
    return rule.id, recommendation.id


#: The four routes with an identifier in the path — the only ones R1.7 can be asked of.
ID_ROUTES: tuple[tuple[str, str], ...] = tuple(
    (method, template) for method, template, _ in ROUTES if "{" in template
)


@pytest.mark.parametrize(("method", "template"), ID_ROUTES)
async def test_another_tenants_identifier_is_a_404_not_a_403(
    api, world, db_session, method: str, template: str
) -> None:
    """R1.7 — "responder `404` y no `403`, sin revelar su existencia".

    A `403` would confirm the row exists and belongs to somebody else, which is the one thing
    the answer must not say. This holds because the ports return `None` outside the tenant and
    the use cases raise their not-found error from a constant message — the endpoint never asks
    "does this exist somewhere else?".
    """
    rule_id, recommendation_id = await _seed_neighbour(db_session, world)

    response = await _call(
        api,
        method,
        template,
        auth_header(api, world.manager),
        rule_id=rule_id,
        recommendation_id=recommendation_id,
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(("method", "template"), ID_ROUTES)
async def test_the_two_404s_are_indistinguishable(
    api, world, db_session, method: str, template: str
) -> None:
    """The status is not enough: two 404s with different bodies are still an oracle."""
    rule_id, recommendation_id = await _seed_neighbour(db_session, world)
    headers = auth_header(api, world.manager)

    theirs = await _call(
        api,
        method,
        template,
        headers,
        rule_id=rule_id,
        recommendation_id=recommendation_id,
    )
    unknown = await _call(
        api,
        method,
        template,
        headers,
        rule_id=uuid.uuid4(),
        recommendation_id=uuid.uuid4(),
    )

    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json() == unknown.json()
