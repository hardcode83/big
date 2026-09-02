"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

import { useAuth } from "@/lib/auth";

import {
  getCleanerDataSource,
  type CleaningChecklistItem,
  type CleaningIncidentReportAck,
  type CleaningIncidentReportInput,
  type CleaningPhoto,
  type CleaningTask,
} from "../data";
import { cleanerKeys } from "./query-keys";

/**
 * The cleaner's cycle mutations (design D8).
 *
 * All of them invalidate and none of them patches the cache optimistically:
 * there must be no instant showing a transition the backend did not confirm,
 * which is exactly the case the `409` of R3.4 makes visible. `retry: false`,
 * because a refused write is not retried.
 *
 * The invalidation runs in `onSettled` — **on failure as well as on success**.
 * After a `409` the row on screen is, by definition, in a status this client
 * no longer believes, so a refresh is what makes the refused action explicable.
 * It is also what `conflictReason` reads to name the reason (D7).
 */

/**
 * The four cycle actions covered by `useCleanerTaskCycleAction`. `reject`,
 * `complete` and `uploadPhoto` are split out because they have distinct shapes
 * and distinct invalidation behaviour (D8).
 */
export type CleanerTaskCycleAction =
  | "accept"
  | "start"
  | "completeChecklistItem"
  | "reportIncident";

export interface CleanerTaskCycleInput {
  taskId: string;
  action: CleanerTaskCycleAction;
  /**
 **Only `completeChecklistItem` and `reportIncident` admit a body. The discriminated
 **union below carries each action's parameters.
 **/
  itemId?: string;
  input?: CleaningIncidentReportInput;
}

export interface CleanerTaskCycleOptions {
  /** Called once `accept`/`start`/`reportIncident` settle (success or fail). */
  onCompleted?: () => void;
}

function useTenantId(): string | undefined {
  const { user } = useAuth();
  return user?.tenant_id ?? undefined;
}

export function useCleanerTaskCycleAction(
  kind: CleanerTaskCycleAction,
  options: CleanerTaskCycleOptions = {},
): UseMutationResult<
  CleaningTask | CleaningChecklistItem | CleaningIncidentReportAck,
  Error,
  Omit<CleanerTaskCycleInput, "action">
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  const { onCompleted } = options;

  return useMutation<
    CleaningTask | CleaningChecklistItem | CleaningIncidentReportAck,
    Error,
    Omit<CleanerTaskCycleInput, "action">
  >({
    mutationFn: ({ taskId, itemId, input }: Omit<CleanerTaskCycleInput, "action">) => {
      if (!tenantId) {
        throw new Error(`The ${kind} cycle action requires a tenant context`);
      }
      const source = getCleanerDataSource();
      switch (kind) {
        case "accept":
          return source.acceptTask(tenantId, taskId);
        case "start":
          return source.startTask(tenantId, taskId);
        case "completeChecklistItem":
          if (!itemId) {
            throw new Error(
              "completeChecklistItem requires the itemId of the entry to tick",
            );
          }
          return source.completeChecklistItem(tenantId, taskId, itemId);
        case "reportIncident":
          if (!input) {
            throw new Error(
              "reportIncident requires a {title, description} input",
            );
          }
          return source.reportIncident(tenantId, taskId, input);
      }
    },
    retry: false,
    /**
     * Awaited, not fire-and-forget: `conflictReason` reads the refreshed task to
     * pick one of the three `409` reasons (D7, R7.3), and the consumer must
     * read that status from the refresh that has actually landed, not from the
     * one before the mutation. The cost is one refetch of latency on the
     * error path; the win is that the reason copy is correct.
     */
    onSettled: async (_data, _error, variables) => {
      if (!tenantId) return;
      const { taskId } = variables;
      const targets: Array<ReturnType<typeof cleanerKeys.detail>> = [
        cleanerKeys.detail(tenantId, taskId),
      ];
      if (kind === "completeChecklistItem") {
        targets.push(cleanerKeys.checklist(tenantId, taskId));
      }
      targets.push(cleanerKeys.listPrefix(tenantId));
      await Promise.all(
        targets.map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
      );
      onCompleted?.();
    },
  });
}

export interface RejectCleaningTaskVariables {
  taskId: string;
}

export interface RejectCleaningTaskOptions {
  /**
   * Called once `reject` has succeeded and its cache entries are gone.
   *
   * The **navigation itself is the caller's**: this hook is part of the data
   * layer and must not import `next/navigation` (D8). The view does
   * `router.replace("/cleaner")` from this callback.
   */
  onRejected?: () => void;
}

