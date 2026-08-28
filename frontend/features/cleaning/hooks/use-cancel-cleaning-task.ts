"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import { getCleaningDataSource, type CleaningTask } from "../data";
import { cleaningKeys } from "./query-keys";

export interface CancelCleaningTaskInput {
  taskId: string;
  /**
   * Free text, non-blank, ≤ 500 chars. The backend contract documents the
   * limit (`cleaning-stall-blocks-next-stay` R3.1); the dialog enforces it
   * client-side so a `422` is impossible from this UI.
   */
  reason: string;
}

/**
 * Cancels one cleaning task from the dashboard card's blocked-transitions row
 * (proposal `blocked-transitions-web` R2.2, R3.1, R3.2).
 *
 * The hook **invalidates and never patches the cache optimistically**, just like
 * `useAssignCleaningTask`: the response carries a single task and knows
 * nothing about the page, the `total`, or the property's `cleaningStatus` and
 * `openIncidentsCount` cubes on the dashboard. `retry: false` — a rejected
 * write is not retried (R3.4: the backend's `409` is the authority, not a
 * flapping network).
 *
 * The invalidation runs in `onSettled`, so **on failure as well as on success**
 * (R3.3): a `409` re-reads the stalls bucket (the row may have been resolved
 * by another person) and the cleaning prefix (the underlying task may have
 * moved out of the active filter). It targets four prefixes — the three
 * design D5 names, plus the property timeline that records the cancellation:
 *
 *   - the dashboard card's `blocked-transitions` bucket — every page of the
 *     blocked transitions, so the resolved stall disappears without
 *     enumerating pages. The hook lives in `features/cleaning` and cannot
 *     import the dashboard's key factory (design D2); the key shape
 *     `['tenant', tenantId, 'blocked-transitions', ...]` is the contract
 *     documented by `tenantScopedKey` in `@/lib/query/query-keys` and by the
 *     `BlockedTransitionsSection`'s read hook.
 *
 *   - `cleaningKeys.tasksPrefix(tenantId)` — every cleaning-task key under
 *     the tenant (assign-cleaner and other consumers share the prefix).
 *
 *   - the dashboard cards (`['tenant', tenantId, 'dashboard-cards']`) — a
 *     cancellation moves the property's `operational_state` and its
 *     `cleaningStatus` cube, so the card behind the dialog is stale the
 *     instant the mutation lands. This is the "detalle de la propiedad
 *     afectada" of design D5, which the first cut of this hook omitted.
 *
 *   - the dashboard property timeline
 *     (`['tenant', tenantId, 'property-timeline']`) — the cancellation writes
 *     a timeline event, mirroring what `useResolveIncident` already does.
 */
export function useCancelCleaningTask(): UseMutationResult<
  CleaningTask,
  Error,
  CancelCleaningTaskInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: ({ taskId, reason }: CancelCleaningTaskInput) => {
      if (!tenantId) {
        throw new Error(
          "Cancelling a cleaning task requires a tenant context",
        );
      }
      return getCleaningDataSource().cancelTask(tenantId, taskId, reason);
    },
    retry: false,
    onSettled: () => {
      if (!tenantId) {
        return;
      }
      // The dashboard's blocked-transitions prefix; the read hook sits in
      // `features/dashboard/stalls` and would re-import this hook, which
      // design D2 forbids, so the prefix is reproduced here from the
      // documented shape rather than referenced.
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "blocked-transitions"],
      });
      void queryClient.invalidateQueries({
        queryKey: cleaningKeys.tasksPrefix(tenantId),
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