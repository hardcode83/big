"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

import { getApprovalsDataSource, type RespondOwnerApprovalInput } from "../data";
import { approvalsKeys } from "./query-keys";

/**
 * The owner's decision on one pending approval (R3.3, R3.4, design D10).
 *
 * Invalidates `approvalsKeys.listPrefix(tenantId)` on success, so both the
 * queue (no-status) and the history (`APPROVED`/`REJECTED`) query entries
 * refetch — one prefix reaches every filter combination, same as
 * `incidentsKeys.listPrefix` does for incidents.
 *
 * A `409` (`OwnerApprovalAlreadyAnsweredError`) invalidates the same prefix
 * (R3.4): the row on screen is, by definition, in a status this client no
 * longer believes — someone else answered it first — so the fix is the same
 * refresh a success gets, not a silent no-op. Mirrors
 * `useUploadIncidentPhoto`'s conditional-409-invalidation shape in
 * `features/incidents/hooks/use-incident-cycle.ts`; every other error
 * (403/422/5xx) leaves the cache alone, since none of those means the row is
 * stale.
 *
 * `retry: false` — mirrors `useResolveIncident`: a mutation is never silently
 * retried, since a second POST against an already-answered approval would be
 * exactly the `409` above.
 */
export function useRespondOwnerApproval(): UseMutationResult<
  void,
  Error,
  RespondOwnerApprovalInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: (input: RespondOwnerApprovalInput) => {
      if (!tenantId) {
        throw new Error("Responding to an approval requires a tenant context");
      }
      return getApprovalsDataSource().respond(tenantId, input);
    },
    retry: false,
    onSettled: (_data, error) => {
      if (!tenantId) {
        return;
      }
      const alreadyAnswered = error instanceof ApiError && error.status === 409;
      if (error && !alreadyAnswered) {
        return;
      }
      void queryClient.invalidateQueries({
        queryKey: approvalsKeys.listPrefix(tenantId),
      });
    },
  });
}
