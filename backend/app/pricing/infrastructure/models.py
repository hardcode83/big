import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.pricing.domain.enums import PriceRecommendationStatus

_EMPTY_OBJECT = text("'{}'::jsonb")
_EMPTY_ARRAY = text("'[]'::jsonb")


class PricingRuleModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "pricing_rules"

    # Nullable on purpose: a rule with no property applies to the whole tenant (§7.17).
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    min_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    max_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    max_daily_change_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("20.00"), server_default="20.00"
    )
    weekday_modifiers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=_EMPTY_OBJECT
    )
    lead_time_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=_EMPTY_ARRAY
    )
    occupancy_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=_EMPTY_ARRAY
    )
    seasonality_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=_EMPTY_ARRAY
    )
    event_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=_EMPTY_ARRAY
    )


class PriceRecommendationModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "price_recommendations"
    __table_args__ = (
        UniqueConstraint("property_id", "date", name="uq_price_recommendations_property_id_date"),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT")
    )
    pricing_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pricing_rules.id", ondelete="RESTRICT")
    )
    date: Mapped[date] = mapped_column(Date)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    recommended_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    explanation: Mapped[str] = mapped_column()
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("1.00"), server_default="1.00"
    )
    status: Mapped[PriceRecommendationStatus] = mapped_column(
        Enum(PriceRecommendationStatus, name="price_recommendation_status", native_enum=True),
        default=PriceRecommendationStatus.RECOMMENDED,
        server_default=PriceRecommendationStatus.RECOMMENDED.value,
    )
    # No TimestampMixin: §7.18 declares created_at only.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
