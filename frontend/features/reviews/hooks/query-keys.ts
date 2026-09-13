import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { ReviewFilters } from "../data";

/**
 * Tenant-scoped query keys for the reviews resources (design D7). Built on the
 * shell's `tenantScopedKey`, so every key begins with `['tenant', tenantId, …]`
 * and a cross-tenant key cannot be produced by accident — `tenantScopedKey`
 * throws on an empty tenant rather than silently writing a global cache entry.
 *
 * The three resource names are the feature's own (`reviews*`), so nothing here
 * can collide with `pricing`/`cleaning` keys. The property catalog is cached
 * separately from pricing's copy of the same list — two copies of one page of
 * 100 rows is cheaper than a shared catalog module this change would otherwise
 * have to introduce.
 *
 * Filters go through the normalizer below, which is what makes two equivalent
 * renders produce the same key. Passing a raw object literal would work today
 * but breaks the moment a caller builds it with a different key order, because
 * TanStack Query hashes the key **structurally** — so the normalization is the
 * guarantee, not a nicety. This is the stricter pattern of
 * `features/properties/hooks/query-keys.ts` rather than cleaning's loose literal.
 */
export const reviewsKeys = {
  list: (
    tenantId: string,
    filters: ReviewFilters,
    page: number,
  ): QueryKey =>
    tenantScopedKey(
      tenantId,
      "reviews",
      normalizeReviewFilters(filters, page),
    ),

  /**
   * The prefix every list key shares — what `useRespondToReview` and
   * `useCreateReview` invalidate (design D8, D11). Invalidating the prefix
   * reaches every filter/page combination without enumerating them, which is
   * the only thing that reflects a row moving out of the active filter: the
   * `PATCH`/`POST` responses are a single review and know nothing about `total`
   * or the page it was on.
   */
  listPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "reviews"),

  detail: (tenantId: string, reviewId: string): QueryKey =>
    tenantScopedKey(tenantId, "review-detail", { reviewId }),

  draft: (tenantId: string, reviewId: string): QueryKey =>
    tenantScopedKey(tenantId, "review-draft", { reviewId }),

  properties: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "review-properties"),
} as const;

/**
 * Emit the filters with their keys in a FIXED order, dropping the ones that are
 * `undefined`, and canonicalizing the page (design D7).
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
export function normalizeReviewFilters(
  filters: ReviewFilters,
  page?: number,
): Record<string, string | number | null> {
  const normalized: Record<string, string | number | null> = {};
  if (filters.channel !== undefined) {
    normalized.channel = filters.channel;
  }
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
  if (filters.ratingMax !== undefined) {
    normalized.ratingMax = filters.ratingMax;
  }
  if (filters.ratingMin !== undefined) {
    normalized.ratingMin = filters.ratingMin;
  }
  if (filters.sentiment !== undefined) {
    // `null` means "all" (the default on the wire); keep it in the key so
    // explicit `null` differs from no filter — the backend treats them
    // equivalently, but TanStack Query does not, and we want the right cache
    // entry either way.
    normalized.sentiment = filters.sentiment;
  }
  if (filters.status !== undefined) {
    normalized.status = filters.status;
  }
  return normalized;
}