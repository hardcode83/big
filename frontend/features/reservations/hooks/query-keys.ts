import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { ReservationFilters } from "../data";

/**
 * Tenant-scoped query keys for the reservations resources (design D4 / D11).
 * Built on the shell's `tenantScopedKey`, so every key begins with
 * `['tenant', tenantId, ...]` and a cross-tenant key cannot be produced by
 * accident.
 *
 * The list key takes the filters object directly (precedent:
 * `dashboardKeys.propertyTimeline(tenantId, propertyId, filters)`). The
 * caller is responsible for passing an object whose key order is stable across
 * renders — that is what guarantees two equivalent renders produce the same
 * key and TanStack Query does not invalidate.
 */
export const reservationsKeys = {
  list: (tenantId: string, filters: ReservationFilters = {}): QueryKey =>
    tenantScopedKey(tenantId, "reservations-list", filters),
  detail: (tenantId: string, reservationId: string): QueryKey =>
    tenantScopedKey(tenantId, "reservations-detail", reservationId),
} as const;
