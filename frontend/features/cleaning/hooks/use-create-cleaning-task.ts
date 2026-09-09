"use client";

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getCleaningDataSource,
  type CleaningTask,
  type CreateCleaningTaskInput,
} from "../data";
import { cleaningKeys } from "./query-keys";

/**
 * Creates one cleaning task by hand (R1.2, R1.3).
 *
 * Same skeleton as `useAssignCleaningTask`: **no optimistic cache write**, just
 * an invalidation of `cleaningKeys.tasksPrefix(tenantId)` in `onSettled` — on
 * failure as well as on success (design D10). A creation changes `total` and
 * `total_pages` on every cached page, which only a refetch of the page the
 * current parameters describe can reflect; the `POST` response is a single
 * task and knows nothing about pagination. `retry: false` — a rejected write
 * is not retried.
 */
export function useCreateCleaningTask(): UseMutationResult<
  CleaningTask,
  Error,
  CreateCleaningTaskInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: (input: CreateCleaningTaskInput) => {
      if (!tenantId) {
        throw new Error("Creating a cleaning task requires a tenant context");
      }
      return getCleaningDataSource().createTask(tenantId, input);
    },
    retry: false,
    onSettled: () => {
      if (tenantId) {
        void queryClient.invalidateQueries({
          queryKey: cleaningKeys.tasksPrefix(tenantId),
        });
      }
    },
  });
}
