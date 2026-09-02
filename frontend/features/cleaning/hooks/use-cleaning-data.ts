"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import {
  getCleaningDataSource,
  type CleanerSummary,
  type CleaningTaskListItem,
  type CleaningTaskFilters,
  type PaginatedResponse,
  type PropertySummary,
} from "../data";
import { cleaningKeys } from "./query-keys";

/**
 * Read-side hooks for the cleaning view. They depend ONLY on the
 * `CleaningDataSource` interface, resolved through the composition point, so the
 * component tests swap the source without touching `lib/api`.
 *
 * Three independent queries, never one per row (design D2): the two catalogs are
 * keyed without the filters or the page, so TanStack Query shares one cached copy
 * across every row and across paging and filtering (R2.5).
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("The cleaning view requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useCleaningTasks(
  filters: CleaningTaskFilters,
  page: number,
): UseQueryResult<PaginatedResponse<CleaningTaskListItem>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleaningKeys.tasks(tenantId, filters, page),
    queryFn: () => getCleaningDataSource().listTasks(tenantId, filters, page),
    retry: retryPolicy,
  });
}

export function useCleanerDirectory(): UseQueryResult<CleanerSummary[]> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleaningKeys.cleaners(tenantId),
    queryFn: () => getCleaningDataSource().listCleaners(tenantId),
    retry: retryPolicy,
  });
}

export function usePropertyDirectory(): UseQueryResult<PropertySummary[]> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleaningKeys.properties(tenantId),
    queryFn: () => getCleaningDataSource().listProperties(tenantId),
    retry: retryPolicy,
  });
}
