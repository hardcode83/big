"""The seven use cases of section 5 (R1, R4, R5, R6; design D9, D10, D12, D14, D20).

Integration tests over the real repositories and a real database — see `Flow` in
`conftest.py` for why fakes would not do: idempotency against a live
`UNIQUE (property_id, date)`, a human decision surviving a regeneration, and one
transaction per property are all things a fake would agree with whatever the code did.
"""

import ast
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.audit.domain import actions as audit_actions
from app.audit.infrastructure.models import AuditLogModel
from app.pricing.application.use_cases import (
    GenerationOutcome,
    PricingActor,
    _AuditWriter,
)
from app.pricing.domain.enums import PriceRecommendationStatus
from app.pricing.domain.exceptions import (
    InvalidRecommendationTransitionError,
    PriceRecommendationNotFoundError,
    PricingRuleNotFoundError,
    PricingValidationError,
)
from app.pricing.domain.repositories import (
    PriceRecommendationFilters,
    PricingRuleFilters,
)
from app.pricing.infrastructure.models import PriceRecommendationModel, PricingRuleModel
from app.properties.domain.enums import PropertyStatus
from app.reservations.domain.enums import ReservationStatus
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel

from tests.pricing.conftest import NOW, TODAY, make_reservation

pytestmark = pytest.mark.asyncio

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

BASE_RULE = {
    "name": "Madrid base",
    "base_price": Decimal("100.00"),
    "min_price": Decimal("50.00"),
    "max_price": Decimal("200.00"),
}


def actor_of(world) -> PricingActor:
    return PricingActor(user_id=world.manager.id, ip="10.0.0.1")


async def a_rule(flow, world, **overrides):
    """A rule created through the use case, so it is audited exactly as production is."""
    fields = {**BASE_RULE, **overrides}
    return await flow.create_rule.execute(
        tenant_id=world.tenant.id, actor=actor_of(world), now=NOW, **fields
    )


async def audit_rows(session, tenant_id, entity_type: str) -> list[AuditLogModel]:
    rows = await session.execute(
        select(AuditLogModel).where(
            AuditLogModel.tenant_id == tenant_id,
            AuditLogModel.entity_type == entity_type,
        )
    )
    return list(rows.scalars())


async def horizon_rows(session, property_id) -> list[PriceRecommendationModel]:
    rows = await session.execute(
        select(PriceRecommendationModel)
        .where(PriceRecommendationModel.property_id == property_id)
        .order_by(PriceRecommendationModel.date)
    )
    return list(rows.scalars())


async def timeline_rows(session, property_id, event_type) -> list[TimelineEventModel]:
    rows = await session.execute(
        select(TimelineEventModel).where(
            TimelineEventModel.property_id == property_id,
            TimelineEventModel.event_type == event_type,
        )
    )
    return list(rows.scalars())


async def seed_recommendation(session, world, rule, *, day, price, status):
    """A row written straight to the table, so a test can start from a status the use
    cases never produce (`APPROVED`, `REJECTED`) without going through them first."""
    row = PriceRecommendationModel(
        id=uuid.uuid4(),
        tenant_id=world.tenant.id,
        property_id=world.property.id,
        pricing_rule_id=rule.id,
        date=day,
        recommended_price=Decimal(price),
        explanation="seeded",
        confidence=Decimal("1.00"),
        status=status,
        created_at=NOW,
    )
    session.add(row)
    await session.flush()
    return row


# --- 5.1 The audit writer -----------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        audit_actions.PRICING_RULE_CREATED,
        audit_actions.PRICING_RULE_UPDATED,
        audit_actions.PRICE_RECOMMENDATION_DECIDED,
        audit_actions.PRICE_RECOMMENDATION_APPLIED_EXTERNAL,
        audit_actions.PRICE_RECOMMENDATIONS_GENERATED,
    ],
)
async def test_no_pricing_audit_action_may_be_written_without_an_actor(
    flow, world, action
) -> None:
    """D12: every audited action of this module is performed by an authenticated person.

    Unlike `maintenance`, this module has **no** actor-optional action to carve out. The one
    anonymous caller — the nightly generator — writes no audit row *because it never calls the
    writer*, so the exemption is a consequence of "no actor, no call" rather than a special
    case in here (OQ1, narrowed to the clock on 2026-08-17).
    """
    from app.audit.domain.value_objects import ChangeSet

    writer = _AuditWriter(flow.audit)
    if action.startswith("PRICING_RULE"):
        entity = audit_actions.ENTITY_PRICING_RULE
    elif action == audit_actions.PRICE_RECOMMENDATIONS_GENERATED:
        # A horizon has no single id, so the generation is audited against the property.
        entity = audit_actions.ENTITY_PROPERTY
    else:
        entity = audit_actions.ENTITY_PRICE_RECOMMENDATION

    with pytest.raises(PricingValidationError):
        await writer.record(
            tenant_id=world.tenant.id,
            action=action,
            entity_type=entity,
            entity_id=uuid.uuid4(),
            actor=None,
            changes=ChangeSet(entity),
            now=NOW,
        )


async def test_the_audited_name_is_the_rules_own_and_not_the_callers_label(
    flow, world, db_session
) -> None:
    """The diff's field names come from `UPDATABLE_RULE_FIELDS`, its values from the entity.

    The residue the section-4 security panel left: `REDACT_ONLY_FIELDS` refuses the five
    JSONB columns *by name*, so the natural shortcut is to relabel one of them as `name`,
    which is diffable and accepts any `str`. Reading the value off `rule.name` makes that
    unwritable — this asserts the value stored is exactly the rule's name and nothing that
    was ever near a JSONB column.
    """
    rule = await a_rule(flow, world)

    await flow.update_rule.execute(
        world.tenant.id,
        rule.id,
        {"name": "Madrid summer", "seasonality_rules": [
            {
                "name": "high summer",
                "start_month": 7,
                "start_day": 1,
                "end_month": 8,
                "end_day": 31,
                "modifier_pct": 30,
            }
        ]},
        actor=actor_of(world),
        now=NOW,
    )

    updates = [
        row
        for row in await audit_rows(db_session, world.tenant.id, audit_actions.ENTITY_PRICING_RULE)
        if row.action == audit_actions.PRICING_RULE_UPDATED
    ]
    assert len(updates) == 1
    changes = updates[0].changes
    assert changes["name"] == {"old": "Madrid base", "new": "Madrid summer"}
    # And the season, whose `name` is the manager's free text, survives only as the fact.
    assert changes["seasonality_rules"] == {"changed": True}
    assert "high summer" not in str(changes)


# --- 5.2 The rule use cases ---------------------------------------------------------


async def test_creating_a_rule_persists_it_and_audits_it(flow, world, db_session) -> None:
    rule = await a_rule(flow, world, property_id=world.property.id)

    stored = await flow.rules.get(world.tenant.id, rule.id)
    assert stored is not None
    assert stored.property_id == world.property.id

    rows = await audit_rows(db_session, world.tenant.id, audit_actions.ENTITY_PRICING_RULE)
    assert [row.action for row in rows] == [audit_actions.PRICING_RULE_CREATED]
    assert rows[0].actor_user_id == world.manager.id
    # The five JSONB columns arrived empty, so nothing claims they changed.
    assert "seasonality_rules" not in rows[0].changes
    assert rows[0].changes["base_price"] == {"old": None, "new": "100.00"}


async def test_a_rule_of_another_tenant_is_not_found_rather_than_forbidden(
    flow, world
) -> None:
    """R1.7: unknown and somebody-else's answer identically, or the pair is a probe."""
    rule = await a_rule(flow, world)

    with pytest.raises(PricingRuleNotFoundError):
        await flow.get_rule.execute(world.other_tenant.id, rule.id)
    with pytest.raises(PricingRuleNotFoundError):
        await flow.update_rule.execute(
            world.other_tenant.id,
            rule.id,
            {"name": "stolen"},
            actor=PricingActor(user_id=world.other_manager.id),
            now=NOW,
        )


