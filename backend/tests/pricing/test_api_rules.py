"""The four pricing-rule routes over HTTP (R1.1-R1.7; design D1, D16, D20).

Through `create_app()` rather than against a use case, because what these prove lives above
it: the `201` and the identifier R1.1 promises, the `422` naming the field that failed, the
`404` that must not distinguish "unknown" from "somebody else's", and the two halves of D20's
gate — a `property_id` of another tenant refused on creation **and** on update.
"""

import uuid

import pytest

from tests.pricing.conftest import (  # noqa: F401
    api,
    auth_header,
    make_rule,
    world,
)

pytestmark = pytest.mark.asyncio

RULES = "/api/v1/pricing-rules"


def _payload(**overrides) -> dict:
    body = {
        "name": "Madrid base",
        "base_price": "100.00",
        "min_price": "50.00",
        "max_price": "200.00",
    }
    body.update(overrides)
    return body


async def _create(api, world, **overrides):
    return await api.post(
        RULES, json=_payload(**overrides), headers=auth_header(api, world.manager)
    )


async def test_creating_a_rule_answers_201_with_its_identifier(api, world) -> None:
    """R1.1 — "devolver `201` con su identificador"."""
    response = await _create(api, world, property_id=str(world.property.id))

    assert response.status_code == 201, response.text
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["property_id"] == str(world.property.id)
    assert body["base_price"] == "100.00"
    # The default the schema publishes, so a client that omits it knows what it gets.
    assert body["max_daily_change_pct"] == "20.00"


async def test_the_response_never_carries_the_tenant(api, world) -> None:
    """The tenant is the token's business. Asserted on the **serialised payload**, not on the
    entity: the entity has a `tenant_id` and the wall is this schema enumerating its fields."""
    response = await _create(api, world)

    assert "tenant_id" not in response.json()


async def test_a_rule_without_a_property_is_tenant_wide(api, world) -> None:
    """R1.5 — omitting `property_id` is how a rule covers every property with none of its own."""
    response = await _create(api, world)

    assert response.status_code == 201
    assert response.json()["property_id"] is None


async def test_the_created_rule_is_readable_back(api, world) -> None:
    created = await _create(api, world, seasonality_rules=[])
    rule_id = created.json()["id"]

    response = await api.get(
        f"{RULES}/{rule_id}", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 200
    assert response.json()["id"] == rule_id


async def test_the_listing_is_paginated_and_filtered(api, world) -> None:
    """R1.2 — `page`/`per_page` of PRD §23, plus the two filters of the route table."""
    await _create(api, world, name="For the flat", property_id=str(world.property.id))
    await _create(api, world, name="Tenant wide")
    await _create(api, world, name="Switched off", active=False)
    headers = auth_header(api, world.manager)

    everything = await api.get(RULES, headers=headers)
    by_property = await api.get(
        RULES, params={"property_id": str(world.property.id)}, headers=headers
    )
    only_active = await api.get(RULES, params={"active": "true"}, headers=headers)
    first_page = await api.get(RULES, params={"per_page": 1}, headers=headers)

    assert everything.json()["total"] == 3
    assert [item["name"] for item in by_property.json()["items"]] == ["For the flat"]
    assert {item["name"] for item in only_active.json()["items"]} == {
        "For the flat",
        "Tenant wide",
    }
    assert len(first_page.json()["items"]) == 1
    assert first_page.json()["total"] == 3


async def test_a_patch_moves_only_the_fields_it_names(api, world) -> None:
    created = await _create(api, world, property_id=str(world.property.id))
    rule_id = created.json()["id"]

    response = await api.patch(
        f"{RULES}/{rule_id}",
        json={"max_price": "300.00"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_price"] == "300.00"
    assert body["base_price"] == "100.00"
    assert body["property_id"] == str(world.property.id)


async def test_a_null_property_id_makes_a_rule_tenant_wide(api, world) -> None:
    """The reason the router forwards `exclude_unset` and not `exclude_none` (R1.5).

    Absent means "leave it alone" and `null` means "cover the whole tenant". With
    `exclude_none` the second request would be silently read as the first, and the move would
    be unreachable through the API.
    """
    created = await _create(api, world, property_id=str(world.property.id))
    rule_id = created.json()["id"]

    response = await api.patch(
        f"{RULES}/{rule_id}",
        json={"property_id": None},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 200, response.text
    assert response.json()["property_id"] is None


async def test_an_empty_patch_changes_nothing(api, world) -> None:
    created = await _create(api, world)
    before = created.json()

    response = await api.patch(
        f"{RULES}/{before['id']}", json={}, headers=auth_header(api, world.manager)
    )

    assert response.status_code == 200
    assert response.json() == before


# --- R1.3 and R1.4: the domain is the gate, and it names the field ------------------------


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"min_price": "300.00"}, "min_price"),
        ({"base_price": "10.00"}, "base_price"),
        ({"max_daily_change_pct": "150.00"}, "max_daily_change_pct"),
        ({"weekday_modifiers": {"lunes": 10}}, "weekday_modifiers"),
        ({"lead_time_rules": [{"days_before": "3", "modifier_pct": 10}]}, "lead_time_rules"),
        ({"occupancy_rules": [{"occupancy_pct_above": 120, "modifier_pct": 5}]}, "occupancy_rules"),
        (
            {"seasonality_rules": [{"name": "s", "start_month": 13, "start_day": 1,
                                    "end_month": 2, "end_day": 1, "modifier_pct": 5}]},
            "seasonality_rules",
        ),
        ({"event_rules": [{"holidays": "ES_LOCAL", "modifier_pct": 5}]}, "event_rules"),
        (
            {"event_rules": [{"name": "x", "date": "2026-08-15", "holidays": "ES_NATIONAL",
                              "modifier_pct": 5}]},
            "event_rules",
        ),
    ],
)
async def test_an_invalid_rule_is_a_422_naming_its_field(
    api, world, overrides: dict, field: str
) -> None:
    """R1.3/R1.4, and the answer comes from the **domain** (D16), not from Pydantic.

    Which is why the message names the column: a 422 saying only "invalid rule" leaves a
    manager guessing which of the five JSONB columns she got wrong.
    """
    response = await _create(api, world, **overrides)

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert field in body["error"]["message"]


