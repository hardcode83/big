import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { PropertyFilters } from "../data";

/**
 * Tenant-scoped query keys for the properties resources (design D6).
 * Built on the shell's `tenantScopedKey`, so every key begins with
 * `['tenant', tenantId, ...]` and a cross-tenant key cannot be produced by
 * accident — `tenantScopedKey` throws on an empty tenant rather than silently
 * writing a global cache entry.
 *
 * The list key takes the filters object through `normalizePropertyFilters`,
 * which is what makes two equivalent renders produce the same key (R2.3).
 * Passing a raw object literal would work today but would break the moment a
 * caller built it with a different key order, and TanStack Query hashes the key
 * structurally — so the normalization is the guarantee, not a nicety.
 */
export const propertiesKeys = {
  list: (tenantId: string, filters: PropertyFilters = {}): QueryKey =>
    tenantScopedKey(
      tenantId,
      "properties-list",
      normalizePropertyFilters(filters),
    ),
} as const;

/**
 * Emit the filters with their keys in a FIXED order, dropping the ones that are
 * `undefined` (design D6, R2.3).
 *
 * Two properties this guarantees, both of which matter for cache correctness:
 *
 *  - **Stable order**: `{status, page}` and `{page, status}` describe the same
 *    request, and after normalization they produce the same key, so TanStack
 *    Query does not treat them as two entries and refetch on a re-render that
 *    happened to build the object differently.
 *  - **Absence, not emptiness**: a filter set to "all" is omitted entirely, so
 *    the key for "no status filter" is distinct from any key that carries a
 *    status — and never `{status: undefined}`, which would serialize
 *    differently depending on the caller.
 *  - **`page` is canonicalized to 1 when absent.** "No page" and "page 1" are
 *    the same request — the backend's `page` defaults to 1 — so they must not
 *    produce two cache entries. Without this, a caller doing `useProperties()`
 *    to mean "the first page" would populate an entry separate from the one the
 *    list actually renders, and neither would invalidate the other. Raised by
 *    the QA panel on sections 2–3.
 */
export function normalizePropertyFilters(
  filters: PropertyFilters,
): Record<string, string | number> {
  const normalized: Record<string, string | number> = {};
  if (filters.currentOperationalState !== undefined) {
    normalized.currentOperationalState = filters.currentOperationalState;
  }
  normalized.page = filters.page ?? 1;
  if (filters.perPage !== undefined) {
    normalized.perPage = filters.perPage;
  }
  if (filters.status !== undefined) {
    normalized.status = filters.status;
  }
  return normalized;
}
