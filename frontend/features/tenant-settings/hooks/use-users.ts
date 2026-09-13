"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import { getTenantSettingsDataSource, type UserListDto } from "../data";
import type { UserFilters } from "../data/http/http-tenant-settings-source";
import { tenantSettingsKeys } from "./query-keys";

/**
 * The paginated user directory (R1.1, R1.2). Depends ONLY on
 * `getTenantSettingsDataSource()` (the composition point), never on a
 * concrete implementation, mirroring `useReservations`
 * (`features/reservations/hooks/use-reservations.ts`).
 *
 * The tenant id comes from the authenticated session, not from a prop or
 * route param — the guard owns UX access; the backend remains the authority
 * for tenant isolation (`user-management` §Aislamiento).
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Tenant settings requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useUsers(filters: UserFilters = {}): UseQueryResult<UserListDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: tenantSettingsKeys.usersList(tenantId, filters),
    queryFn: () => getTenantSettingsDataSource().listUsers(tenantId, filters),
    retry: retryPolicy,
  });
}
