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
} as const;