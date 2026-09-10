import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { OwnerApprovalFilters } from "../data";

/**
 * Tenant-scoped query keys for the approvals resource (mirroring
 * `incidentsKeys`, design D4's precedent). Built on the shell's
 * `tenantScopedKey`, so every key begins with `['tenant', tenantId, ...]` and
 * a cross-tenant key cannot be produced by accident.
 *
 * The list key takes the filters object directly. The caller is responsible
 * for passing an object whose key order is stable across renders — that is
 * what guarantees two equivalent renders produce the same key and TanStack
 * Query does not invalidate.
 */
export const approvalsKeys = {
  list: (tenantId: string, filters: OwnerApprovalFilters = {}): QueryKey =>
    tenantScopedKey(tenantId, "approvals-list", filters),
  /** Prefix of `list`, so one invalidation reaches every filter/page combination. */
  listPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "approvals-list"),
} as const;
