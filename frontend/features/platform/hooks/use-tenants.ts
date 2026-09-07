"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";

import { getPlatformDataSource, type TenantListDto } from "../data";
import { platformKeys } from "./query-keys";

/**
 * List tenants, paginated (R2.1, R2.6, design D2). No tenant id to gate the query on:
 * `SUPER_ADMIN` has none, and the whole point of this endpoint is "every tenant" — so, unlike
 * every tenant-scoped `use*` hook in this codebase, this one does not call `useAuth()` at all.
 */
export function useTenants(
  page: number = 1,
  perPage: number = 20,
): UseQueryResult<TenantListDto> {
  return useQuery({
    queryKey: platformKeys.tenantsList(page, perPage),
    queryFn: () => getPlatformDataSource().listTenants(page, perPage),
    retry: retryPolicy,
  });
}
