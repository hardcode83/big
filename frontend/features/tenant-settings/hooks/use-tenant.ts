"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import { getTenantSettingsDataSource, type TenantDto } from "../data";
import { tenantSettingsKeys } from "./query-keys";

function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Tenant settings requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/**
 * The acting tenant plus its nested `TenantConfig` (R5.1). Depends ONLY on
 * `getTenantSettingsDataSource()`, mirroring `useReservation`.
 */
export function useTenant(): UseQueryResult<TenantDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: tenantSettingsKeys.tenantDetail(tenantId),
    queryFn: () => getTenantSettingsDataSource().getTenant(tenantId),
    retry: retryPolicy,
  });
}
