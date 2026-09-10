"use client";

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getCleaningDataSource,
  type CleaningTask,
  type CleaningValidationVerdict,
} from "../data";
import { cleaningKeys } from "./query-keys";

export interface ValidateCleaningTaskInput {
  taskId: string;
  verdict: CleaningValidationVerdict;
}

/**
 * Records a manager's verdict on one finished cleaning (R3.2).
 *
 * Same skeleton as `useAssignCleaningTask`: **no optimistic cache write**, just
 * an invalidation of `cleaningKeys.tasksPrefix(tenantId)` in `onSettled` — on
 * failure as well as on success (design D10). A validation can move a task
 * out of the active filter (e.g. filtering by `validation_status`), which
 * only a refetch of the page the current parameters describe can reflect.
 * `retry: false` — a rejected write is not retried.
 */
export function useValidateCleaningTask(): UseMutationResult<
  CleaningTask,
  Error,
  ValidateCleaningTaskInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: ({ taskId, verdict }: ValidateCleaningTaskInput) => {
      if (!tenantId) {
        throw new Error(
          "Validating a cleaning task requires a tenant context",
        );
      }
      return getCleaningDataSource().validateTask(tenantId, taskId, verdict);
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
