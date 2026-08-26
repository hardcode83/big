import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { PricingRuleFilters, RecommendationFilters } from "../data";

/**
 * Tenant-scoped query keys for the pricing resources (design D6). Built on the
 * shell's `tenantScopedKey`, so every key begins with `['tenant', tenantId, …]`
 * and a cross-tenant key cannot be produced by accident — `tenantScopedKey`
 * throws on an empty tenant rather than silently writing a global cache entry.
 *
 * The three resource names are the feature's own (`pricing-*`), so nothing here
 * can collide with `cleaning`'s keys. The property catalog is cached separately
 * from `cleaning`'s copy of the same list: two copies of one page of 100 rows is
 * cheaper than the shared catalog module this change would otherwise have to
 * introduce, and it is what `cleaning` already does next to `features/properties`.
 *
 * Filters go through the normalizers below, which is what makes two equivalent
 * renders produce the same key. Passing a raw object literal would work today
 * but breaks the moment a caller builds it with a different key order, because
 * TanStack Query hashes the key **structurally** — so the normalization is the
 * guarantee, not a nicety. This is the stricter pattern of
 * `features/properties/hooks/query-keys.ts` rather than `cleaning`'s loose literal.
 */
export const pricingKeys = {
  recommendations: (
    tenantId: string,
    filters: RecommendationFilters,
    page: number,
  ): QueryKey =>
    tenantScopedKey(
      tenantId,
      "pricing-recommendations",
      normalizeRecommendationFilters(filters, page),
    ),

  /**
   * The prefix every recommendation key shares — what both mutations invalidate
   * (design D7). Invalidating the prefix reaches every filter/page combination
   * without enumerating them, which is the only thing that reflects a row moving
   * out of the active filter: the `PATCH` response is a single recommendation and
   * knows nothing about `total` or the page it was on.
   */
  recommendationsPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "pricing-recommendations"),

  rules: (
    tenantId: string,
    filters: PricingRuleFilters,
    page: number,
  ): QueryKey =>
    tenantScopedKey(
      tenantId,
      "pricing-rules",
      normalizeRuleFilters(filters, page),
    ),

  properties: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "pricing-properties"),
} as const;

/**
 * Emit the filters with their keys in a FIXED order, dropping the ones that are
 * `undefined`, and canonicalizing the page (design D6).
 *
 * Three properties this guarantees, all of which matter for cache correctness:
 *
 *  - **Stable order**: `{status, page}` and `{page, status}` describe the same
 *    request and must not become two cache entries.
 *  - **Absence, not emptiness**: a filter set to "all" is omitted entirely, never
 *    written as `{status: undefined}`, which serializes differently by caller.
 *  - **`page` canonicalized**: "no page" and "page 1" are the same request, since
 *    the backend defaults `page` to 1.
 */
export function normalizeRecommendationFilters(
  filters: RecommendationFilters,
  page?: number,
): Record<string, string | number> {
  const normalized: Record<string, string | number> = {};
  if (filters.dateFrom !== undefined) {
    normalized.dateFrom = filters.dateFrom;
  }
  if (filters.dateTo !== undefined) {
    normalized.dateTo = filters.dateTo;
  }
  normalized.page = page ?? 1;
  if (filters.propertyId !== undefined) {
    normalized.propertyId = filters.propertyId;
  }
  if (filters.status !== undefined) {
    normalized.status = filters.status;
  }
  return normalized;
}

export function normalizeRuleFilters(
  filters: PricingRuleFilters,
  page?: number,
): Record<string, string | number | boolean> {
  const normalized: Record<string, string | number | boolean> = {};
  if (filters.active !== undefined) {
    normalized.active = filters.active;
  }
  normalized.page = page ?? 1;
  if (filters.propertyId !== undefined) {
    normalized.propertyId = filters.propertyId;
  }
  return normalized;
}
