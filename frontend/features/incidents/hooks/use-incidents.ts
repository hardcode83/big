"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getIncidentsDataSource,
  type IncidentDetailDto,
  type IncidentFilters,
  type IncidentList,
} from "../data";
import { incidentsKeys } from "./query-keys";

/**
 * Incidents data-access hooks (proposal R2 / R3). They depend ONLY on
 * `getIncidentsDataSource()` (the composition point), never on a concrete
 * implementation, so the source is replaced without touching the UI.
 *
 * The tenant id comes from the authenticated context. The guard owns UX
 * access; the backend remains the authority for tenant isolation.
 *
 * The shared `retryPolicy` from `@/lib/api/retry-policy` (introduced in
 * `guest-portal-web` and present in `main`) is reused: no 4xx retries, brief
 * 5xx/network retries. Detailed coverage lives in
 * `use-dashboard-data.test.tsx` and is not duplicated here — these tests
 * assert the wiring (the hook configures `retry: retryPolicy`), not the
 * policy's branch table.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user) {
    throw new Error("Incidents requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useIncidents(
  filters: IncidentFilters = {},
): UseQueryResult<IncidentList> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: incidentsKeys.list(tenantId, filters),
    queryFn: () => getIncidentsDataSource().listIncidents(tenantId, filters),
    retry: retryPolicy,
  });
}

export function useIncident(
  incidentId: string,
): UseQueryResult<IncidentDetailDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: incidentsKeys.detail(tenantId, incidentId),
    queryFn: () =>
      getIncidentsDataSource().getIncident(tenantId, incidentId),
    retry: retryPolicy,
  });
}