async def test_a_refused_creation_persists_nothing(api, world) -> None:
    """R1.3 — "sin persistir nada"."""
    await _create(api, world, min_price="300.00")

    listing = await api.get(RULES, headers=auth_header(api, world.manager))

    assert listing.json()["total"] == 0


async def test_a_refused_patch_leaves_the_rule_as_it_was(api, world) -> None:
    created = await _create(api, world)
    before = created.json()

    refused = await api.patch(
        f"{RULES}/{before['id']}",
        json={"min_price": "300.00"},
        headers=auth_header(api, world.manager),
    )
    after = await api.get(
        f"{RULES}/{before['id']}", headers=auth_header(api, world.manager)
    )

    assert refused.status_code == 422
    # Including `updated_at`: `update_details` restores from a snapshot when `validate()`
    # rejects, so a refused update does not stamp the row.
    assert after.json() == before


@pytest.mark.parametrize(
    ("overrides", "column"),
    [
        # A JSON **object key**, which no schema bounds: `weekday_modifiers` is typed
        # `dict[str, Any]`, so the key is as long as whoever sent it chose.
        ({"weekday_modifiers": {"x" * 5000: 10}}, "weekday_modifiers"),
        # A catalogue name that is not `ES_NATIONAL` (D7).
        ({"event_rules": [{"holidays": "x" * 5000, "modifier_pct": 5}]}, "event_rules"),
        # The nastiest of the three: `date.fromisoformat`'s own `ValueError` quotes the
        # offending string **in full**, so an un-redacted message hands the whole thing back.
        (
            {"event_rules": [{"name": "n", "date": "x" * 5000, "modifier_pct": 5}]},
            "event_rules",
        ),
    ],
)
async def test_a_422_never_echoes_an_unbounded_caller_value(
    api, world, overrides: dict, column: str
) -> None:
    """Task 6.2's third body rule: "ningún mensaje de error hace eco de un valor del llamante
    sin acotar".

    Section 6 is what makes these reachable — the five JSONB columns are free-form interiors
    that D16 deliberately leaves to the domain, and until there was a route nobody could send
    one. Each message names the *supported set* instead, which is what keeps it actionable;
    R1.4 only ever asked for the field.
    """
    response = await _create(api, world, **overrides)

    assert response.status_code == 422, response.text
    message = response.json()["error"]["message"]
    assert column in message
    assert "x" * 100 not in message
    # A bound, not just the absence of that needle: a message could echo the value in a
    # different form (escaped, truncated at 4 KB) and still be a body the caller sized.
    assert len(message) < 500, message


async def test_a_body_field_outside_the_schema_is_refused(api, world) -> None:
    """`extra="forbid"`: a misspelt field is a 422, not a silently ignored intention."""
    response = await _create(api, world, base_prize="100.00")

    assert response.status_code == 422


# --- D20's gate: the half that arrives by keyboard ----------------------------------------


async def test_creating_a_rule_for_another_tenants_property_is_a_422(api, world) -> None:
    """D20. The foreign key is global, so nothing in the schema stops this — and the damage
    is not the overwrite the `ON CONFLICT … WHERE` guards: it is the **first insert**, which
    takes the `(property_id, date)` key and makes every later upsert of the rightful tenant
    fail its predicate and be discarded silently, for ever."""
    response = await _create(api, world, property_id=str(world.other_property.id))

    assert response.status_code == 422, response.text
    assert "property_id" in response.json()["error"]["message"]


