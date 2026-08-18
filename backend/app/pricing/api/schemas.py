"""Request/response DTOs for the seven pricing routes (PRD §23, R1, R4.5, R5).

Four rules this module exists to enforce, three of them shared with `maintenance`'s and one
of them particular to pricing:

* **No request schema has a `tenant_id`.** The effective tenant comes only from the
  verified token.
* **Response fields are enumerated, never dumped from the entity.** Both aggregates carry
  `tenant_id`, and a `from_attributes` dump would publish it.
* **`page` and `per_page` have ceilings.** The ports refuse a non-positive page; the
  ceiling belongs here, or one request pulls a tenant's whole horizon — sixty rows per
  property per run, each with its rendered `explanation` — in a single response.
* **These schemas are not the only gate, and deliberately not the field-naming one**
  (design D16). They validate types and shapes; every invariant of R1.3 and R1.4 lives in
  `PricingRule.validate()`, which is also what names the failing field. The nightly job and
  `POST /generate` read rules written *earlier*, so a validator that only ran here would
  leave every later reader unprotected. Concretely: the five JSONB columns are typed as
  containers and nothing more, because their interior schema (D3, D7) is a business rule.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.pricing.domain.entities import PriceRecommendation, PricingRule
from app.pricing.domain.enums import PriceRecommendationStatus

MAX_PER_PAGE = 100
# `page` needs a ceiling too, not just `per_page`: the value becomes a SQL OFFSET and a
# 20-digit page number overflows int8, producing an unhandled driver error instead of a 422
# in the PRD §23 envelope. Same bound and same reason as `maintenance` and `cleaning`.
MAX_PAGE = 100_000

#: `pricing_rules.name` is `VARCHAR(200)`; the entity refuses anything longer and names the
#: field (R1.4). Repeated here only as a body ceiling, so a megabyte of `name` is refused
#: before it is copied into an entity — not as the authority on the bound.
MAX_NAME_LENGTH = 200

# `allow_inf_nan=False` on every `Decimal` field: Pydantic otherwise accepts the JSON
# strings "NaN" and "Infinity" into a `Decimal`, and while `_number` in the entity refuses
# both, a price that is not a number has no business getting as far as an aggregate.
_Price = Annotated[Decimal, Field(allow_inf_nan=False)]


class PricingRuleResponse(BaseModel):
    """What an authorised operator may see about one rule.

    Every writable column of the rule plus its identity and timestamps — a rule is the
    manager's own declaration, so there is nothing here she did not write herself. What is
    absent is `tenant_id`: it is the token's, and echoing it back tells a caller nothing it
    did not already prove.
    """

    id: uuid.UUID
    property_id: uuid.UUID | None
    name: str
    active: bool
    base_price: Decimal
    min_price: Decimal
    max_price: Decimal
    max_daily_change_pct: Decimal
    weekday_modifiers: dict[str, Any]
    lead_time_rules: list[dict[str, Any]]
    occupancy_rules: list[dict[str, Any]]
    seasonality_rules: list[dict[str, Any]]
    event_rules: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, rule: PricingRule) -> "PricingRuleResponse":
        return cls(
            id=rule.id,
            property_id=rule.property_id,
            name=rule.name,
            active=rule.active,
            base_price=rule.base_price,
            min_price=rule.min_price,
            max_price=rule.max_price,
            max_daily_change_pct=rule.max_daily_change_pct,
            weekday_modifiers=rule.weekday_modifiers,
            lead_time_rules=rule.lead_time_rules,
            occupancy_rules=rule.occupancy_rules,
            seasonality_rules=rule.seasonality_rules,
            event_rules=rule.event_rules,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )


class PricingRulePageResponse(BaseModel):
    items: list[PricingRuleResponse]
    total: int
    page: int
    per_page: int

    @classmethod
    def from_domain(
        cls, rules: Sequence[PricingRule], *, total: int, page: int, per_page: int
    ) -> "PricingRulePageResponse":
        return cls(
            items=[PricingRuleResponse.from_domain(rule) for rule in rules],
            total=total,
            page=page,
            per_page=per_page,
        )


class CreatePricingRuleRequest(BaseModel):
    """`POST /api/v1/pricing-rules` (R1.1, R1.3, R1.4).

    `property_id` omitted means a tenant-wide rule (R1.5), which is why it is nullable
    rather than required. The five JSONB columns default to empty: a rule with no
    modifiers is a flat `base_price`, which is a legitimate starting point.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(max_length=MAX_NAME_LENGTH)]
    base_price: _Price
    min_price: _Price
    max_price: _Price
    property_id: uuid.UUID | None = None
    active: bool = True
    max_daily_change_pct: _Price = Decimal("20.00")
    weekday_modifiers: dict[str, Any] | None = None
    lead_time_rules: list[dict[str, Any]] | None = None
    occupancy_rules: list[dict[str, Any]] | None = None
    seasonality_rules: list[dict[str, Any]] | None = None
    event_rules: list[dict[str, Any]] | None = None


