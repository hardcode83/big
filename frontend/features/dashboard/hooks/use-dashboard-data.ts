"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

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
 * The tenant id comes from the authenticated context. The guard owns UX access;
 * the backend remains the authority for tenant isolation.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Dashboard requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/**
 * A 4xx (e.g. a §23 404 not-found) is a definitive client error: retrying only
 * delays the localized error/not-found state behind TanStack Query's default
 * backoff. Retry only transient (5xx / network) failures, and only briefly.
 */
export { retryPolicy } from "@/lib/api/retry-policy";

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
