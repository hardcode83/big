/**
 * Tenant-scoped query keys for the dashboard's blocked-transitions section
 * (proposal `blocked-transitions-web` R1.4).
 *
 * Built on the shell's `tenantScopedKey`, so every key begins with
 * `['tenant', tenantId, 'blocked-transitions', page]` and a cross-tenant
 * key cannot be produced by accident.
 *
 * `invalidationsFromStalls` is the prefix the cancel-cleaning and
 * resolve-incident hooks use to invalidate the stalls bucket plus the
 * resource that owns the row (design D5): one prefix invalidates every
 * page for the tenant, so a mutation never leaves a stale row visible.
 */
import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

const STALLS_RESOURCE = "blocked-transitions";

export const stallsKeys = {
  all: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, STALLS_RESOURCE),
  list: (tenantId: string, page: number): QueryKey =>
    tenantScopedKey(tenantId, STALLS_RESOURCE, page),
} as const;