async def test_listing_rules_never_crosses_tenants(flow, world) -> None:
    await a_rule(flow, world)

    ours = await flow.list_rules.execute(
        world.tenant.id, PricingRuleFilters(), page=1, per_page=50
    )
    theirs = await flow.list_rules.execute(
        world.other_tenant.id, PricingRuleFilters(), page=1, per_page=50
    )

    assert ours.total == 1
    assert theirs.total == 0


async def test_a_foreign_property_cannot_be_named_when_creating_a_rule(
    flow, world, db_session
) -> None:
    """Design D20, the half that arrives by keyboard.

    The FKs are global, so the database would take a rule of tenant A anchored to tenant
    B's flat — and the section-3 panel showed the damage is not the overwrite but the
    first insert, which steals the `(property_id, date)` key for ever.
    """
    with pytest.raises(PricingValidationError) as error:
        await a_rule(flow, world, property_id=world.other_property.id)

    assert error.value.field == "property_id"
    assert await db_session.scalar(select(func.count()).select_from(PricingRuleModel)) == 0


async def test_a_foreign_property_cannot_be_named_when_updating_a_rule(
    flow, world
) -> None:
    """`property_id` is mutable, so re-pointing an existing rule is as reachable as
    creating one there. Same door, same guard."""
    rule = await a_rule(flow, world, property_id=world.property.id)

    with pytest.raises(PricingValidationError):
        await flow.update_rule.execute(
            world.tenant.id,
            rule.id,
            {"property_id": world.other_property.id},
            actor=actor_of(world),
            now=NOW,
        )

    stored = await flow.rules.get(world.tenant.id, rule.id)
    assert stored.property_id == world.property.id


async def test_an_invalid_rule_is_refused_without_persisting_anything(
    flow, world, db_session
) -> None:
    """R1.3 — `422` "sin persistir nada"."""
    with pytest.raises(PricingValidationError) as error:
        await a_rule(flow, world, min_price=Decimal("300.00"))

    assert error.value.field == "min_price"
    assert await db_session.scalar(select(func.count()).select_from(PricingRuleModel)) == 0


async def test_an_update_that_changes_nothing_owes_no_audit_row(
    flow, world, db_session
) -> None:
    rule = await a_rule(flow, world)

    await flow.update_rule.execute(
        world.tenant.id, rule.id, {"name": rule.name}, actor=actor_of(world), now=NOW
    )

    rows = await audit_rows(db_session, world.tenant.id, audit_actions.ENTITY_PRICING_RULE)
    assert [row.action for row in rows] == [audit_actions.PRICING_RULE_CREATED]


# --- 5.3 The generator --------------------------------------------------------------


async def test_the_horizon_is_sixty_days_starting_tomorrow_in_ascending_order(
    flow, world, db_session
) -> None:
    """R4.1 with `HORIZON_DAYS`: [execution_date + 1, execution_date + 61)."""
    await a_rule(flow, world, property_id=world.property.id)

    outcome = await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    rows = await horizon_rows(db_session, world.property.id)
    assert outcome == GenerationOutcome(created=60)
    assert len(rows) == 60
    assert rows[0].date == TODAY + timedelta(days=1)
    assert rows[-1].date == TODAY + timedelta(days=60)
    assert [row.date for row in rows] == sorted(row.date for row in rows)


async def test_the_generated_rows_carry_the_rendered_reasoning_and_full_confidence(
    flow, world, db_session
) -> None:
    """R6.1/R6.3 as the generator writes them: our own closed template, `confidence` at 1."""
    await a_rule(flow, world, property_id=world.property.id)

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    rows = await horizon_rows(db_session, world.property.id)
    assert all(row.confidence == Decimal("1.00") for row in rows)
    assert all(row.current_price is None for row in rows)
    assert rows[0].explanation.startswith("Base price 100.00 EUR.")
    assert rows[0].explanation.endswith("Recommended 100.00 EUR.")


async def test_the_occupancy_of_the_next_thirty_days_reaches_the_price(
    flow, world, db_session
) -> None:
    """R2.3/D5: one scalar per property and run, off the local reservations, no PMS."""
    await a_rule(
        flow,
        world,
        property_id=world.property.id,
        occupancy_rules=[{"occupancy_pct_above": 50, "modifier_pct": 10}],
    )
    # 20 of the window's 30 nights, which is 66.6% — above the threshold.
    await make_reservation(
        db_session,
        world.tenant.id,
        world.property.id,
        check_in=TODAY + timedelta(days=1),
        check_out=TODAY + timedelta(days=21),
    )
    # And one that must NOT count: a cancellation describes a night that ended up free.
    await make_reservation(
        db_session,
        world.tenant.id,
        world.property.id,
        check_in=TODAY + timedelta(days=21),
        check_out=TODAY + timedelta(days=31),
        status=ReservationStatus.CANCELLED,
    )

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    rows = await horizon_rows(db_session, world.property.id)
    assert rows[0].recommended_price == Decimal("110.00")
    assert "Occupancy" in rows[0].explanation


