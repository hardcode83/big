"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import { getPropertiesDataSource, type PropertyDetailDto } from "../data";
import { propertiesKeys } from "./query-keys";

/**
 * Fetches one property in full (proposal R2.2, design D7). Mirrors
 * `useProperties`: same tenant guard, same shared `retryPolicy` (no retry on
 * 4xx, two retries on 5xx/network, R3.7 of the list hook applies here too).
 *
 * `EditPropertyForm` calls this hook itself to pre-fill (design D7) rather
 * than receiving the detail as a prop — the dashboard's own
 * `usePropertyDetail`-shaped aggregate targets a different endpoint and must
 * not be conflated with this one.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Properties requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useProperty(id: string): UseQueryResult<PropertyDetailDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: propertiesKeys.detail(tenantId, id),
    queryFn: () => getPropertiesDataSource().getProperty(tenantId, id),
    retry: retryPolicy,
  });
}
