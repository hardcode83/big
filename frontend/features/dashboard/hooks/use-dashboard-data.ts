"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { DEV_TENANT_ID } from "@/lib/config/constants";

import {
  getDashboardDataSource,
  type PaginatedResponse,
  type PropertyDashboardCard,
  type PropertyDetail,
  type TimelineEntry,
  type TimelineFilters,
} from "../data";
import { dashboardKeys } from "./query-keys";

/**
 * Dashboard data-access hooks (proposal R4). They depend ONLY on the
 * `DashboardDataSource` interface, resolved through the composition point
 * (`getDashboardDataSource`) — never on a concrete implementation — so the mock
 * is replaced by HTTP without touching this file or the components that use it.
 *
 * ASSUMPTION / DEBT (auth-tenancy): the tenant id comes from `DEV_TENANT_ID`
 * until a session context exists; this is the single place hooks read it.
 */
function useTenantId(): string {
  return DEV_TENANT_ID;
}

/**
 * A 4xx (e.g. a §23 404 not-found) is a definitive client error: retrying only
 * delays the localized error/not-found state behind TanStack Query's default
 * backoff. Retry only transient (5xx / network) failures, and only briefly.
 */
export function retryPolicy(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failureCount < 2;
}

export function useDashboardCards(): UseQueryResult<
  PaginatedResponse<PropertyDashboardCard>
> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: dashboardKeys.cards(tenantId),
    queryFn: () => getDashboardDataSource().getDashboardCards(tenantId),
    retry: retryPolicy,
  });
}

export function usePropertyDetail(
  propertyId: string,
): UseQueryResult<PropertyDetail> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: dashboardKeys.propertyDetail(tenantId, propertyId),
    queryFn: () =>
      getDashboardDataSource().getPropertyDetail(tenantId, propertyId),
    retry: retryPolicy,
  });
}

export function usePropertyTimeline(
  propertyId: string,
  filters: TimelineFilters = {},
): UseQueryResult<PaginatedResponse<TimelineEntry>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: dashboardKeys.propertyTimeline(tenantId, propertyId, filters),
    queryFn: () =>
      getDashboardDataSource().getPropertyTimeline(
        tenantId,
        propertyId,
        filters,
      ),
    retry: retryPolicy,
  });
}
