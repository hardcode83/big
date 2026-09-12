"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import { getTenantSettingsDataSource } from "../data";
import { tenantSettingsKeys } from "./query-keys";

function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Tenant settings requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/**
 * The tenant's count of `ACTIVE` `CLEANER` users (R3.4, design D8) — backs
 * the deactivate-confirmation "last active cleaner" warning. Fires
 * `GET /api/v1/users?role=CLEANER&status=ACTIVE&per_page=1` and exposes
 * `total` from the `UserPageResponse` envelope as the query's `data` — the
 * one row `per_page=1` returns is discarded, only the count matters.
 *
 * `enabled` has no default and must be passed explicitly: this is an
 * on-demand check the confirmation dialog fires only when the target row is
 * an `ACTIVE` `CLEANER`, never a query every row render triggers.
 */
export function useActiveCleanerCount(enabled: boolean): UseQueryResult<number> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: tenantSettingsKeys.activeCleanerCount(tenantId, "CLEANER", "ACTIVE"),
    queryFn: async () => {
      const page = await getTenantSettingsDataSource().listUsers(tenantId, {
        role: "CLEANER",
        status: "ACTIVE",
        perPage: 1,
      });
      return page.total;
    },
    retry: retryPolicy,
    enabled,
  });
}
