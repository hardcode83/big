import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type { PricingDataSource } from "../pricing-source";
import type {
  DecisionStatus,
  GenerationReport,
  ModifierCounts,
  PriceRecommendation,
  PricingPage,
  PricingRule,
  PricingRuleFilters,
  PropertySummary,
  RecommendationFilters,
} from "../dto";

type RecommendationPageResponse =
  components["schemas"]["PriceRecommendationPageResponse"];
type RecommendationResponse =
  components["schemas"]["PriceRecommendationResponse"];
type RulePageResponse = components["schemas"]["PricingRulePageResponse"];
type RuleResponse = components["schemas"]["PricingRuleResponse"];
type ReportResponse = components["schemas"]["GenerationReportResponse"];
type PropertyPageResponse = components["schemas"]["PropertyPageResponse"];
type PropertyListItemResponse =
  components["schemas"]["PropertyListItemResponse"];

/** One page per request in both tabs; `page` is what the pagination control moves. */
const ITEMS_PER_PAGE = 20;

/**
 * ASSUMPTION (design D5): the property catalog is fetched as a single page of
 * 100, which is the backend's `MAX_PER_PAGE`, exactly as
 * `http-cleaning-source.ts` does. A tenant with more than 100 properties will see
 * "identity unavailable" (R2.8) from the hundredth onwards. That is the
 * degradation R2.8 specifies rather than a silent failure, and it is harmless at
 * MVP scale (two flats) — but it stops being correct as coverage and has to be
 * redone before the SaaS phase.
 */
const CATALOG_PER_PAGE = 100;

/**
 * Pricing's page envelope is `{items, total, page, per_page}` and carries **no
 * `total_pages`** — unlike the §23 `{data, …, total_pages}` of `cleaning`,
 * `properties` and `reservations`. Both halves of that asymmetry are handled
 * here, once, so no view repeats them (design D2).
 *
 * `perPage <= 0` yields `0` rather than a division by zero, and `total === 0`
 * yields `0` too — which is what makes «page 1 of 0» unrepresentable and lets the
 * view resolve the empty state first (R2.3).
 */
function mapPage<T, U>(
  page: { items: T[]; total: number; page: number; per_page: number },
  mapItem: (item: T) => U,
): PricingPage<U> {
  return {
    items: page.items.map(mapItem),
    total: page.total,
    page: page.page,
    perPage: page.per_page,
    totalPages: page.per_page > 0 ? Math.ceil(page.total / page.per_page) : 0,
  };
}

/**
 * How many entries a JSONB column holds, **never what is in one** (R5.4, design
 * D3). The contract declares `weekday_modifiers` an object and the other four
 * arrays; anything else is a deploy-skew window and counts as `0` rather than
 * throwing. No value is ever read.
 */
export function countEntries(value: unknown): number {
  if (Array.isArray(value)) {
    return value.length;
  }
  if (typeof value === "object" && value !== null) {
    return Object.keys(value).length;
  }
  return 0;
}

function mapRecommendation(value: RecommendationResponse): PriceRecommendation {
  // `current_price`, `confidence` and `created_at` are deliberately not read
  // (design D3): what is not mapped cannot be painted (R2.5, R2.6).
  return {
    id: value.id,
    propertyId: value.property_id,
    pricingRuleId: value.pricing_rule_id,
    date: value.date,
    recommendedPrice: value.recommended_price,
    status: value.status,
    explanation: value.explanation,
  };
}

function mapRule(value: RuleResponse): PricingRule {
  return {
    id: value.id,
    propertyId: value.property_id,
    name: value.name,
    active: value.active,
    basePrice: value.base_price,
    minPrice: value.min_price,
    maxPrice: value.max_price,
    maxDailyChangePct: value.max_daily_change_pct,
    modifierCounts: {
      weekday: countEntries(value.weekday_modifiers),
      leadTime: countEntries(value.lead_time_rules),
      occupancy: countEntries(value.occupancy_rules),
      seasonality: countEntries(value.seasonality_rules),
      event: countEntries(value.event_rules),
    } satisfies ModifierCounts,
  };
}

