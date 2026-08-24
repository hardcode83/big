import type {
  DecisionStatus,
  GenerationReport,
  PriceRecommendation,
  PricingPage,
  PricingRule,
  PricingRuleFilters,
  PropertySummary,
  RecommendationFilters,
} from "./dto";

/**
 * The pricing screen's data-access boundary. Components and hooks depend ONLY on
 * this interface, never on a concrete implementation, which is what lets the
 * component tests inject a double without touching `lib/api`. The single runtime
 * implementation is `HttpPricingSource`; there is no mock source, because the
 * backend has existed since the `revenue-pricing` change and there is nothing to
 * stand in for (design D1).
 *
 * `tenantId` is explicit at the boundary so the tenant-scoped query keys stay
 * honest; it comes from the session context. The backend remains the authority
 * for tenant isolation.
 *
 * **There is no method for `GET /api/v1/pricing-rules/{rule_id}`, and that is the
 * enforcement of R5.5**: the detail route returns the same `PricingRuleResponse`
 * already carried by every `items[]`, so there is no detail to fetch. Absence
 * here is what stops a later component from reaching for it.
 *
 * Every method rejects with `ApiError` (`lib/api`) on failure — including the §23
 * `403`/`404`/`409`/`422` envelopes that `decideRecommendation` can produce.
 */
export interface PricingDataSource {
  /** One page of the tenant's recommendations, filtered server-side (R2.1). */
  listRecommendations(
    tenantId: string,
    filters: RecommendationFilters,
    page: number,
  ): Promise<PricingPage<PriceRecommendation>>;

  /** One page of the tenant's pricing rules, filtered server-side (R5.1). */
  listRules(
    tenantId: string,
    filters: PricingRuleFilters,
    page: number,
  ): Promise<PricingPage<PricingRule>>;

  /** The tenant's property catalog, for R2.8's readable identity. */
  listProperties(tenantId: string): Promise<PropertySummary[]>;

  /** One of the three legal moves; `status` is the only field sent (R3.1, R3.2). */
  decideRecommendation(
    tenantId: string,
    recommendationId: string,
    status: DecisionStatus,
  ): Promise<PriceRecommendation>;

  /** Runs the generator now; `null` sweeps the whole active portfolio (R4.1). */
  generateRecommendations(
    tenantId: string,
    propertyId: string | null,
  ): Promise<GenerationReport>;
}
