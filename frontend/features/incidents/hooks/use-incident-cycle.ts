"use client";

import { useRouter } from "next/navigation";
import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

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

function useTenantId(): string | undefined {
  const { user } = useAuth();
  return user?.tenant_id;
}

export function useIncidentCycleAction(): UseMutationResult<
  IncidentDetailDto,
  Error,
  IncidentCycleInput
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  const router = useRouter();

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
    onSettled: (_data, error, variables) => {
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
      } else {
        void queryClient.invalidateQueries({
          queryKey: incidentsKeys.detail(tenantId, variables.incidentId),
        });
        void queryClient.invalidateQueries({
          queryKey: incidentsKeys.context(tenantId, variables.incidentId),
        });
      }
      void queryClient.invalidateQueries({
        queryKey: incidentsKeys.listPrefix(tenantId),
      });
      if (refused) {
        router.replace("/tech");
      }
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
 * Uploading a photo invalidates **only** the photo list of that incident
 * (R5.5): it moves neither the status nor the list.
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
    onSettled: (_data, _error, variables) => {
      if (!tenantId) return;
      void queryClient.invalidateQueries({
        queryKey: incidentsKeys.photos(tenantId, variables.incidentId),
      });
    },
  });
}
