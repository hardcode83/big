import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { TimelineFilters } from "../data";

/**
 * Tenant-scoped query keys for the dashboard resources (design D11). Built on the
 * shell's `tenantScopedKey`, so every key begins with `['tenant', tenantId, ...]`
 * and a cross-tenant key cannot be produced by accident.
 */
export const dashboardKeys = {
  cards: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "dashboard-cards"),
  propertyDetail: (tenantId: string, propertyId: string): QueryKey =>
    tenantScopedKey(tenantId, "property-detail", propertyId),
  propertyTimeline: (
    tenantId: string,
    propertyId: string,
    filters: TimelineFilters = {},
  ): QueryKey =>
    tenantScopedKey(tenantId, "property-timeline", propertyId, filters),
} as const;