export function useRejectCleaningTask(
  options: RejectCleaningTaskOptions = {},
): UseMutationResult<
  CleaningTask,
  Error,
  RejectCleaningTaskVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  const { onRejected } = options;

  return useMutation({
    mutationFn: ({ taskId }: RejectCleaningTaskVariables) => {
      if (!tenantId) {
        throw new Error("Rejecting a task requires a tenant context");
      }
      return getCleanerDataSource().rejectTask(tenantId, taskId);
    },
    retry: false,
    /**
     * `reject` is the case apart (R3.3, D8). Once it succeeds the assignment is
     * gone and `GET /cleaning-tasks/{id}` answers 404 to whoever refused, so
     * **invalidating the detail would be asking for a 404**: the two entries
     * are removed instead. A refusal that failed leaves the task where it
     * was, so it refreshes like any other action.
     */
    onSettled: async (_data, error, variables) => {
      if (!tenantId) return;
      const refused = !error;
      if (refused) {
        queryClient.removeQueries({
          queryKey: cleanerKeys.detail(tenantId, variables.taskId),
        });
        queryClient.removeQueries({
          queryKey: cleanerKeys.context(tenantId, variables.taskId),
        });
        await queryClient.invalidateQueries({
          queryKey: cleanerKeys.listPrefix(tenantId),
        });
        onRejected?.();
        return;
      }
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: cleanerKeys.detail(tenantId, variables.taskId),
        }),
        queryClient.invalidateQueries({
          queryKey: cleanerKeys.listPrefix(tenantId),
        }),
      ]);
    },
  });
}

export interface CompleteCleaningTaskVariables {
  taskId: string;
}

export interface CompleteCleaningTaskOptions {
  /**
   * Called once the close has succeeded and the refresh has landed, so the
   * view renders the reversible completion panel (R7.2).
   */
  onCompleted?: () => void;
}

/**
 * Closing the task (R7). Invalidates detail + list prefix and lets the view
 * render the reversible «Cerrada — Volver a mis tareas» panel through
 * `onCompleted`.
 *
 * The `409` reason is **not** read here — it is the view's job, after the
 * post-invalidation refetch (D7).
 */
export function useCompleteCleaningTask(
  options: CompleteCleaningTaskOptions = {},
): UseMutationResult<
  CleaningTask,
  Error,
  CompleteCleaningTaskVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  const { onCompleted } = options;

  return useMutation({
    mutationFn: ({ taskId }: CompleteCleaningTaskVariables) => {
      if (!tenantId) {
        throw new Error("Completing a task requires a tenant context");
      }
      return getCleanerDataSource().completeTask(tenantId, taskId);
    },
    retry: false,
    onSettled: async (_data, _error, variables) => {
      if (!tenantId) return;
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: cleanerKeys.detail(tenantId, variables.taskId),
        }),
        queryClient.invalidateQueries({
          queryKey: cleanerKeys.listPrefix(tenantId),
        }),
      ]);
      // Only on success (R7.2): a 409 leaves the task open for the view to
      // read the refreshed clause via `conflictReason`, not to render the
      // reversible completion panel over an action that did not succeed.
      if (!_error) {
        onCompleted?.();
      }
    },
  });
}

export interface UploadCleaningPhotoVariables {
  taskId: string;
  photoType: string;
  file: File;
}

/**
 * Uploading a photo invalidates the requirements and the gallery of that task
 * (R5.4): a successful upload changes both facts. The list prefix is **not**
 * invalidated — the status did not move and the row is unchanged.
 *
 * A `409` also invalidates the detail: the refusal means the status this
 * client believes is stale — the task moved out of `IN_PROGRESS` while the
 * cleaner was choosing a file — so the screen has to re-read it.
 */
export function useUploadCleaningPhoto(): UseMutationResult<
  CleaningPhoto,
  Error,
  UploadCleaningPhotoVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskId, photoType, file }: UploadCleaningPhotoVariables) => {
      if (!tenantId) {
        throw new Error("Uploading a photo requires a tenant context");
      }
      return getCleanerDataSource().uploadPhoto(
        tenantId,
        taskId,
        photoType,
        file,
      );
    },
    retry: false,
    onSettled: async (_data, _error, variables) => {
      if (!tenantId) return;
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: cleanerKeys.photoRequirements(tenantId, variables.taskId),
        }),
        queryClient.invalidateQueries({
          queryKey: cleanerKeys.photos(tenantId, variables.taskId),
        }),
      ]);
      if (_error instanceof ApiError && _error.status === 409) {
        await queryClient.invalidateQueries({
          queryKey: cleanerKeys.detail(tenantId, variables.taskId),
        });
      }
    },
  });
}