"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import {
  getIncidentsDataSource,
  type IncidentDetailDto,
  type TechnicianSummary,
} from "../data";
import type {
  AssignIncidentInput,
  TriageIncidentInput,
} from "../data/http/http-incidents-source";
import { incidentsKeys } from "./query-keys";

/**
 * The manager-side incident-management hooks: the technician directory
 * (read) plus the four mutations that classify, triage, assign and cancel
 * one incident (proposal R2, R3, R4, R5; design D8).
 *
 * None of the four mutations patches the cache optimistically — there must
 * be no instant showing a transition the backend has not confirmed yet
 * (R2.4, R6.1), the same criterion `use-incident-cycle.ts` follows. `retry:
 * false`, because a refused write is not retried.
 *
 * The invalidation runs in `onSettled`, **awaited** rather than
 * `void`-discarded (D8). That is the lesson `use-incident-cycle.ts` already
 * documents: `conflictReason` reads the `status` this invalidation just
 * refreshed, and a discarded invalidation would let the first render of a
 * `409` read the stale status and name the wrong reason for a whole trip
 * through the component tree. `use-resolve-incident.ts`'s `void`-per-call
 * style predates that lesson and is not the pattern to copy here.
 */
function useTenantId(): string | undefined {
  const { user } = useAuth();
  return user?.tenant_id ?? undefined;
}

/**
 * The tenant's technician roster (R2.1), unfiltered by `isActive` — the
 * caller decides whether an inactive technician is still selectable (UI
 * concern, section 4/5). Copied from `useCleanerDirectory`.
 */
export function useTechnicianDirectory(): UseQueryResult<TechnicianSummary[]> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: incidentsKeys.technicians(tenantId ?? ""),
    queryFn: () => {
      if (!tenantId) {
        throw new Error("The technician directory requires a tenant context");
      }
      return getIncidentsDataSource().listTechnicians(tenantId);
    },
    enabled: Boolean(tenantId),
    retry: retryPolicy,
  });
}

/**
 * Invalidates the three keys every one of the four mutations below shares:
 * the incident's detail, its property context, and the list prefix (R2.4,
 * R3.4, R4.3, R6.1, R6.3). Awaited, never `void`-discarded (D8).
 */
async function invalidateIncidentQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  tenantId: string,
  incidentId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: incidentsKeys.detail(tenantId, incidentId),
    }),
    queryClient.invalidateQueries({
      queryKey: incidentsKeys.context(tenantId, incidentId),
    }),
    queryClient.invalidateQueries({
      queryKey: incidentsKeys.listPrefix(tenantId),
    }),
  ]);
}

export interface ClassifyIncidentVariables {
  incidentId: string;
}

/** Force the classifier over one incident (R4.1, R4.3). No body. */
export function useClassifyIncident(): UseMutationResult<
  IncidentDetailDto,
  Error,
  ClassifyIncidentVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ incidentId }: ClassifyIncidentVariables) => {
      if (!tenantId) {
        throw new Error("Classifying an incident requires a tenant context");
      }
      return getIncidentsDataSource().classifyIncident(tenantId, incidentId);
    },
    retry: false,
    onSettled: async (_data, _error, variables) => {
      if (!tenantId) return;
      await invalidateIncidentQueries(queryClient, tenantId, variables.incidentId);
    },
  });
}

export interface TriageIncidentVariables extends TriageIncidentInput {
  incidentId: string;
}

/** Correct category, severity and/or estimated cost (R3.2, R3.4/D8). */
export function useTriageIncident(): UseMutationResult<
  IncidentDetailDto,
  Error,
  TriageIncidentVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ incidentId, ...input }: TriageIncidentVariables) => {
      if (!tenantId) {
        throw new Error("Triaging an incident requires a tenant context");
      }
      return getIncidentsDataSource().triageIncident(tenantId, incidentId, input);
    },
    retry: false,
    onSettled: async (_data, _error, variables) => {
      if (!tenantId) return;
      await invalidateIncidentQueries(queryClient, tenantId, variables.incidentId);
    },
  });
}

export interface AssignIncidentVariables extends AssignIncidentInput {
  incidentId: string;
}

/** Assign or reassign a technician (R2.1, R2.4, design D14). */
export function useAssignIncident(): UseMutationResult<
  IncidentDetailDto,
  Error,
  AssignIncidentVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ incidentId, ...input }: AssignIncidentVariables) => {
      if (!tenantId) {
        throw new Error("Assigning an incident requires a tenant context");
      }
      return getIncidentsDataSource().assignIncident(tenantId, incidentId, input);
    },
    retry: false,
    onSettled: async (_data, _error, variables) => {
      if (!tenantId) return;
      await invalidateIncidentQueries(queryClient, tenantId, variables.incidentId);
    },
  });
}

export interface CancelIncidentVariables {
  incidentId: string;
}

/**
 * Cancel the incident (R5.1, R5.3). In addition to the three common keys,
 * invalidates the dashboard's `blocked-transitions`, `dashboard-cards` and
 * `property-timeline` buckets (R5.2, D8) — the same literal key arrays
 * `use-resolve-incident.ts` reproduces, for the same reason: `features/incidents`
 * does not import the dashboard's key factory (design D2).
 */
export function useCancelIncident(): UseMutationResult<
  IncidentDetailDto,
  Error,
  CancelIncidentVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ incidentId }: CancelIncidentVariables) => {
      if (!tenantId) {
        throw new Error("Cancelling an incident requires a tenant context");
      }
      return getIncidentsDataSource().cancelIncident(tenantId, incidentId);
    },
    retry: false,
    onSettled: async (_data, _error, variables) => {
      if (!tenantId) return;
      await Promise.all([
        invalidateIncidentQueries(queryClient, tenantId, variables.incidentId),
        queryClient.invalidateQueries({
          queryKey: ["tenant", tenantId, "blocked-transitions"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["tenant", tenantId, "dashboard-cards"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["tenant", tenantId, "property-timeline"],
        }),
      ]);
    },
  });
}
