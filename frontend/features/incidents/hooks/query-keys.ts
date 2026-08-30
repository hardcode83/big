import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { IncidentFilters } from "../data";

/**
 * Tenant-scoped query keys for the incidents resources (design D4).
 * Built on the shell's `tenantScopedKey`, so every key begins with
 * `['tenant', tenantId, ...]` and a cross-tenant key cannot be produced by
 * accident.
 *
 * The list key takes the filters object directly (precedent:
 * `reservationsKeys.list(tenantId, filters)`). The caller is responsible for
 * passing an object whose key order is stable across renders — that is what
 * guarantees two equivalent renders produce the same key and TanStack Query
 * does not invalidate.
 */
export const incidentsKeys = {
  list: (tenantId: string, filters: IncidentFilters = {}): QueryKey =>
    tenantScopedKey(tenantId, "incidents-list", filters),
  detail: (tenantId: string, incidentId: string): QueryKey =>
    tenantScopedKey(tenantId, "incidents-detail", incidentId),
  /**
   * The property context of one incident. This is **the same** key the list
   * and the detail consume, and that identity is what makes opening a row skip
   * a second request for its context (R1.3): the row and the detail read the
   * same cache entry, not two equivalent ones.
   */
  context: (tenantId: string, incidentId: string): QueryKey =>
    tenantScopedKey(tenantId, "incidents-context", incidentId),
  photos: (tenantId: string, incidentId: string): QueryKey =>
    tenantScopedKey(tenantId, "incidents-photos", incidentId),
  /** Prefix of `list`, so one invalidation reaches every filter/page combination. */
  listPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "incidents-list"),
} as const;