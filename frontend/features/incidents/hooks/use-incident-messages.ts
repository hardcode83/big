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
  getIncidentsDataSource,
  type IncidentMessage,
  type PaginatedResponse,
} from "../data";
import { incidentsKeys } from "./query-keys";

/**
 * Incident staff-thread hooks (proposal R2, design D2, D3, D4, D5).
 *
 * This module lives in the **shared** `features/incidents` package, but is
 * consumed only by `features/tech` (design D2): `IncidentDetailView` — the
 * manager's view — does not import anything from this file, so the manager
 * gains no surface from it (proposal, Out of scope).
 *
 * `useIncidentMessages` is lazy by design (D1, mirroring `cleaner`'s
 * `useCleanerTaskMessages`): fetching is gated by the `enabled` parameter the
 * caller passes — the sticky `hasOpenedMessagesTab` flag that `TechIncidentTabs`
 * (section 4) owns — so the request never fires before the technician opens
 * the Messages tab, and keeps firing once she has (R2.1).
 *
 * `useSendIncidentMessage` never patches the cache optimistically (D5,
 * Rejected): it invalidates `incidentsKeys.messagesPrefix` in `onSettled`, on
 * both success and failure, mirroring `use-incident-cycle.ts` — "no debe
 * haber un instante mostrando una transición que el backend no confirmó".
 */

/** Throws immediately outside an authenticated tenant context, like `useIncidents`/`useIncident` in `use-incidents.ts`. */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Incidents requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/** Tolerates a missing tenant, like the mutation hooks in `use-incident-cycle.ts` — the guard lives in `mutationFn`, not at render time. */
function useOptionalTenantId(): string | undefined {
  const { user } = useAuth();
  return user?.tenant_id ?? undefined;
}

/**
 * One page of an incident's staff thread (R2.1, D4). Page 1 is the oldest
 * messages; the caller advances `page` to load newer ones and appends them to
 * what is already shown (D4) — this hook only fetches one page at a time.
 */
export function useIncidentMessages(
  incidentId: string,
  page: number,
  enabled: boolean,
): UseQueryResult<PaginatedResponse<IncidentMessage>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: incidentsKeys.messages(tenantId, incidentId, page),
    queryFn: () =>
      getIncidentsDataSource().getIncidentMessages(tenantId, incidentId, page),
    enabled,
    retry: retryPolicy,
  });
}

export interface SendIncidentMessageVariables {
  content: string;
}

/**
 * Sends one message on the incident's staff thread (R2.2). On settle —
 * success or failure alike — invalidates every cached page of this incident's
 * thread (`incidentsKeys.messagesPrefix`), so a successful send is picked up
 * by the next refetch without a page reload (R2.2) and a failed one leaves
 * the cache consistent with what the backend actually holds (D5).
 */
export function useSendIncidentMessage(
  incidentId: string,
): UseMutationResult<
  IncidentMessage,
  Error,
  SendIncidentMessageVariables
> {
  const tenantId = useOptionalTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ content }: SendIncidentMessageVariables) => {
      if (!tenantId) {
        throw new Error("Sending an incident message requires a tenant context");
      }
      return getIncidentsDataSource().sendIncidentMessage(
        tenantId,
        incidentId,
        content,
      );
    },
    retry: false,
    onSettled: async () => {
      if (!tenantId) return;
      await queryClient.invalidateQueries({
        queryKey: incidentsKeys.messagesPrefix(tenantId, incidentId),
      });
    },
  });
}