function mapProperty(value: PropertyListItemResponse): PropertySummary {
  return {
    id: value.id,
    name: value.name,
    internalCode: value.internal_code,
  };
}

export class HttpPricingSource implements PricingDataSource {
  constructor(private readonly client: ApiClient) {}

  async listRecommendations(
    _tenantId: string,
    filters: RecommendationFilters,
    page: number,
  ): Promise<PricingPage<PriceRecommendation>> {
    const response: RecommendationPageResponse = await this.client.request<
      "/api/v1/price-recommendations",
      "GET"
    >("/api/v1/price-recommendations", {
      query: {
        page,
        per_page: ITEMS_PER_PAGE,
        // Only the filters actually chosen travel; the backend ANDs them and
        // nothing is ever filtered client-side (R2.1). The status parameter is
        // named `status` on the wire — Python calls it `status_filter` with
        // `Query(alias="status")`, and the alias is what the contract publishes.
        ...(filters.propertyId !== undefined
          ? { property_id: filters.propertyId }
          : {}),
        ...(filters.dateFrom !== undefined
          ? { date_from: filters.dateFrom }
          : {}),
        ...(filters.dateTo !== undefined ? { date_to: filters.dateTo } : {}),
        ...(filters.status !== undefined ? { status: filters.status } : {}),
      },
    });
    return mapPage(response, mapRecommendation);
  }

  async listRules(
    _tenantId: string,
    filters: PricingRuleFilters,
    page: number,
  ): Promise<PricingPage<PricingRule>> {
    const response: RulePageResponse = await this.client.request<
      "/api/v1/pricing-rules",
      "GET"
    >("/api/v1/pricing-rules", {
      query: {
        page,
        per_page: ITEMS_PER_PAGE,
        ...(filters.propertyId !== undefined
          ? { property_id: filters.propertyId }
          : {}),
        // A boolean on the wire, which is why design D20 widened
        // `RequestOptions.query`; `appendQuery` sends `active=true`/`false`.
        ...(filters.active !== undefined ? { active: filters.active } : {}),
      },
    });
    return mapPage(response, mapRule);
  }

  async listProperties(_tenantId: string): Promise<PropertySummary[]> {
    const response: PropertyPageResponse = await this.client.request<
      "/api/v1/properties",
      "GET"
    >("/api/v1/properties", {
      query: { page: 1, per_page: CATALOG_PER_PAGE },
    });
    // `/api/v1/properties` is a §23 envelope and answers `data`, not `items`:
    // the two shapes live side by side in this file on purpose.
    return response.data.map(mapProperty);
  }

  async decideRecommendation(
    _tenantId: string,
    recommendationId: string,
    status: DecisionStatus,
  ): Promise<PriceRecommendation> {
    // `DecidePriceRecommendationRequest` is `extra="forbid"` with a single field:
    // anything else in this body is a `422` (R3.1, R3.2).
    const response: RecommendationResponse = await this.client.request(
      "/api/v1/price-recommendations/{recommendation_id}",
      {
        method: "PATCH",
        pathParams: { recommendation_id: recommendationId },
        body: { status },
      },
    );
    return mapRecommendation(response);
  }

  async generateRecommendations(
    _tenantId: string,
    propertyId: string | null,
  ): Promise<GenerationReport> {
    // Runs synchronously inside the request and answers the report: no `202`, no
    // job id, no polling (R4.1). `null` sweeps the whole active portfolio.
    const response: ReportResponse = await this.client.request(
      "/api/v1/price-recommendations/generate",
      {
        method: "POST",
        body: { property_id: propertyId },
      },
    );
    return {
      created: response.created,
      updated: response.updated,
      preserved: response.preserved,
      skipped: response.skipped,
    };
  }
}
