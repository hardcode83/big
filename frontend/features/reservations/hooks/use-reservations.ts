"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getReservationsDataSource,
  type ReservationDetailDto,
  type ReservationFilters,
  type ReservationList,
} from "../data";
import { reservationsKeys } from "./query-keys";

/**
 * Reservations data-access hooks (proposal R2 / R3). They depend ONLY on
 * `getReservationsDataSource()` (the composition point), never on a concrete
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
    throw new Error("Reservations requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useReservations(
  filters: ReservationFilters = {},
): UseQueryResult<ReservationList> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: reservationsKeys.list(tenantId, filters),
    queryFn: () => getReservationsDataSource().listReservations(tenantId, filters),
    retry: retryPolicy,
  });
}

export function useReservation(
  reservationId: string,
): UseQueryResult<ReservationDetailDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: reservationsKeys.detail(tenantId, reservationId),
    queryFn: () =>
      getReservationsDataSource().getReservation(tenantId, reservationId),
    retry: retryPolicy,
  });
}
