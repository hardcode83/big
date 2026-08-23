import type { components } from "@/lib/api/generated/openapi";

/**
 * DTOs for the pricing screen (PRD §7.17, §7.18, §19, §24). Success shapes only:
 * failures travel as the §23 error envelope, which `lib/api` turns into a thrown
 * `ApiError`. Types only — no runtime code.
 *
 * Two things here are deliberately unlike the rest of the tree, and both are the
 * point:
 *
 *  - The page envelope is `PricingPage`, **not** `PaginatedResponse` (design D2).
 *    Pricing answers `{items, total, page, per_page}` with no `total_pages`, while
 *    §23's envelope is `{data, …, total_pages}`. A boundary copied from `cleaning`
 *    compiles against `data` and fails at runtime, so the type carries a different
 *    name to make the asymmetry visible where it has to be seen.
 *  - What must not be painted **does not cross the boundary** (design D3). No
 *    `current_price`, no `confidence`, no `created_at`, and no JSONB column: R2.5,
 *    R2.6 and R5.4 stop being discipline for whoever writes the component and
 *    become unrepresentable.
 */

/**
 * Pricing's page envelope, normalized at the boundary with `totalPages` computed
 * there (design D2). `totalPages` is `0` when `total` is `0`, so «page 1 of 0» is
 * not representable and the view resolves the empty state before paginating (R2.3).
 */
export interface PricingPage<T> {
  items: T[];
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
}

/**
 * Alias of the generated union, never a hand-written copy: a sixth status in the
 * backend must break the build here as soon as the contract is regenerated. That
 * guarantee is compile-time only — `lib/decision-moves.ts` and
 * `lib/recommendation-status.ts` carry the runtime fallbacks for the deploy-skew
 * window.
 */
export type PriceRecommendationStatus =
  components["schemas"]["PriceRecommendationStatus"];

/**
 * The three statuses a human may write (design D4). Taking this rather than the
 * full union means sending `DRAFT` or `RECOMMENDED` does not compile, and a
 * rename in the backend breaks the build on regeneration instead of producing a
 * `422` at runtime.
 */
export type DecisionStatus = Extract<
  PriceRecommendationStatus,
  "APPROVED" | "REJECTED" | "APPLIED_EXTERNAL"
>;

/**
 * One recommendation row (PRD §7.18).
 *
 * `current_price`, `confidence` and `created_at` are absent on purpose (design
 * D3): the first is always `null` while Mode 1 never calls the PMS, the second is
 * fixed at `1.00` because the calculation is deterministic, and the third would be
 * the only timestamp on screen when R2.6 forbids one — `PriceRecommendationResponse`
 * has no `updated_at`, so no decision instant exists to show honestly.
 *
 * `explanation` is the backend's English sentence, rendered literally as text and
 * never as markup (R2.7, design D16).
 */
export interface PriceRecommendation {
  id: string;
  propertyId: string;
  pricingRuleId: string;
  /** `YYYY-MM-DD`, the night being priced. Formatted with `fmtDay`, never zone-shifted. */
  date: string;
  /** Decimal as a string; converted to a number only to format it (R6.1). */
  recommendedPrice: string;
  status: PriceRecommendationStatus;
  explanation: string;
}

/**
 * How many entries each of the rule's five JSONB columns holds — never what is
 * inside them (R5.4, design D3). Counting cardinality is safe; painting the
 * contents would reimplement the PRD §7.17 schema in the client.
 */
export interface ModifierCounts {
  weekday: number;
  leadTime: number;
  occupancy: number;
  seasonality: number;
  event: number;
}

/** One pricing rule, read-only (PRD §7.17). The five JSONB columns arrive as counts. */
export interface PricingRule {
  id: string;
  /** `null` means the whole portfolio — a positive claim, not a missing property (R5.3). */
  propertyId: string | null;
  name: string;
  active: boolean;
  basePrice: string;
  minPrice: string;
  maxPrice: string;
  /** Decimal as a string; the `%` lives in the localized label, not in the number (design D14). */
  maxDailyChangePct: string;
  modifierCounts: ModifierCounts;
}

/**
 * The four counters a generation reports (R4.2). There is no `failed` in the
 * published contract, which is why the copy that renders these may not claim the
 * sweep was complete or correct (R4.3).
 */
export interface GenerationReport {
  created: number;
  updated: number;
  preserved: number;
  skipped: number;
}

/** A property from the tenant's catalog, for the readable identity of R2.8. */
export interface PropertySummary {
  id: string;
  name: string;
  internalCode: string;
}

/** Server-side filters for the recommendation queue (R2.1); never applied in the client. */
export interface RecommendationFilters {
  propertyId?: string;
  dateFrom?: string;
  dateTo?: string;
  status?: PriceRecommendationStatus;
}

/** Server-side filters for the rule list (R5.1). */
export interface PricingRuleFilters {
  propertyId?: string;
  active?: boolean;
}
