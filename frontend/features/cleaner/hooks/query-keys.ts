import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { CleaningFilters } from "../data";

/**
 * Tenant-scoped query keys for the cleaner's task app (design D3).
 *
 * Built on the shell's `tenantScopedKey`, so every key begins with
 * `['tenant', tenantId, ...]` and a cross-tenant key cannot be produced by
 * accident. Each resource keeps its own key so the list and the detail share
 * the `context` key — opening a task from the list does not refetch its
 * context (R1.3).
 *
 * The filter object travels with stable key order (`status` before any future
 * filter) and no `undefined` keys; two renders with equivalent filters produce
 * the same key.
 */
export const cleanerKeys = {
  list: (
    tenantId: string,
    filters: CleaningFilters,
    page: number,
  ): QueryKey =>
    tenantScopedKey(tenantId, "cleaner-tasks", {
      status: filters.status,
      page,
    }),
  /** The prefix every task key shares — what the mutations invalidate. */
  listPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaner-tasks"),
  detail: (tenantId: string, taskId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaner-task", taskId),
  context: (tenantId: string, taskId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaner-task-context", taskId),
  checklist: (tenantId: string, taskId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaner-task-checklist", taskId),
  photoRequirements: (tenantId: string, taskId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaner-task-photo-requirements", taskId),
  photos: (tenantId: string, taskId: string): QueryKey =>
    tenantScopedKey(tenantId, "cleaner-task-photos", taskId),
} as const;