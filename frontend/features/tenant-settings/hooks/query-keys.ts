import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { UserFilters } from "../data/http/http-tenant-settings-source";
import type { UserRole, UserStatus } from "../dto";

/**
 * Tenant-scoped query keys for the tenant-settings resources (design
 * "Changes by area", D8). Built on the shell's `tenantScopedKey`, so every
 * key begins with `['tenant', tenantId, ...]` and a cross-tenant key cannot
 * be produced by accident — mirrors `reservationsKeys`
 * (`features/reservations/hooks/query-keys.ts`).
 */
export const tenantSettingsKeys = {
  usersList: (tenantId: string, filters: UserFilters = {}): QueryKey =>
    tenantScopedKey(tenantId, "users-list", filters),
  userDetail: (tenantId: string, userId: string): QueryKey =>
    tenantScopedKey(tenantId, "user-detail", userId),
  tenantDetail: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "tenant-detail"),
  /**
   * The on-demand "only active cleaner" count (R3.4, design D8) — a scalar
   * check, not a list to render, so it gets its own key shape distinct from
   * `usersList` even though it hits the same `GET /api/v1/users` endpoint
   * with `role`/`status`/`per_page=1` filters.
   */
  activeCleanerCount: (
    tenantId: string,
    role: UserRole,
    status: UserStatus,
  ): QueryKey => tenantScopedKey(tenantId, "active-cleaner-count", role, status),
} as const;
