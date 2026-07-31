import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.pricing.domain.entities import PriceRecommendation, PricingRule
from app.pricing.domain.enums import PriceRecommendationStatus


def test_pricing_rule_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    rule = PricingRule(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Madrid base",
        base_price=Decimal("90.00"),
        min_price=Decimal("60.00"),
        max_price=Decimal("180.00"),
        created_at=now,
        updated_at=now,
    )

    assert rule.property_id is None
    assert rule.active is True
    assert rule.max_daily_change_pct == Decimal("20.00")
    assert rule.weekday_modifiers == {}
    assert rule.lead_time_rules == []
    assert rule.occupancy_rules == []
    assert rule.seasonality_rules == []
    assert rule.event_rules == []


def test_pricing_rule_json_defaults_are_not_shared_between_instances() -> None:
    """A bare `= {}` default would make every rule share one dict."""
    now = datetime.now(timezone.utc)
    common = {
        "tenant_id": uuid.uuid4(),
        "name": "shared-default probe",
        "base_price": Decimal("90.00"),
        "min_price": Decimal("60.00"),
        "max_price": Decimal("180.00"),
        "created_at": now,
        "updated_at": now,
    }
    first = PricingRule(id=uuid.uuid4(), **common)
    second = PricingRule(id=uuid.uuid4(), **common)

    first.weekday_modifiers["friday"] = 15
    first.event_rules.append({"name": "Local Festival", "modifier_pct": 25})

    assert second.weekday_modifiers == {}
    assert second.event_rules == []


def test_price_recommendation_instantiates_with_defaults() -> None:
    recommendation = PriceRecommendation(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        pricing_rule_id=uuid.uuid4(),
        date=date(2026, 8, 15),
        recommended_price=Decimal("135.00"),
        explanation="Weekend in high season, +50% over base price.",
        created_at=datetime.now(timezone.utc),
    )

    assert recommendation.current_price is None
    assert recommendation.confidence == Decimal("1.00")
    assert recommendation.status is PriceRecommendationStatus.RECOMMENDED