async def test_a_property_that_fails_does_not_discard_the_horizons_already_written(
    flow, world, db_session
) -> None:
    """D9's transaction boundary, demonstrated with the failure task 2.2 names.

    A rule row written before the validator existed carries a **string** threshold, which
    `calculate_price` compares as a bare `int` and dies on with `TypeError`. One bad rule
    must cost one property's horizon, not the portfolio's.
    """
    await a_rule(flow, world, property_id=world.property.id)
    db_session.add(
        PricingRuleModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=world.second_property.id,
            name="Broken",
            base_price=Decimal("100.00"),
            min_price=Decimal("50.00"),
            max_price=Decimal("200.00"),
            max_daily_change_pct=Decimal("20.00"),
            lead_time_rules=[{"days_before": "3", "modifier_pct": 10}],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await db_session.commit()
    # Read before the run, because the rollback the failing property triggers expires every
    # ORM object in this session's identity map — which is the point: the generator works
    # off domain entities it already holds, so it is unaffected.
    tenant_id, good, bad = world.tenant.id, world.property.id, world.second_property.id

    outcome = await flow.generate.execute(tenant_id, now=NOW)

    # `REDES11` sorts before `REDES12`, so the good property is priced first and its 60
    # committed rows have to survive the second property blowing up.
    assert outcome.created == 60
    assert outcome.failed == 1
    assert len(await horizon_rows(db_session, good)) == 60
    assert await horizon_rows(db_session, bad) == []


async def test_a_property_id_of_another_tenant_is_refused_by_the_generator(
    flow, world
) -> None:
    with pytest.raises(PricingValidationError) as error:
        await flow.generate.execute(
            world.tenant.id, now=NOW, property_id=world.other_property.id
        )

    assert error.value.field == "property_id"


async def test_an_inactive_property_is_refused_rather_than_counted_as_skipped(
    flow, world, db_session
) -> None:
    """R4.1 says "cada propiedad activa", and `skipped` means one thing only.

    R4.6 defines `skipped` as "no active applicable rule". Letting an inactive property
    land in the same counter would put two causes in one number — the very overloading
    D9's refinement paragraph rejects when it argues for a separate `failed`. Raised by
    the section-5 architecture panel.
    """
    await a_rule(flow, world, property_id=world.property.id)
    world.property.status = PropertyStatus.INACTIVE
    await db_session.flush()

    with pytest.raises(PricingValidationError) as error:
        await flow.generate.execute(
            world.tenant.id, now=NOW, property_id=world.property.id
        )

    assert error.value.field == "property_id"
    assert "ACTIVE" in str(error.value)
    # And the message differs from the foreign/unknown one, which is not an oracle: an
    # inactive property is the caller's own, so naming it reveals nothing across tenants.
    assert "does not name a property of this tenant" not in str(error.value)


async def test_the_sweep_prices_the_active_portfolio_and_ignores_the_rest(
    flow, world, db_session
) -> None:
    """The sweep's scope *is* the active portfolio, so an inactive flat never enters it
    and is never counted — the other half of the symmetry above."""
    await a_rule(flow, world)
    world.second_property.status = PropertyStatus.INACTIVE
    await db_session.flush()
    inactive = world.second_property.id

    outcome = await flow.generate.execute(world.tenant.id, now=NOW)

    assert outcome == GenerationOutcome(created=60)
    assert await horizon_rows(db_session, inactive) == []


# --- 5.4 Idempotence and the untouchable human decision -----------------------------


async def test_two_runs_in_a_row_neither_duplicate_rows_nor_fail_against_the_unique(
    flow, world, db_session
) -> None:
    """R4.2: the `UNIQUE (property_id, date)` decides, not a prior read."""
    await a_rule(flow, world, property_id=world.property.id)

    first = await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    second = await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    assert first == GenerationOutcome(created=60)
    assert second == GenerationOutcome(updated=60)
    assert len(await horizon_rows(db_session, world.property.id)) == 60


async def test_an_approved_recommendation_survives_a_regeneration_intact(
    flow, world, db_session
) -> None:
    """R4.3: a nightly job does not undo a human decision."""
    rule = await a_rule(flow, world, property_id=world.property.id)
    approved = await seed_recommendation(
        db_session,
        world,
        rule,
        day=TODAY + timedelta(days=1),
        price="777.00",
        status=PriceRecommendationStatus.APPROVED,
    )
    await db_session.commit()

    outcome = await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    await db_session.refresh(approved)
    assert outcome.preserved == 1
    assert outcome.created == 59
    assert approved.recommended_price == Decimal("777.00")
    assert approved.explanation == "seeded"
    assert approved.status is PriceRecommendationStatus.APPROVED


async def test_a_rejected_recommendation_is_regenerated_and_stays_rejected(
    flow, world, db_session
) -> None:
    """D9: rejecting yesterday's proposal is not an instruction never to propose again —
    but it is also not an approval, so the status does not quietly reset."""
    rule = await a_rule(flow, world, property_id=world.property.id)
    rejected = await seed_recommendation(
        db_session,
        world,
        rule,
        day=TODAY + timedelta(days=1),
        price="777.00",
        status=PriceRecommendationStatus.REJECTED,
    )
    await db_session.commit()

    outcome = await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    await db_session.refresh(rejected)
    assert outcome.updated == 1
    assert outcome.preserved == 0
    assert rejected.recommended_price == Decimal("100.00")
    assert rejected.status is PriceRecommendationStatus.REJECTED


async def test_a_property_without_an_applicable_rule_is_skipped_without_failing(
    flow, world, db_session
) -> None:
    """R4.6: a tenant that has written no rules yet finishes green."""
    outcome = await flow.generate.execute(world.tenant.id, now=NOW)

    assert outcome == GenerationOutcome(skipped=2)
    assert await horizon_rows(db_session, world.property.id) == []


async def test_a_tenant_wide_rule_prices_every_property_without_one_of_its_own(
    flow, world, db_session
) -> None:
    """R1.5, resolved by the generator through `resolve_rule`."""
    await a_rule(flow, world)

    outcome = await flow.generate.execute(world.tenant.id, now=NOW)

    assert outcome == GenerationOutcome(created=120)
    assert len(await horizon_rows(db_session, world.second_property.id)) == 60


# --- 5.5 The previous price is the persisted one ------------------------------------


async def test_the_daily_cap_measures_against_the_persisted_price_of_the_day_before(
    flow, world, db_session
) -> None:
    """D4, the decision the proposal did not anticipate.

    Day 1 is approved at 120 and today's recalculation "would have" put it at 90. Day 2
    must therefore be capped against **120** — `120 * 0.80 = 96` — because otherwise the
    two rows that actually exist side by side would violate the very cap R3.2 protects.
    """
    rule = await a_rule(
        flow,
        world,
        property_id=world.property.id,
        base_price=Decimal("90.00"),
        min_price=Decimal("10.00"),
    )
    await seed_recommendation(
        db_session,
        world,
        rule,
        day=TODAY + timedelta(days=1),
        price="120.00",
        status=PriceRecommendationStatus.APPROVED,
    )
    await db_session.commit()

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    rows = await horizon_rows(db_session, world.property.id)
    assert rows[0].recommended_price == Decimal("120.00")
    assert rows[1].recommended_price == Decimal("96.00")
    assert "max_daily_change_pct" in rows[1].explanation
    # Day 3 chains off day 2's own calculated price, back down towards the base.
    assert rows[2].recommended_price == Decimal("90.00")


# --- 5.6 The timeline -----------------------------------------------------------------


async def test_only_new_recommendations_reach_the_timeline(
    flow, world, db_session
) -> None:
    """D14: 60 events the first time, one a day after that — never one per update."""
    await a_rule(flow, world, property_id=world.property.id)

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    first_run = await timeline_rows(
        db_session, world.property.id, TimelineEventType.PRICE_RECOMMENDATION_CREATED
    )

    await flow.generate.execute(
        world.tenant.id, now=NOW + timedelta(days=1), property_id=world.property.id
    )
    after_second_run = await timeline_rows(
        db_session, world.property.id, TimelineEventType.PRICE_RECOMMENDATION_CREATED
    )

    assert len(first_run) == 60
    # 59 of the second run's days already existed; only the far end of the horizon is new.
    assert len(after_second_run) == 61


async def test_the_created_event_carries_exactly_four_identifiers(
    flow, world, db_session
) -> None:
    """The other half of "no se propaga", asserted on the **constructed event**.

    `TimelineEventFactory` checks only that `metadata` is a `dict` — no key allowlist — and
    `timeline_events` is append-only, so nothing that lands there can be redacted later.
    The exact key set is what catches `metadata=asdict(recommendation)` or a `{k: v}` loop,
    both of which would carry the rendered text with every "not equal to the fixture"
    assertion still green. The source-level test in `test_free_text_sink_contract.py` says
    in as many words that it does not reach these shapes.
    """
    rule = await a_rule(flow, world, property_id=world.property.id)

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    events = await timeline_rows(
        db_session, world.property.id, TimelineEventType.PRICE_RECOMMENDATION_CREATED
    )
    payload = events[0].metadata_
    assert set(payload) == {"recommendation_id", "date", "recommended_price", "pricing_rule_id"}
    assert payload["pricing_rule_id"] == str(rule.id)


async def test_the_job_signs_its_events_as_the_scheduler_and_the_endpoint_as_the_user(
    flow, world, db_session
) -> None:
    """D14: `TimelineEventFactory` takes `actor_user_id` only alongside `USER`, so the row
    cannot claim a person who was not there."""
    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    await a_rule(flow, world, property_id=world.second_property.id, name="Second")
    await flow.generate.execute(
        world.tenant.id,
        now=NOW,
        property_id=world.second_property.id,
        actor=actor_of(world),
    )

    from_job = await timeline_rows(
        db_session, world.property.id, TimelineEventType.PRICE_RECOMMENDATION_CREATED
    )
    from_endpoint = await timeline_rows(
        db_session, world.second_property.id, TimelineEventType.PRICE_RECOMMENDATION_CREATED
    )

    assert all(row.actor_type is TimelineActorType.SCHEDULER for row in from_job)
    assert all(row.actor_user_id is None for row in from_job)
    assert all(row.actor_type is TimelineActorType.USER for row in from_endpoint)
    assert all(row.actor_user_id == world.manager.id for row in from_endpoint)


# --- 5.7 The generation writes no audit row -----------------------------------------


async def test_the_nightly_generation_writes_no_audit_row(flow, world, db_session) -> None:
    """D12/OQ1, the fifth named exception of rule 9 — bounded to exactly the clock.

    The trail of an unattended generation is the `TimelineEvent` of each new recommendation
    plus the run's own report, and that is what task 8.1 writes into `steering/security.md`.
    The exemption is a consequence of the mechanism rather than a carve-out: `_AuditWriter`
    is only called when somebody is acting, and here nobody is.
    """
    await a_rule(flow, world, property_id=world.property.id)

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    assert (
        await audit_rows(db_session, world.tenant.id, audit_actions.ENTITY_PRICE_RECOMMENDATION)
        == []
    )
    assert (
        await audit_rows(db_session, world.tenant.id, audit_actions.ENTITY_PROPERTY) == []
    )


async def test_a_generation_a_person_asked_for_is_audited_once_per_property(
    flow, world, db_session
) -> None:
    """The half OQ1 should never have exempted (design D12/OQ1, narrowed 2026-08-17).

    OQ1 exempted both paths on the ground of «ausencia de actor». That is true of the clock
    and false of `POST /generate`, which receives a `user_id` **and** an `ip` — and this same
    section signs those timeline rows `TimelineActorType.USER` precisely because a person is
    present. Rule 9's second and third exceptions say in as many words that they «no exime la
    lectura con actor humano o iniciada por API».

    Without the row, a manager could press generate repeatedly and rewrite prices leaving no
    trace in either sink: a repeat run over a full horizon inserts nothing, so D14 emits no
    timeline row, and the manual path carries no lock.
    """
    await a_rule(flow, world)  # tenant-wide: two properties in the sweep

    await flow.generate.execute(world.tenant.id, now=NOW, actor=actor_of(world))

    rows = await audit_rows(db_session, world.tenant.id, audit_actions.ENTITY_PROPERTY)
    generated = [
        row for row in rows
        if row.action == audit_actions.PRICE_RECOMMENDATIONS_GENERATED
    ]
    assert {row.entity_id for row in generated} == {
        world.property.id,
        world.second_property.id,
    }
    assert all(row.actor_user_id == world.manager.id for row in generated)
    assert all(row.actor_ip == "10.0.0.1" for row in generated)
    # No diff: the audited fact is "she repriced this property", and the counts are in the
    # response. A `changes` payload would also be a second place for the numbers to live.
    assert all(not row.changes for row in generated)
    # And still nothing on the recommendations themselves — the exemption that survives.
    assert (
        await audit_rows(db_session, world.tenant.id, audit_actions.ENTITY_PRICE_RECOMMENDATION)
        == []
    )


# --- 5.8 Reading and deciding --------------------------------------------------------


async def test_recommendations_are_listed_within_the_tenant_and_its_filters(
    flow, world, db_session
) -> None:
    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    ours = await flow.list_recommendations.execute(
        world.tenant.id,
        PriceRecommendationFilters(
            property_id=world.property.id,
            date_from=TODAY + timedelta(days=1),
            date_to=TODAY + timedelta(days=7),
        ),
        page=1,
        per_page=50,
    )
    theirs = await flow.list_recommendations.execute(
        world.other_tenant.id, PriceRecommendationFilters(), page=1, per_page=50
    )

    assert ours.total == 7
    assert theirs.total == 0


async def test_approving_a_recommendation_records_the_decision(
    flow, world, db_session
) -> None:
    """R5.2 — one action for both outcomes, with the outcome in the diff (D12)."""
    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    target = (await horizon_rows(db_session, world.property.id))[0]

    decided = await flow.decide.execute(
        world.tenant.id,
        target.id,
        PriceRecommendationStatus.APPROVED,
        actor=actor_of(world),
        now=NOW,
    )

    assert decided.status is PriceRecommendationStatus.APPROVED
    rows = await audit_rows(
        db_session, world.tenant.id, audit_actions.ENTITY_PRICE_RECOMMENDATION
    )
    assert [row.action for row in rows] == [audit_actions.PRICE_RECOMMENDATION_DECIDED]
    assert rows[0].changes == {"status": {"old": "RECOMMENDED", "new": "APPROVED"}}
    assert rows[0].actor_user_id == world.manager.id


async def test_marking_a_price_applied_externally_is_a_fact_of_the_world_not_a_decision(
    flow, world, db_session
) -> None:
    """R5.3: its own audit action **and** the timeline event that says a human published."""
    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    target = (await horizon_rows(db_session, world.property.id))[0]
    await flow.decide.execute(
        world.tenant.id, target.id, PriceRecommendationStatus.APPROVED,
        actor=actor_of(world), now=NOW,
    )

    await flow.decide.execute(
        world.tenant.id,
        target.id,
        PriceRecommendationStatus.APPLIED_EXTERNAL,
        actor=actor_of(world),
        now=NOW,
    )

    actions = [
        row.action
        for row in await audit_rows(
            db_session, world.tenant.id, audit_actions.ENTITY_PRICE_RECOMMENDATION
        )
    ]
    events = await timeline_rows(
        db_session, world.property.id, TimelineEventType.PRICE_UPDATED_EXTERNAL
    )
    assert sorted(actions) == sorted(
        [
            audit_actions.PRICE_RECOMMENDATION_DECIDED,
            audit_actions.PRICE_RECOMMENDATION_APPLIED_EXTERNAL,
        ]
    )
    assert len(events) == 1
    assert set(events[0].metadata_) == {"recommendation_id", "date", "recommended_price"}


@pytest.mark.parametrize(
    "target_status",
    [
        PriceRecommendationStatus.APPLIED_EXTERNAL,
        PriceRecommendationStatus.DRAFT,
        PriceRecommendationStatus.RECOMMENDED,
    ],
)
async def test_an_illegal_transition_leaves_the_status_intact(
    flow, world, db_session, target_status
) -> None:
    """R5.4 — `409` and nothing moves. `DRAFT` is in the enum and reachable from nowhere."""
    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    target = (await horizon_rows(db_session, world.property.id))[0]

    with pytest.raises(InvalidRecommendationTransitionError):
        await flow.decide.execute(
            world.tenant.id, target.id, target_status, actor=actor_of(world), now=NOW
        )

    await db_session.refresh(target)
    assert target.status is PriceRecommendationStatus.RECOMMENDED


async def test_a_recommendation_of_another_tenant_is_not_found(flow, world, db_session) -> None:
    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    target = (await horizon_rows(db_session, world.property.id))[0]

    with pytest.raises(PriceRecommendationNotFoundError):
        await flow.decide.execute(
            world.other_tenant.id,
            target.id,
            PriceRecommendationStatus.APPROVED,
            actor=PricingActor(user_id=world.other_manager.id),
            now=NOW,
        )


async def test_no_transition_ever_touches_the_pms(flow, world, db_session, monkeypatch) -> None:
    """R5.5, Mode 1 of PRD §19: the system recommends, a human publishes.

    Two nets, because either alone is weak. The spy catches a call made through the
    adapter at runtime; the import scan catches the wiring that would make one possible at
    all — which is the honest one, since these use cases take no PMS port to spy on. If a
    future change injects one, the spy is already waiting.
    """
    from app.integrations.infrastructure.mock_pms import MockPMSAdapter
    from app.integrations.infrastructure.pms_factory import SqlAlchemyPMSAdapterFactory

    def refuse(*_args, **_kwargs):
        raise AssertionError("pricing reached the PMS; Mode 1 never does (R5.5)")

    for owner, name in (
        (MockPMSAdapter, "list_reservations"),
        (MockPMSAdapter, "get_reservation"),
        (SqlAlchemyPMSAdapterFactory, "reservations_for"),
        (SqlAlchemyPMSAdapterFactory, "messaging_for"),
    ):
        monkeypatch.setattr(owner, name, refuse)

    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    target = (await horizon_rows(db_session, world.property.id))[0]
    await flow.decide.execute(
        world.tenant.id, target.id, PriceRecommendationStatus.APPROVED,
        actor=actor_of(world), now=NOW,
    )
    await flow.decide.execute(
        world.tenant.id, target.id, PriceRecommendationStatus.APPLIED_EXTERNAL,
        actor=actor_of(world), now=NOW,
    )

    await db_session.refresh(target)
    # `current_price` has no source while `get_availability` does not exist (D19), and the
    # column is nullable in PRD §7.18 precisely for that reason.
    assert target.current_price is None


async def test_the_pricing_module_does_not_import_the_pms_at_all() -> None:
    """The structural half of R5.5, which does not depend on a call being made.

    `async` with nothing to await: this file carries a module-wide `pytest.mark.asyncio`
    (the suite is not in auto mode), and a sync test under it is a collection warning.
    """
    offenders = []
    for path in (APP_ROOT / "pricing").glob("**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(name.startswith("app.integrations") for name in names):
                offenders.append(path.relative_to(APP_ROOT).as_posix())

    assert not offenders, offenders


# --- The failure paths the first pass left unpinned ----------------------------------
#
# Every test below answers a finding of the feature-scale QA panel of `/sdd:review`
# panel of `/sdd:review` on 2026-08-17. They share one theme: the generator's guarantees
# under failure and concurrency were carried by prose and by one test whose failure landed
# in pure domain code, before the property had issued a single statement — so the
# session-level machinery those guarantees rest on was never exercised at all.


def a_generator(flow, *, uow=None, recommendations=None, timeline=None, notifications=None):
    """The generator rewired, so a test can substitute exactly one collaborator."""
    from app.core.unit_of_work import SqlAlchemyUnitOfWork
    from app.pricing.application.use_cases import GeneratePriceRecommendationsUseCase
    from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
    from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository

    return GeneratePriceRecommendationsUseCase(
        rules=flow.rules,
        recommendations=recommendations or flow.recommendations,
        properties=flow.properties,
        reservations=SqlAlchemyReservationRepository(flow.session),
        timeline=timeline or flow.timeline,
        audit=flow.audit,
        users=flow.users,
        notifications=notifications or flow.notifications,
        tenant_configs=SqlAlchemyTenantConfigRepository(flow.session),
        uow=uow or SqlAlchemyUnitOfWork(flow.session),
    )


class _Delegating:
    """Everything the real collaborator does, except what a subclass overrides."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def a_broken_rule(db_session, world, property_id, name="Broken"):
    """A rule row as it would exist if written before task 2.2's validator: a **string**
    threshold, which `calculate_price` compares as a bare `int` and dies on."""
    db_session.add(
        PricingRuleModel(
            id=uuid.uuid4(),
            tenant_id=world.tenant.id,
            property_id=property_id,
            name=name,
            base_price=Decimal("100.00"),
            min_price=Decimal("50.00"),
            max_price=Decimal("200.00"),
            max_daily_change_pct=Decimal("20.00"),
            lead_time_rules=[{"days_before": "3", "modifier_pct": 10}],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await db_session.flush()


async def test_a_real_database_error_does_not_take_the_rest_of_the_portfolio_with_it(
    flow, world, db_session
) -> None:
    """The rollback at the heart of D9's "the loop carries on", finally load-bearing.

    The existing failure test fails inside `calculate_price` — pure domain code, **before**
    the property issues any statement — so the session stays clean and the rollback is a
    no-op: deleting it left the whole suite green. This one fails at the database, which is
    the case D9 argues from ("a failure inside the upsert leaves the session unusable"), and
    it is the one that goes red without the rollback: without it, property two's statements
    raise `InFailedSQLTransactionError` and its horizon is never written.

    `REDES11` sorts before `REDES12` (promised by `PropertyRepository.list_by_status`), so
    the *first* property is the one that breaks here — the harder direction.
    """
    from sqlalchemy import text

    class _FailsAtTheDatabase(_Delegating):
        def __init__(self, inner, session, failing_property_id) -> None:
            super().__init__(inner)
            self._session = session
            self._failing = failing_property_id

        async def upsert_many(self, tenant_id, recommendations):
            if recommendations and recommendations[0].property_id == self._failing:
                # A genuine statement failure, so the session really is unusable
                # afterwards — which a raised Python exception would not achieve.
                await self._session.execute(text("SELECT 1 / 0"))
            return await self._inner.upsert_many(tenant_id, recommendations)

    await a_rule(flow, world)  # tenant-wide, so both properties are priced
    await db_session.commit()
    broken, healthy = world.property.id, world.second_property.id
    generator = a_generator(
        flow, recommendations=_FailsAtTheDatabase(flow.recommendations, db_session, broken)
    )

    outcome = await generator.execute(world.tenant.id, now=NOW)

    assert (outcome.failed, outcome.created) == (1, 60)
    assert await horizon_rows(db_session, broken) == []
    assert len(await horizon_rows(db_session, healthy)) == 60


async def test_a_failure_after_the_upsert_discards_that_propertys_rows_too(
    flow, world, db_session
) -> None:
    """The window between the upsert and the commit, which no test reached.

    D9 puts one transaction around each property, so a failure while the timeline events
    are being written must discard that property's 60 rows as well — a horizon committed
    without its `PRICE_RECOMMENDATION_CREATED` events would be invisible on the timeline
    for ever (R4.4, and `timeline_events` is append-only so it cannot be backfilled
    honestly).
    """
    class _FailsMidTimeline(_Delegating):
        def __init__(self, inner, failing_property_id) -> None:
            super().__init__(inner)
            self._failing = failing_property_id
            self.added = 0

        async def add(self, tenant_id, event):
            if event.property_id == self._failing:
                self.added += 1
                if self.added == 30:
                    raise RuntimeError("the timeline write failed halfway")
            return await self._inner.add(tenant_id, event)

    await a_rule(flow, world)
    await db_session.commit()
    broken, healthy = world.property.id, world.second_property.id
    generator = a_generator(flow, timeline=_FailsMidTimeline(flow.timeline, broken))

    outcome = await generator.execute(world.tenant.id, now=NOW)

    assert (outcome.failed, outcome.created) == (1, 60)
    assert await horizon_rows(db_session, broken) == []
    assert (
        await timeline_rows(
            db_session, broken, TimelineEventType.PRICE_RECOMMENDATION_CREATED
        )
        == []
    )
    assert len(await horizon_rows(db_session, healthy)) == 60


class _RollbackFails:
    """A unit of work whose abandon fails — the correlated half of a dropped connection."""

    def __init__(self, session) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        raise RuntimeError("rollback failed: connection is gone")


async def test_a_rollback_that_itself_fails_still_returns_a_report(
    flow, world, db_session
) -> None:
    """`execute` must not raise instead of reporting.

    A dropped connection is the most likely cause of **both** the original failure and of
    the rollback's, so the two are correlated rather than independent. An unguarded
    `rollback()` inside the handler propagates, and the caller then gets an exception in
    place of the `GenerationOutcome` whose `failed` counter exists precisely so a sweep with
    a hole in it cannot be mistaken for a green one.

    The failure is a **real statement failure**, not a `TypeError` in pure domain code: the
    QA panel pointed out on re-review that a domain-level failure leaves the session clean,
    so the test would pin only "the exception does not escape" and not "the session really
    could not be abandoned". Both properties carry a rule here, so both are `failed`.
    """
    from sqlalchemy import text

    class _FailsAtTheDatabase(_Delegating):
        def __init__(self, inner, session) -> None:
            super().__init__(inner)
            self._session = session

        async def upsert_many(self, tenant_id, recommendations):
            await self._session.execute(text("SELECT 1 / 0"))
            return await self._inner.upsert_many(tenant_id, recommendations)

    await a_rule(flow, world)  # tenant-wide, so both properties resolve a rule
    await db_session.commit()
    generator = a_generator(
        flow,
        uow=_RollbackFails(db_session),
        recommendations=_FailsAtTheDatabase(flow.recommendations, db_session),
    )

    outcome = await generator.execute(world.tenant.id, now=NOW)

    assert outcome == GenerationOutcome(failed=2)


async def test_an_unreachable_property_without_a_rule_is_skipped_not_failed(
    flow, world, db_session
) -> None:
    """R4.6: `skipped` means one thing — no active applicable rule — and only that.

    When the session cannot be abandoned the sweep stops, so the properties it never
    reached have to be reported without being visited. Counting them all as `failed` would
    page an operator about a property that was never going to be priced — the same
    overloading of one counter with two causes that D9's refinement paragraph rejects when
    it argues for `failed` existing separately from `skipped`. `resolve_rule` is pure over a
    list already in memory, so the tail can be classified without a query.

    `REDES11` carries the only rule and sorts first, so it is the one that breaks;
    `REDES12` has no rule and is never reached. Raised by the QA panel on re-review.
    """
    from sqlalchemy import text

    class _FailsAtTheDatabase(_Delegating):
        def __init__(self, inner, session) -> None:
            super().__init__(inner)
            self._session = session

        async def upsert_many(self, tenant_id, recommendations):
            await self._session.execute(text("SELECT 1 / 0"))
            return await self._inner.upsert_many(tenant_id, recommendations)

    await a_rule(flow, world, property_id=world.property.id)
    await db_session.commit()
    generator = a_generator(
        flow,
        uow=_RollbackFails(db_session),
        recommendations=_FailsAtTheDatabase(flow.recommendations, db_session),
    )

    outcome = await generator.execute(world.tenant.id, now=NOW)

    assert outcome == GenerationOutcome(failed=1, skipped=1)


async def test_the_generator_refuses_a_unit_of_work_it_cannot_abandon(flow) -> None:
    """The docstring said it; the suite asserted the opposite.

    `CallerOwnedUnitOfWork.rollback()` is deliberately empty, so composing this generator
    under it turns "abandon and carry on" into "keep and carry on" — the panel measured
    `created=0, failed=2` with the rows of the failure committed. Prose was the only
    barrier, and `tests/test_unit_of_work.py` pins the two adapters as substitutable for
    the port (which they are, for every other use case). This is the barrier.
    """
    from app.core.unit_of_work import CallerOwnedUnitOfWork

    with pytest.raises(TypeError) as error:
        a_generator(flow, uow=CallerOwnedUnitOfWork())

    assert "abandon" in str(error.value)


async def test_a_concurrent_insert_never_puts_a_dangling_id_on_the_timeline(
    flow, world, db_session
) -> None:
    """R4.4/D14: the events come from the statement, not from the pre-read.

    A row that appears between the pre-read and the upsert takes the `ON CONFLICT DO UPDATE`
    branch, and `DO UPDATE` never sets `id` — so the stored row keeps its own while the
    entity still carries the one it was built with. Emitting from the pre-read's "absent"
    list would write a `recommendation_id` that no row carries, **permanently**, because
    `timeline_events` is append-only. The manual path has no lock at all, so this is not an
    exotic case.
    """
    rule = await a_rule(flow, world, property_id=world.property.id)
    contested = TODAY + timedelta(days=1)

    class _AConcurrentRunInsertsAfterTheRead(_Delegating):
        def __init__(self, inner, session) -> None:
            super().__init__(inner)
            self._session = session
            self._done = False

        async def list_for_property_range(self, *args, **kwargs):
            rows = await self._inner.list_for_property_range(*args, **kwargs)
            if not self._done:
                self._done = True
                await seed_recommendation(
                    self._session,
                    world,
                    rule,
                    day=contested,
                    price="333.00",
                    status=PriceRecommendationStatus.RECOMMENDED,
                )
            return rows

    generator = a_generator(
        flow,
        recommendations=_AConcurrentRunInsertsAfterTheRead(flow.recommendations, db_session),
    )

    outcome = await generator.execute(
        world.tenant.id, now=NOW, property_id=world.property.id
    )

    rows = await horizon_rows(db_session, world.property.id)
    events = await timeline_rows(
        db_session, world.property.id, TimelineEventType.PRICE_RECOMMENDATION_CREATED
    )
    # The contested day was updated, not created, and got no event.
    assert (outcome.created, outcome.updated) == (59, 1)
    assert len(events) == 59
    # The assertion the old shape failed: every id on the timeline is an id in the table.
    existing_ids = {str(row.id) for row in rows}
    assert {event.metadata_["recommendation_id"] for event in events} <= existing_ids
    assert contested not in {
        row.date for row in rows if str(row.id) in
        {event.metadata_["recommendation_id"] for event in events}
    }


@pytest.mark.parametrize(
    "decided_status",
    [PriceRecommendationStatus.APPROVED, PriceRecommendationStatus.APPLIED_EXTERNAL],
)
async def test_an_approval_landing_after_the_pre_read_is_still_preserved(
    flow, world, db_session, decided_status
) -> None:
    """R4.3 «preservarla intacta» — closed in the statement, not in the read.

    The pre-read used to be the *only* thing enforcing `PRESERVED_STATUSES`, and it is stale
    by construction: the QA panel reproduced a manager approving day+1 at `777.00` mid-sweep
    and the upsert rewriting the price to `100.00`. The status survived (it was never in the
    `set_`); the approved **price** did not. And because the generation is audit-exempt (D12)
    and updates emit no timeline event (D14), the overwrite left no trace in either sink — on
    a row a human had decided.

    The job's lock never helped: it serialises generators against each other, never against
    a person clicking Approve mid-run.
    """
    rule = await a_rule(flow, world, property_id=world.property.id)
    contested = TODAY + timedelta(days=1)

    class _AHumanDecidesAfterTheRead(_Delegating):
        def __init__(self, inner, session) -> None:
            super().__init__(inner)
            self._session = session
            self._done = False

        async def list_for_property_range(self, *args, **kwargs):
            rows = await self._inner.list_for_property_range(*args, **kwargs)
            if not self._done:
                self._done = True
                await seed_recommendation(
                    self._session, world, rule,
                    day=contested, price="777.00", status=decided_status,
                )
            return rows

    generator = a_generator(
        flow, recommendations=_AHumanDecidesAfterTheRead(flow.recommendations, db_session)
    )

    outcome = await generator.execute(
        world.tenant.id, now=NOW, property_id=world.property.id
    )

    rows = await horizon_rows(db_session, world.property.id)
    decided = next(row for row in rows if row.date == contested)
    assert decided.recommended_price == Decimal("777.00")
    assert decided.explanation == "seeded"
    assert decided.status is decided_status
    # Reported as preserved, not as updated — and the day still lands in exactly one counter.
    assert (outcome.created, outcome.updated, outcome.preserved) == (59, 0, 1)
    # No timeline event for a day nobody created (D14).
    events = await timeline_rows(
        db_session, world.property.id, TimelineEventType.PRICE_RECOMMENDATION_CREATED
    )
    assert len(events) == 59


async def test_the_statements_preserved_set_matches_the_use_cases(flow) -> None:
    """The guarantee is only as good as its narrower half, so the two lists must agree.

    `application/` keeps `PRESERVED_STATUSES` for its pre-read and `infrastructure/` keeps
    `_STATUSES_A_HUMAN_DECIDED` for the conflict predicate — two copies, because
    `infrastructure/` may not depend on `application/`. Two copies can drift, and a drift
    that widened the pre-read while leaving the statement narrow would restore exactly the
    R4.3 hole this guard exists to close, silently.
    """
    from app.pricing.application.use_cases import PRESERVED_STATUSES
    from app.pricing.infrastructure.repositories import _STATUSES_A_HUMAN_DECIDED

    assert frozenset(_STATUSES_A_HUMAN_DECIDED) == PRESERVED_STATUSES


@pytest.mark.parametrize("seed_status", [None, PriceRecommendationStatus.APPROVED])
async def test_every_day_of_the_horizon_is_accounted_for_in_exactly_one_counter(
    flow, world, db_session, seed_status
) -> None:
    """The invariant no test asserted: `created + updated + preserved == HORIZON_DAYS`.

    It is what catches a horizon quietly coming out 59 long — the shape the QA panel showed
    the counters could take without a single assertion going red.
    """
    from app.pricing.domain.constants import HORIZON_DAYS

    rule = await a_rule(flow, world, property_id=world.property.id)
    if seed_status is not None:
        await seed_recommendation(
            db_session, world, rule,
            day=TODAY + timedelta(days=1), price="777.00", status=seed_status,
        )
    await db_session.commit()

    first = await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    second = await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    for outcome in (first, second):
        assert outcome.created + outcome.updated + outcome.preserved == HORIZON_DAYS
        assert outcome.failed == 0
    assert len(await horizon_rows(db_session, world.property.id)) == HORIZON_DAYS


async def test_two_adjacent_persisted_rows_can_break_the_daily_cap_when_one_is_preserved(
    flow, world, db_session
) -> None:
    """The limit R4.3 imposes on R3.2, pinned instead of assumed.

    Task 5.5 and the code both claimed "dos filas contiguas nunca violan el tope diario
    entre sí". They cannot: the cap is enforced **forward** only, and R4.3 forbids adjusting
    the preserved neighbour, so the pair *(recalculated, preserved)* is structurally
    unconstrained — R4.3 outranks R3.2 at that boundary, deliberately (design D4).

    `test_the_daily_cap_measures_against_the_persisted_price_of_the_day_before` covers the
    direction that *does* hold (preserved → recalculated). This is the one that does not.
    """
    rule = await a_rule(
        flow, world,
        property_id=world.property.id,
        min_price=Decimal("10.00"),
        max_price=Decimal("500.00"),
    )
    for offset, price in ((1, "200.00"), (3, "300.00"), (5, "120.00")):
        await seed_recommendation(
            db_session, world, rule,
            day=TODAY + timedelta(days=offset), price=price,
            status=PriceRecommendationStatus.APPROVED,
        )
    await db_session.commit()

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    rows = await horizon_rows(db_session, world.property.id)
    prices = [row.recommended_price for row in rows[:6]]
    # Days +1/+3/+5 are the untouched approvals; +2/+4/+6 are capped against the approval
    # *before* them, which is the half that works.
    assert prices == [
        Decimal("200.00"),  # approved, preserved
        Decimal("160.00"),  # 200 - 20%
        Decimal("300.00"),  # approved, preserved  <- +87.5% off 160, uncapped
        Decimal("240.00"),  # 300 - 20%
        Decimal("120.00"),  # approved, preserved  <- -50% off 240, uncapped
        Decimal("100.00"),  # within 20% of 120, so the base price stands
    ]
    cap = rule.max_daily_change_pct / Decimal("100")
    breaches = [
        (before, after)
        for before, after in zip(prices, prices[1:])
        if abs(after - before) > before * cap
    ]
    # Named rather than tolerated: two breaches, both landing *on* a preserved row.
    assert breaches == [
        (Decimal("160.00"), Decimal("300.00")),
        (Decimal("240.00"), Decimal("120.00")),
    ]


async def test_the_left_edge_of_the_horizon_is_repriced_without_a_cap_every_run(
    flow, world, db_session
) -> None:
    """R3.3 read as «no base exists *in this horizon*» (design D4).

    Every run starts with `previous_price=None`, so the row for the day *before* the horizon
    — written by yesterday's run, possibly `APPROVED` — is never a reference. R3.3 sanctions
    it literally («primer día del horizonte → no aplicar el tope diario»), and D4 rejects the
    alternative on purpose: chaining against the stored previous day would make every run
    depend on the last, so a rule correction would take sixty days to land.

    Pinned rather than left to prose, because the trade-off is invisible in the code: a
    future change that "fixed" the discontinuity by chaining would pass the whole suite
    silently while breaking what D4 says. Flagged by the QA panel on re-review.
    """
    rule = await a_rule(
        flow, world,
        property_id=world.property.id,
        min_price=Decimal("10.00"),
        max_price=Decimal("900.00"),
    )
    # Yesterday's horizon left an approved price on what is now the day *before* the first
    # day this run prices — outside `[execution_date + 1, execution_date + 60]`.
    await seed_recommendation(
        db_session, world, rule,
        day=TODAY, price="800.00", status=PriceRecommendationStatus.APPROVED,
    )
    await db_session.commit()

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    rows = await horizon_rows(db_session, world.property.id)
    edge = next(row for row in rows if row.date == TODAY + timedelta(days=1))
    # 800 → 100 is −87.5%, far outside the rule's ±20%, and deliberately uncapped: the 800
    # is not in this horizon, so R3.3 says there is no base to measure against.
    assert edge.recommended_price == Decimal("100.00")
    assert "max_daily_change_pct" not in edge.explanation


# --- R4: the recommendation reaches whoever approves it --------------------------------


async def _price_rows(db_session, tenant_id) -> list:
    from sqlalchemy import select

    from app.notifications.infrastructure.models import NotificationLogModel

    rows = await db_session.execute(
        select(NotificationLogModel).where(
            NotificationLogModel.tenant_id == tenant_id,
            NotificationLogModel.notification_type == "PRICE_RECOMMENDATION",
        )
    )
    return list(rows.scalars())


async def test_a_run_that_creates_sixty_recommendations_writes_one_row_per_recipient(
    flow, world, db_session
) -> None:
    """R4.1/R4.2 — the cifra the requirement is built on.

    A property's first run creates the whole sixty-day horizon. One row per recommendation
    would be sixty notifications for one fact; R4.2 says count only what the statement
    declared inserted, and write per property and execution.
    """
    await a_rule(flow, world, property_id=world.property.id)

    outcome = await flow.generate.execute(
        world.tenant.id, now=NOW, property_id=world.property.id
    )

    assert outcome.created == 60
    rows = await _price_rows(db_session, world.tenant.id)
    # One per recipient (manager + owner), not one per recommendation.
    assert len(rows) == 2
    assert {row.related_id for row in rows} == {world.property.id}
    assert all(row.related_type == "property" for row in rows)
    assert all(row.sla_deadline_at is None for row in rows)


async def test_a_run_fans_out_across_the_tenants_enabled_channels(
    flow, world, db_session
) -> None:
    """notification-channel-routing R1, R2 — the price-recommendation writer, exercised
    through the real use case → resolver → `dispatch_and_persist` path, not just the
    pure `channel_dispatch.py` unit tests."""
    from sqlalchemy import select

    from app.notifications.domain.enums import NotificationChannel
    from app.tenants.infrastructure.models import TenantConfigModel

    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == world.tenant.id)
        )
    ).scalar_one()
    config.notification_email_enabled = True
    config.notification_whatsapp_enabled = True
    world.manager.phone = "+34600000003"
    db_session.add(world.manager)
    await db_session.flush()

    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    rows = await _price_rows(db_session, world.tenant.id)
    manager_rows = {row.channel: row for row in rows if row.recipient_user_id == world.manager.id}
    assert set(manager_rows) == {
        NotificationChannel.IN_APP,
        NotificationChannel.EMAIL,
        NotificationChannel.WHATSAPP,
    }
    assert manager_rows[NotificationChannel.WHATSAPP].recipient_contact == world.manager.phone
    assert all(row.sla_deadline_at is None for row in rows)


async def test_the_recipients_are_the_union_of_managers_and_owners(
    flow, world, db_session
) -> None:
    """R4.4 — **not** R5.1's fallback, and this is the one writer where that differs.

    Everywhere else the owner hears only when there is no manager. Here she approves the
    price, so dropping her because a manager exists would take the decision away from the
    person whose money it is. Both roles hold `MANAGE_PRICE_RECOMMENDATIONS`.
    """
    await a_rule(flow, world, property_id=world.property.id)

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    rows = await _price_rows(db_session, world.tenant.id)
    assert {row.recipient_user_id for row in rows} == {world.manager.id, world.owner.id}


async def test_a_second_run_that_only_updates_announces_nothing(
    flow, world, db_session
) -> None:
    """R4.2/R4.3 — `written.inserted` is empty, so there is nothing new to announce.

    This is the steady state on the day after a property's first run over an unchanged
    horizon: sixty updates, zero creations. A notification here would be a daily ping about
    prices nobody changed.
    """
    await a_rule(flow, world, property_id=world.property.id)
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    before = len(await _price_rows(db_session, world.tenant.id))

    outcome = await flow.generate.execute(
        world.tenant.id, now=NOW, property_id=world.property.id
    )

    assert outcome.created == 0
    assert len(await _price_rows(db_session, world.tenant.id)) == before


async def test_the_roster_is_resolved_once_per_execution_not_once_per_property(
    flow, world, db_session
) -> None:
    """Design D7's whole reason for the lazy memo, asserted by counting statements.

    With N properties creating rows, resolving per property would be 2N queries for an answer
    that cannot change inside one sweep. Counted rather than reasoned about, because a `for`
    that re-resolves looks exactly like one that does not.
    """
    from tests.sql_counter import count_statements

    await a_rule(flow, world, property_id=world.property.id)
    await a_rule(flow, world, property_id=world.second_property.id)

    with count_statements(db_session.bind) as log:
        outcome = await flow.generate.execute(world.tenant.id, now=NOW)

    assert outcome.created == 120  # both properties created their horizons
    roster_queries = [
        statement
        for statement in log.matching("FROM users")
        if "count" not in statement.lower()
    ]
    # Exactly two: one for PROPERTY_MANAGER, one for TENANT_OWNER, for the whole sweep.
    assert len(roster_queries) == 2, roster_queries
    assert len(await _price_rows(db_session, world.tenant.id)) == 4  # 2 properties x 2 people


async def test_a_run_that_creates_nothing_never_asks_for_the_roster(
    flow, world, db_session
) -> None:
    """The other half of D7's laziness: a tenant with no rules pays nothing.

    Resolving the roster on entry to `execute` would spend two queries on every tick of
    every tenant, including the ones that skip every property for want of a rule.
    """
    from tests.sql_counter import count_statements

    with count_statements(db_session.bind) as log:
        outcome = await flow.generate.execute(world.tenant.id, now=NOW)

    assert outcome.created == 0
    assert log.matching("FROM users") == []
    assert await _price_rows(db_session, world.tenant.id) == []


async def test_a_neighbours_owner_is_never_told_about_this_tenants_prices(
    flow, world, db_session
) -> None:
    """Rule 1 of `steering/security.md` on a row addressed to a named person."""
    await a_rule(flow, world, property_id=world.property.id)

    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)

    mine = await _price_rows(db_session, world.tenant.id)
    assert {row.recipient_user_id for row in mine} == {world.manager.id, world.owner.id}
    assert await _price_rows(db_session, world.other_tenant.id) == []


async def test_a_mixed_sweep_only_announces_the_properties_that_created(
    flow, world, db_session
) -> None:
    """R4.1/R4.3 in one execution: the gate is per property, not per sweep.

    The existing tests cover "one property creates" and "one property only updates" as
    separate runs. The section-6/7 QA panel pointed out the permutation that actually
    exercises the gate's placement — a creator and an updater **in the same `execute`** — and
    it was missing. A gate hoisted out of `_price_one_property` to the sweep would pass both
    of the older tests and fail this one.
    """
    await a_rule(flow, world, property_id=world.property.id)
    # Give the first property a full horizon already, so the next sweep only updates it.
    await flow.generate.execute(world.tenant.id, now=NOW, property_id=world.property.id)
    before = await _price_rows(db_session, world.tenant.id)
    assert {row.related_id for row in before} == {world.property.id}

    # Now the second property gains a rule and creates for the first time, in a sweep that
    # also revisits the first property.
    await a_rule(flow, world, property_id=world.second_property.id)
    await flow.generate.execute(world.tenant.id, now=NOW)

    after = await _price_rows(db_session, world.tenant.id)
    fresh = [row for row in after if row not in before]
    # Only the property that actually created anything is announced.
    assert {row.related_id for row in fresh} == {world.second_property.id}


async def test_a_notification_does_not_survive_the_rollback_of_its_own_property(
    flow, world, db_session
) -> None:
    """R4.1's row lives in the property's transaction, so an abandoned property announces nothing.

    The two existing failure-injection tests both raise *before* `_notify_new_recommendations`
    is reached, so neither covered this window — the section-6/7 QA panel called it out.

    The failure is placed **between the two recipients**: the manager's row is written and
    flushed by the real adapter, then the owner's raises. So a notification row genuinely
    exists inside the transaction at the moment it is abandoned, which is the only way to show
    that the rollback takes it with the horizon rather than leaving an orphan announcement for
    a property whose prices were discarded.

    The explicit `rollback()` before the assertions is not ceremony: the adapter's `add`
    flushes, so the failure lands with a real statement already on the connection, and the
    session has to be brought back to a usable state before it can be queried. Two earlier
    attempts at this test skipped that and died on `MissingGreenlet` — which looked like a
    product problem and was not.
    """

    class _FailsOnTheSecondRecipient(_Delegating):
        """Fails the second row of whichever property the sweep reaches first.

        Not keyed to a named property on purpose: `_candidates`' ordering is not part of what
        this test is about, and pinning the failure to a specific one made the sweep end on
        the abandoned property, leaving the session unusable for the assertions.
        """

        def __init__(self, inner) -> None:
            super().__init__(inner)
            self.added = 0
            self.failed_property = None

        async def add(self, tenant_id, log):
            self.added += 1
            if self.added == 2:
                self.failed_property = log.related_id
                raise RuntimeError("the second notification write failed")
            return await self._inner.add(tenant_id, log)

    # Ids captured as plain UUIDs **before** the sweep. This is the whole reason three
    # earlier attempts at this test died on `MissingGreenlet`: the abandoned property's
    # rollback expires the `world` fixture's ORM instances, so a later `world.property.id`
    # is not a field read but a lazy refresh — IO in a place the assertions never expected
    # it. The session was fine all along; reading the fixture was not.
    first_id, second_id = world.property.id, world.second_property.id

    await a_rule(flow, world, property_id=first_id)
    # The second property needs a rule too, so the sweep ends on a **successful** commit
    # after the first one is abandoned. Without it the second property is merely skipped for
    # want of a rule, the run ends on the rollback, and the session is left in a state where
    # the assertions below raise `MissingGreenlet` — which is what defeated two earlier
    # attempts at this test and looked like a product problem. It is the same shape
    # `test_a_failure_after_the_upsert_discards_that_propertys_rows_too` relies on.
    await a_rule(flow, world, property_id=second_id)
    await db_session.commit()
    notifications = _FailsOnTheSecondRecipient(flow.notifications)
    generator = a_generator(flow, notifications=notifications)

    tenant_id = world.tenant.id
    outcome = await generator.execute(tenant_id, now=NOW)

    assert outcome.failed == 1
    # The failure landed where it was meant to: on a property's **second** recipient, so its
    # first recipient's row had already been written inside that transaction. Without that,
    # this test would prove only that a property with no rows keeps no rows.
    assert notifications.failed_property is not None
    assert notifications.added >= 2
    abandoned = notifications.failed_property
    healthy = {first_id, second_id} - {abandoned}
    assert len(healthy) == 1
    survivor = healthy.pop()

    # The abandoned property kept neither its horizon nor its announcement...
    assert await horizon_rows(db_session, abandoned) == []
    announced = {row.related_id for row in await _price_rows(db_session, tenant_id)}
    assert abandoned not in announced
    # ...while its sibling in the same sweep kept both (D9: the loop carries on).
    assert len(await horizon_rows(db_session, survivor)) == 60
    assert announced == {survivor}
