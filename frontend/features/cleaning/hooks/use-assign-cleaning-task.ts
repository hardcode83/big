"use client";

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import { getCleaningDataSource, type CleaningTask } from "../data";
import { cleaningKeys } from "./query-keys";

export interface AssignCleaningTaskInput {
  taskId: string;
  cleanerId: string;
}

/**
 * Assigns or reassigns one cleaning task (design D9).
 *
 * It **invalidates and never patches the cache optimistically**, which is what makes
 * R4.4 and R4.5 free rather than extra work: there is no instant in which a row shows
 * an assignment the backend did not confirm. `retry: false`, like
 * `features/guest-portal/hooks/use-checkin.ts` — a rejected write is not retried.
 *
 * The invalidation runs in `onSettled`, so **on failure as well as on success**: R4.5
 * asks for the list to be refreshed after a `404`/`409` precisely so a rejected
 * assignment cannot stay on screen. It targets the `['tenant', id, 'cleaning-tasks']`
 * prefix, which reaches every filter/page combination without enumerating them.
 *
 * Nor would patching be enough: assigning can move a task **out of the active filter**
 * (`CREATED` → `ASSIGNED` while filtering on `CREATED`), and only refetching the page
 * the current parameters describe reflects that — the `PATCH` response is a single task
 * and knows nothing about the page, `total` or `total_pages`.
 */
export function useAssignCleaningTask(): UseMutationResult<
  CleaningTask,
  Error,
  AssignCleaningTaskInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: ({ taskId, cleanerId }: AssignCleaningTaskInput) => {
      if (!tenantId) {
        throw new Error("Assigning a cleaning task requires a tenant context");
      }
      return getCleaningDataSource().assignTask(tenantId, taskId, cleanerId);
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
