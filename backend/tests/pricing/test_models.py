import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.pricing.infrastructure.models import PriceRecommendationModel, PricingRuleModel
from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel


async def _tenant_property(db_session, code: str = "redes11"):
    tenant = TenantModel(name="Owner A", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(tenant_id=tenant.id, name="REDES11", internal_code=code)
    db_session.add(prop)
    await db_session.flush()
    return tenant, prop


def _rule(tenant_id, property_id=None) -> PricingRuleModel:
    return PricingRuleModel(
        tenant_id=tenant_id,
        property_id=property_id,
        name="Madrid base",
        base_price=Decimal("90.00"),
        min_price=Decimal("60.00"),
        max_price=Decimal("180.00"),
    )


@pytest.mark.asyncio
async def test_pricing_rule_roundtrip_applies_the_prd_defaults(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)

    rule = _rule(tenant.id, prop.id)
    db_session.add(rule)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(PricingRuleModel).where(PricingRuleModel.id == rule.id))
    ).scalar_one()
    assert fetched.active is True
    assert fetched.max_daily_change_pct == Decimal("20.00")
    assert fetched.weekday_modifiers == {}
    assert fetched.lead_time_rules == []
    assert fetched.occupancy_rules == []
    assert fetched.seasonality_rules == []
    assert fetched.event_rules == []


@pytest.mark.asyncio
async def test_pricing_rule_server_defaults_apply_without_the_orm(db_session) -> None:
    """The DDL defaults, proven by a statement SQLAlchemy cannot fill in (R3.2).

    Raw `text()` on purpose. `Table.insert().values(...)` looks like it bypasses the
    ORM, but SQLAlchemy Core still applies each column's Python-side `default=` when
    compiling the statement, so that test would pass unchanged with every
    `server_default` deleted from the model. Only a statement with no SQLAlchemy
    column knowledge reaches the database's own DEFAULT — which is what a data
    migration, a psql session or a script would hit.
    """
    tenant, _ = await _tenant_property(db_session)

    await db_session.execute(
        text(
            "INSERT INTO pricing_rules (id, tenant_id, name, base_price, min_price, max_price) "
            "VALUES (:id, :tenant_id, :name, 90.00, 60.00, 180.00)"
        ),
        {"id": uuid.uuid4(), "tenant_id": tenant.id, "name": "raw insert"},
    )
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(PricingRuleModel).where(PricingRuleModel.name == "raw insert")
        )
    ).scalar_one()
    assert fetched.active is True
    assert fetched.max_daily_change_pct == Decimal("20.00")
    assert fetched.weekday_modifiers == {}
    assert fetched.event_rules == []
    assert fetched.property_id is None


@pytest.mark.asyncio
async def test_pricing_rule_property_restrict_on_delete(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    db_session.add(_rule(tenant.id, prop.id))
    await db_session.commit()

    await db_session.delete(prop)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_price_recommendation_is_unique_per_property_and_date(db_session) -> None:
    tenant, prop = await _tenant_property(db_session)
    rule = _rule(tenant.id, prop.id)
    db_session.add(rule)
    await db_session.flush()

    for _ in range(2):
        db_session.add(
            PriceRecommendationModel(
                tenant_id=tenant.id,
                property_id=prop.id,
                pricing_rule_id=rule.id,
                date=date(2026, 8, 15),
                recommended_price=Decimal("135.00"),
                explanation="High season weekend.",
            )
        )

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_price_recommendation_keeps_decimal_scale_across_the_roundtrip(db_session) -> None:
    """Money must come back as Decimal at the declared scale, never as float (R6.3)."""
    tenant, prop = await _tenant_property(db_session)
    rule = _rule(tenant.id, prop.id)
    db_session.add(rule)
    await db_session.flush()

    recommendation = PriceRecommendationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        pricing_rule_id=rule.id,
        date=date(2026, 8, 15),
        current_price=Decimal("99.99"),
        recommended_price=Decimal("135.10"),
        explanation="High season weekend.",
    )
    db_session.add(recommendation)
    await db_session.commit()
    db_session.expunge_all()

    fetched = (
        await db_session.execute(
            select(PriceRecommendationModel).where(
                PriceRecommendationModel.id == recommendation.id
            )
        )
    ).scalar_one()
    assert isinstance(fetched.recommended_price, Decimal)
    assert fetched.recommended_price == Decimal("135.10")
    assert str(fetched.recommended_price) == "135.10"
    assert fetched.current_price == Decimal("99.99")
    assert fetched.confidence == Decimal("1.00")
    assert fetched.status.value == "RECOMMENDED"