class UpdatePricingRuleRequest(BaseModel):
    """`PATCH /api/v1/pricing-rules/{id}` (R1.2, R1.3, R1.4).

    Every field optional, and the router forwards `model_dump(exclude_unset=True)` — so
    **"absent" and "sent as null" are different things**, which this endpoint needs: setting
    `property_id` to `null` is how a per-property rule becomes tenant-wide (R1.5), and a
    schema that could not tell the two apart would make that unexpressible.

    The other fields are typed `| None` only to be optional; the entity refuses a null in
    any of them and names the field (D16). Sending no field at all is a no-op the use case
    answers without writing anything.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(max_length=MAX_NAME_LENGTH)] = None
    active: bool | None = None
    property_id: uuid.UUID | None = None
    base_price: _Price | None = None
    min_price: _Price | None = None
    max_price: _Price | None = None
    max_daily_change_pct: _Price | None = None
    weekday_modifiers: dict[str, Any] | None = None
    lead_time_rules: list[dict[str, Any]] | None = None
    occupancy_rules: list[dict[str, Any]] | None = None
    seasonality_rules: list[dict[str, Any]] | None = None
    event_rules: list[dict[str, Any]] | None = None


class PriceRecommendationResponse(BaseModel):
    """One recommended price, with the sentence that explains it.

    `explanation` **is** here, and that is the point of R6: the owner approves with
    criterion instead of blind. It is sink 14 of rule 11 in `steering/security.md`, and its
    audience is exactly this surface — an authenticated `TENANT_OWNER` or
    `PROPERTY_MANAGER`, reading a price for their own flat.

    `current_price` is always `null` while Mode 1 never calls the PMS (R5.5, D19); it is
    published anyway because the column exists and a client that omitted it would have to
    change shape the day ARI arrives.
    """

    id: uuid.UUID
    property_id: uuid.UUID
    pricing_rule_id: uuid.UUID
    date: date
    recommended_price: Decimal
    current_price: Decimal | None
    confidence: Decimal
    status: PriceRecommendationStatus
    explanation: str
    created_at: datetime

    @classmethod
    def from_domain(
        cls, recommendation: PriceRecommendation
    ) -> "PriceRecommendationResponse":
        return cls(
            id=recommendation.id,
            property_id=recommendation.property_id,
            pricing_rule_id=recommendation.pricing_rule_id,
            date=recommendation.date,
            recommended_price=recommendation.recommended_price,
            current_price=recommendation.current_price,
            confidence=recommendation.confidence,
            status=recommendation.status,
            explanation=recommendation.explanation,
            created_at=recommendation.created_at,
        )


class PriceRecommendationPageResponse(BaseModel):
    items: list[PriceRecommendationResponse]
    total: int
    page: int
    per_page: int

    @classmethod
    def from_domain(
        cls,
        recommendations: Sequence[PriceRecommendation],
        *,
        total: int,
        page: int,
        per_page: int,
    ) -> "PriceRecommendationPageResponse":
        return cls(
            items=[
                PriceRecommendationResponse.from_domain(recommendation)
                for recommendation in recommendations
            ],
            total=total,
            page=page,
            per_page=per_page,
        )


class GeneratePriceRecommendationsRequest(BaseModel):
    """`POST /api/v1/price-recommendations/generate` (R4.5, OQ4).

    `property_id` omitted sweeps the tenant's whole active portfolio, which is the case
    that motivates the endpoint: a tenant-wide rule just changed and every property needs
    repricing (OQ4). Naming a property that is unknown, another tenant's, or not `ACTIVE`
    is a `422` — it is a body field, not a path identifier (D9's fourth refinement).
    """

    model_config = ConfigDict(extra="forbid")

    property_id: uuid.UUID | None = None


class GenerationReportResponse(BaseModel):
    """The four counters R4.5 asks a generation to report.

    One number per outcome, and they do not overlap: `created` are new rows, `updated` are
    recalculated ones, `preserved` are the human decisions R4.3 protects, and `skipped` are
    properties with no applicable active rule (R4.6). A fifth counter exists inside the use
    case — `failed` — and stays out of the published contract per D9/D10; a failed property
    is reported in the application log with the id that caused it.
    """

    created: int
    updated: int
    preserved: int
    skipped: int


class DecidePriceRecommendationRequest(BaseModel):
    """`PATCH /api/v1/price-recommendations/{id}` (R5.2, R5.3, R5.4).

    Only `status`, and only the three legal moves get through — but the refusal is the
    entity's, not this schema's: `PriceRecommendation` owns the state machine, so an
    illegal move is a `409` with the status untouched (R5.4) rather than a `422` about a
    shape. Typing the field as the enum keeps a value outside the enum entirely out of the
    domain, which is a different failure and correctly a `422`.
    """

    model_config = ConfigDict(extra="forbid")

    status: PriceRecommendationStatus
