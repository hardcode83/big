"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import { getTenantSettingsDataSource, type UserDto } from "../data";
import { tenantSettingsKeys } from "./query-keys";

/**
 * One user's detail (R1.3), including `INACTIVE`/`SUSPENDED` users — the
 * backend does not hide non-`ACTIVE` rows from this endpoint. Depends ONLY
 * on `getTenantSettingsDataSource()`, mirroring `useReservation`
 * (`features/reservations/hooks/use-reservations.ts`).
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Tenant settings requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useUser(userId: string): UseQueryResult<UserDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: tenantSettingsKeys.userDetail(tenantId, userId),
    queryFn: () => getTenantSettingsDataSource().getUser(tenantId, userId),
    retry: retryPolicy,
  });
}
