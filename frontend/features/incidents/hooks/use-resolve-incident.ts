"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getIncidentsDataSource,
  type IncidentDetailDto,
} from "../data";
import { incidentsKeys } from "./query-keys";

export interface ResolveIncidentInput {
  incidentId: string;
  /**
   * Required by the backend (`maintenance.md` R4.2). Either a number or the
   * decimal string the schema accepts; the dialog enforces positive + two
   * decimals so a `422` is impossible from this UI.
   */
  finalCost: number | string;
}

/**
 * Resolves one incident from the dashboard card's blocked-transitions row
 * (proposal `blocked-transitions-web` R2.3, R3.1, R3.2).
 *
 * Like `useCancelCleaningTask`, **invalidates and never patches the cache
 * optimistically** (`sdd/specs/maintenance.md` R4.4 documents why — the cost
 * threshold may move the incident to `AWAITING_OWNER_APPROVAL` instead of
 * closing it, and the response shape then is not "resolved"). `retry: false`.
 *
 * `onSettled` invalidates four prefixes, all tenant-scoped:
 *
 *   - the dashboard card's `blocked-transitions` bucket — every page of the
 *     dashboard's blocked transitions, so the resolved stall disappears;
 *   - the dashboard cards (`['tenant', tenantId, 'dashboard-cards']`) — the
 *     `openIncidentsCount` cube (R6 of the design risks);
 *   - the dashboard property timeline (`['tenant', tenantId, 'property-timeline']`) —
 *     the timeline surfaces the resolution event and would otherwise stay stale;
 *   - `incidentsKeys.list(...)` and `incidentsKeys.detail(...)` — the incidents
 *     resource's own keys.
 *
 * The hook lives in `features/incidents` and cannot import the dashboard's
 * key factory (design D2); the key shapes for `blocked-transitions`,
 * `dashboard-cards` and `property-timeline` are reproduced from the
 * documented shape published by `tenantScopedKey` in `@/lib/query/query-keys`.
 */
export function useResolveIncident(): UseMutationResult<
  IncidentDetailDto,
  Error,
  ResolveIncidentInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: ({ incidentId, finalCost }: ResolveIncidentInput) => {
      if (!tenantId) {
        throw new Error("Resolving an incident requires a tenant context");
      }
      return getIncidentsDataSource().resolveIncident(
        tenantId,
        incidentId,
        finalCost,
      );
    },
    retry: false,
    onSettled: () => {
      if (!tenantId) {
        return;
      }
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "blocked-transitions"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "incidents-list"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "incidents-detail"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "dashboard-cards"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "property-timeline"],
      });
    },
  });
}