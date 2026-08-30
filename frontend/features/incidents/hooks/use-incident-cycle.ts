"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

import { useAuth } from "@/lib/auth";

import {
  getIncidentsDataSource,
  type IncidentDetailDto,
  type IncidentPhotoDto,
  type IncidentPhotoStage,
  type ResolveIncidentInput,
} from "../data";
import { incidentsKeys } from "./query-keys";

/**
 * The technician's cycle mutations (design D8).
 *
 * All of them invalidate and none of them patches the cache optimistically:
 * there must be no instant showing a transition the backend did not confirm,
 * which is exactly the case the `409` of R3.7 makes visible. `retry: false`,
 * because a refused write is not retried.
 *
 * The invalidation runs in `onSettled` — **on failure as well as on success**
 * (R3.6, R3.7). After a `409` the row on screen is, by definition, in a status
 * this client no longer believes, so a refresh is what makes the refused action
 * explicable. It is also what `conflictReason` reads to name the reason.
 */

/**
 * The five cycle actions of this hook. `resolve` is not one of them — closing
 * carries a body and its own gate, and lives in `useResolveIncident`.
 */
export type IncidentCycleAction =
  | "accept"
  | "reject"
  | "en-route"
  | "wait-parts"
  | "resume";

export interface IncidentCycleInput {
  incidentId: string;
  action: IncidentCycleAction;
  /** Only `accept` and `en-route` admit one; omitted means no body at all. */
  etaAt?: string;
}

export interface IncidentCycleOptions {
  /**
   * Called once a `reject` has succeeded and its cache entries are gone.
   *
   * The **navigation itself is the caller's**: this hook is part of the shared
   * incidents data layer, which the manager's `/incidents` screens consume too,
   * so a `/tech` route hardcoded here would bake one surface's vocabulary into
   * a module that belongs to all of them (design D1). D8 mandates the
   * behaviour — remove the entries, then leave — not where the URL lives.
   */
  onRejected?: () => void;
}

function useTenantId(): string | undefined {
  const { user } = useAuth();
  return user?.tenant_id;
}

export function useIncidentCycleAction({
  onRejected,
}: IncidentCycleOptions = {}): UseMutationResult<
  IncidentDetailDto,
  Error,
  IncidentCycleInput
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ incidentId, action, etaAt }: IncidentCycleInput) => {
      if (!tenantId) {
        throw new Error("The incident cycle requires a tenant context");
      }
      const source = getIncidentsDataSource();
      switch (action) {
        case "accept":
          return source.accept(tenantId, incidentId, etaAt);
        case "reject":
          return source.reject(tenantId, incidentId);
        case "en-route":
          return source.enRoute(tenantId, incidentId, etaAt);
        case "wait-parts":
          return source.waitParts(tenantId, incidentId);
        case "resume":
          return source.resume(tenantId, incidentId);
      }
    },
    retry: false,
    // **Awaited, not fire-and-forget.** React Query waits for a promise
    // returned from `onSettled` before the mutation settles, so awaiting the
    // invalidation is what makes D7 true rather than merely intended: the
    // consumer reads `incident.status` to pick one of the three `409` reasons
    // (R3.7), and with a `void`-discarded invalidation that read happened on
    // the render *before* the refetch landed — an incident the backend had
    // already closed showed «ya no encaja» for a full round trip before
    // correcting itself to «ya está cerrada», which is the wrong one of the
    // three. The await costs one refetch of latency on the error path and buys
    // the invariant the copy depends on.
    onSettled: async (_data, error, variables) => {
      if (!tenantId) return;
      // `reject` is the case apart (R3.5, D8). Once it succeeds the assignment
      // is gone and `GET /incidents/{id}` answers 404 to whoever refused, so
      // **invalidating the detail would be asking for a 404**: the two entries
      // are removed instead. A refusal that failed leaves the incident where it
      // was, so it refreshes like any other action.
      const refused = variables.action === "reject" && !error;
      if (refused) {
        queryClient.removeQueries({
          queryKey: incidentsKeys.detail(tenantId, variables.incidentId),
        });
        queryClient.removeQueries({
          queryKey: incidentsKeys.context(tenantId, variables.incidentId),
        });
        await queryClient.invalidateQueries({
          queryKey: incidentsKeys.listPrefix(tenantId),
        });
        onRejected?.();
        return;
      }
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: incidentsKeys.detail(tenantId, variables.incidentId),
        }),
        queryClient.invalidateQueries({
          queryKey: incidentsKeys.context(tenantId, variables.incidentId),
        }),
        queryClient.invalidateQueries({
          queryKey: incidentsKeys.listPrefix(tenantId),
        }),
      ]);
    },
  });
}

export interface ResolveIncidentVariables extends ResolveIncidentInput {
  incidentId: string;
}

export function useResolveIncident(): UseMutationResult<
  IncidentDetailDto,
  Error,
  ResolveIncidentVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ incidentId, ...input }: ResolveIncidentVariables) => {
      if (!tenantId) {
        throw new Error("Closing an incident requires a tenant context");
      }
      return getIncidentsDataSource().resolve(tenantId, incidentId, input);
    },
    retry: false,
    onSettled: (_data, _error, variables) => {
      if (!tenantId) return;
      void queryClient.invalidateQueries({
        queryKey: incidentsKeys.detail(tenantId, variables.incidentId),
      });
      void queryClient.invalidateQueries({
        queryKey: incidentsKeys.context(tenantId, variables.incidentId),
      });
      void queryClient.invalidateQueries({
        queryKey: incidentsKeys.listPrefix(tenantId),
      });
    },
  });
}

export interface UploadIncidentPhotoVariables {
  incidentId: string;
  file: File;
  stage: IncidentPhotoStage;
}

/**
 * Uploading a photo invalidates the photo list of that incident (R5.5): a
 * successful upload moves neither the status nor the list.
 *
 * A `409` also invalidates the detail: the refusal means the status this client
 * believes is stale — the incident was closed or sent to the owner while the
 * technician was choosing a file — so the screen has to re-read it. Why that is
 * the right response, and what the upload shows the technician afterwards, is
 * D8's; the trailing sentence that used to live here described the three-reason
 * message design that D8's amendment replaced.
 */
export function useUploadIncidentPhoto(): UseMutationResult<
  IncidentPhotoDto,
  Error,
  UploadIncidentPhotoVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ incidentId, file, stage }: UploadIncidentPhotoVariables) => {
      if (!tenantId) {
        throw new Error("Uploading a photo requires a tenant context");
      }
      return getIncidentsDataSource().uploadPhoto(
        tenantId,
        incidentId,
        file,
        stage,
      );
    },
    retry: false,
    onSettled: (_data, error, variables) => {
      if (!tenantId) return;
      void queryClient.invalidateQueries({
        queryKey: incidentsKeys.photos(tenantId, variables.incidentId),
      });
      if (error instanceof ApiError && error.status === 409) {
        void queryClient.invalidateQueries({
          queryKey: incidentsKeys.detail(tenantId, variables.incidentId),
        });
      }
    },
  });
}
