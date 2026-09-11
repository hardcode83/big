"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getReservationsDataSource,
  type CreateReservationInput,
  type ReservationDetailDto,
  type ReservationFilters,
  type ReservationList,
  type ReservationSummaryDto,
  type UpdateReservationInput,
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
class TenantContextError extends Error {
  readonly code = "TENANT_CONTEXT_REQUIRED" as const;

  constructor() {
    super();
    this.name = "TenantContextError";
  }
}

function useTenantId(): string {
  const { user } = useAuth();
  const tenantId = user?.tenant_id;
  if (typeof tenantId !== "string" || tenantId.trim().length === 0) {
    throw new TenantContextError();
  }
  return tenantId;
}

async function invalidateReservationQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  tenantId: string,
  reservationId?: string,
): Promise<void> {
  const invalidations = [
    queryClient.invalidateQueries({
      queryKey: reservationsKeys.listPrefix(tenantId),
    }),
  ];
  if (reservationId) {
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: reservationsKeys.detail(tenantId, reservationId),
      }),
    );
  }
  await Promise.all(invalidations);
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

export function useCreateReservation(): UseMutationResult<
  ReservationSummaryDto,
  Error,
  CreateReservationInput
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateReservationInput) =>
      getReservationsDataSource().createReservation(tenantId, input),
    retry: false,
    onSettled: async () => {
      await invalidateReservationQueries(queryClient, tenantId);
    },
  });
}

export interface UpdateReservationVariables {
  reservationId: string;
  input: UpdateReservationInput;
}

export function useUpdateReservation(): UseMutationResult<
  ReservationSummaryDto,
  Error,
  UpdateReservationVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ reservationId, input }: UpdateReservationVariables) =>
      getReservationsDataSource().updateReservation(tenantId, reservationId, input),
    retry: false,
    onSettled: async (_data, _error, variables) => {
      await invalidateReservationQueries(queryClient, tenantId, variables.reservationId);
    },
  });
}

export interface CancelReservationVariables {
  reservationId: string;
}

export function useCancelReservation(): UseMutationResult<
  void,
  Error,
  CancelReservationVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ reservationId }: CancelReservationVariables) =>
      getReservationsDataSource().cancelReservation(tenantId, reservationId),
    retry: false,
    onSettled: async (_data, _error, variables) => {
      await invalidateReservationQueries(queryClient, tenantId, variables.reservationId);
    },
  });
}