async def test_repointing_a_rule_at_another_tenants_property_is_a_422(api, world) -> None:
    """The other half of the same gate, and the one section 3 left standing: `property_id` is
    a mutable column, so an update reaches exactly as far as a creation."""
    created = await _create(api, world, property_id=str(world.property.id))

    response = await api.patch(
        f"{RULES}/{created.json()['id']}",
        json={"property_id": str(world.other_property.id)},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422, response.text
    assert "property_id" in response.json()["error"]["message"]


async def test_an_unknown_property_is_a_422_and_not_a_404(api, world) -> None:
    """D20's status choice: the *body* names something the tenant does not have, which is a
    validation failure. The `404` of R1.7 is for the identifier in the path."""
    response = await _create(api, world, property_id=str(uuid.uuid4()))

    assert response.status_code == 422


# --- R1.7: unknown and somebody else's are the same answer --------------------------------


async def test_an_unknown_rule_is_a_404(api, world) -> None:
    response = await api.get(
        f"{RULES}/{uuid.uuid4()}", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def _seed_neighbour_rule(db_session, world) -> uuid.UUID:
    """The other tenant's rule, written **directly** and before any request.

    Not through the API as their manager, and the reason is the shared session: the first
    authenticated call runs `bind_session_to_tenant`, which installs a `with_loader_criteria`
    for that tenant on every later ORM `SELECT` — including the one that resolves the *next*
    token's user, so a second caller from another tenant is answered `401` instead of being
    authenticated. Seeding first keeps the neighbour's row real while leaving the session
    unmarked for the caller under test.
    """
    from app.pricing.infrastructure.repositories import SqlAlchemyPricingRuleRepository

    rule = make_rule(world.other_tenant.id, property_id=world.other_property.id)
    await SqlAlchemyPricingRuleRepository(db_session).add(world.other_tenant.id, rule)
    await db_session.flush()
    return rule.id


async def test_another_tenants_rule_is_the_same_404_with_the_same_body(
    api, world, db_session
) -> None:
    """R1.7 — "`404` y no `403`, sin revelar su existencia", asserted on the body too.

    A 404 that read differently for the two cases would be a tenant-enumeration oracle: the
    caller could tell "this id is taken" from "this id is free".
    """
    theirs = await _seed_neighbour_rule(db_session, world)
    headers = auth_header(api, world.manager)

    not_mine = await api.get(f"{RULES}/{theirs}", headers=headers)
    unknown = await api.get(f"{RULES}/{uuid.uuid4()}", headers=headers)

    assert not_mine.status_code == unknown.status_code == 404
    assert not_mine.json() == unknown.json()


async def test_patching_another_tenants_rule_is_a_404(api, world, db_session) -> None:
    theirs = await _seed_neighbour_rule(db_session, world)

    response = await api.patch(
        f"{RULES}/{theirs}",
        json={"max_price": "999.00"},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 404


async def test_the_listing_never_crosses_tenants(api, world, db_session) -> None:
    """DoD §28.18 through the real app."""
    await _seed_neighbour_rule(db_session, world)
    await _create(api, world, name="Mine")

    response = await api.get(RULES, headers=auth_header(api, world.manager))

    assert [item["name"] for item in response.json()["items"]] == ["Mine"]
    assert response.json()["total"] == 1


async def test_the_route_asks_the_repository_for_the_callers_own_tenant(
    api, world, monkeypatch
) -> None:
    """Rule 1 of `steering/security.md` asks for a test that *demonstrates* the isolation, and
    the 404 above cannot fail: by the time it asserts, the first authenticated call has already
    made `bind_session_to_tenant` install a `with_loader_criteria` on the shared session, so
    the neighbour's row is invisible whatever the router, the use case or the repository do
    with `tenant_id`. This watches the value that actually reaches the port.
    """
    from app.pricing.infrastructure.repositories import SqlAlchemyPricingRuleRepository

    seen: list[uuid.UUID] = []
    original = SqlAlchemyPricingRuleRepository.get

    async def _spy(self, tenant_id, rule_id):
        seen.append(tenant_id)
        return await original(self, tenant_id, rule_id)

    created = await _create(api, world)
    monkeypatch.setattr(SqlAlchemyPricingRuleRepository, "get", _spy)

    response = await api.get(
        f"{RULES}/{created.json()['id']}", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 200
    assert seen == [world.tenant.id], (
        "the repository was asked for a tenant other than the caller's own: "
        f"{seen!r} != [{world.tenant.id!r}]"
    )
