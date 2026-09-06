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
  /**
   * The guest portal token's live status for one reservation (proposal R1.1 /
   * R2, design D7). Every mint/revoke/send mutation invalidates exactly this
   * key on success — never a broader prefix, since the status of one
   * reservation's token has no bearing on any other reservation's.
   */
  guestAccessTokenStatus: (tenantId: string, reservationId: string): QueryKey =>
    tenantScopedKey(tenantId, "guest-access-token-status", reservationId),
} as const;
