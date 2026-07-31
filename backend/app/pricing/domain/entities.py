import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.pricing.domain.enums import PriceRecommendationStatus


@dataclass
class PricingRule:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    base_price: Decimal
    min_price: Decimal
    max_price: Decimal
    created_at: datetime
    updated_at: datetime
    property_id: uuid.UUID | None = None
    active: bool = True
    max_daily_change_pct: Decimal = Decimal("20.00")
    weekday_modifiers: dict[str, Any] = field(default_factory=dict)
    lead_time_rules: list[dict[str, Any]] = field(default_factory=list)
    occupancy_rules: list[dict[str, Any]] = field(default_factory=list)
    seasonality_rules: list[dict[str, Any]] = field(default_factory=list)
    event_rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PriceRecommendation:
    id: uuid.UUID
    tenant_id: uuid.UUID
    property_id: uuid.UUID
    pricing_rule_id: uuid.UUID
    date: date
    recommended_price: Decimal
    explanation: str
    created_at: datetime
    current_price: Decimal | None = None
    confidence: Decimal = Decimal("1.00")
    status: PriceRecommendationStatus = PriceRecommendationStatus.RECOMMENDED
