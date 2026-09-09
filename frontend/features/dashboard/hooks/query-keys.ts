import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";
import type { Locale } from "@/lib/config/constants";

import type { TimelineFilters } from "../data";

/**
 * Tenant-scoped query keys for the dashboard resources (design D11). Built on the
 * shell's `tenantScopedKey`, so every key begins with `['tenant', tenantId, ...]`
 * and a cross-tenant key cannot be produced by accident.
 *
 * The active locale is appended at the **end** of `scope` (design D7), never
 * inserted between `tenantId` and the resource: the two hand-written prefix
 * invalidations in `use-resolve-incident.ts` and `use-cancel-cleaning-task.ts`
 * (`["tenant", tenantId, "dashboard-cards"]`, `["tenant", tenantId,
 * "property-timeline"]`) rely on that ordering to keep matching, for both
 * locales at once, after this change.
 */
export const dashboardKeys = {
  cards: (tenantId: string, locale: Locale): QueryKey =>
    tenantScopedKey(tenantId, "dashboard-cards", locale),
  propertyDetail: (
    tenantId: string,
    propertyId: string,
    locale: Locale,
  ): QueryKey =>
    tenantScopedKey(tenantId, "property-detail", propertyId, locale),
  propertyTimeline: (
    tenantId: string,
    propertyId: string,
    filters: TimelineFilters,
    locale: Locale,
  ): QueryKey =>
    tenantScopedKey(tenantId, "property-timeline", propertyId, filters, locale),
} as const;
