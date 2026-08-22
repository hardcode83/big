import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { CleaningTaskFilters } from "../data";

/**
 * Tenant-scoped query keys for the cleaning view. Built on the shell's
 * `tenantScopedKey`, so every key begins with `['tenant', tenantId, ...]` and a
 * cross-tenant key cannot be produced by accident.
 *
 * The filters and the page are part of the task key, so each combination is
 * cached apart (design D6). They all share the `['tenant', id, 'cleaning-tasks']`
 * prefix, which is what the assignment mutation invalidates to reach every
 * combination at once without enumerating them (design D9).
 */
export const cleaningKeys = {
  tasks: (
    tenantId: string,
    filters: CleaningTaskFilters,
    page: number,
  ): QueryKey =>
    tenantScopedKey(tenantId, "cleaning-tasks", {
      propertyId: filters.propertyId,
      status: filters.status,
      page,
    }),
  /** The prefix every task key shares — what design D9 invalidates. */
  tasksPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaning-tasks"),
  cleaners: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaning-cleaners"),
  properties: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaning-properties"),
} as const;
