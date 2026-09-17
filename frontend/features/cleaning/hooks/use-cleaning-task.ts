"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import { getCleaningDataSource, type CleaningTask } from "../data";
import { cleaningKeys } from "./query-keys";

/**
 * Resolves the tenant id from the session, mirroring `useCleaningTasks`
 * (`hooks/use-cleaning-data.ts`): a missing tenant context is a programming
 * error, not a silently-disabled query.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error(
      "The cleaning task detail view requires an authenticated tenant context",
    );
  }
  return user.tenant_id;
}

/**
 * Reads one cleaning task by id (design D3, R1.1).
 *
 * `tenantId` is resolved by `useAuth()` so the page renders the detail without
 * the listing having mounted first (deep-link friendly, D6). `retry: false` —
 * a `404` is not transient, the same discipline as
 * `cleaning-task-manage-web` D10. `enabled: !!taskId` keeps the hook quiet
 * until the page actually has an id; the detail view never calls it without
 * one, but the guard is here so the hook cannot fire a half-formed request.
 *
 * The mapper `features/cleaning/lib/detail-error.ts` (section 3) reduces the
 * raw `isError` to the discriminated UI state the page renders; this hook
 * intentionally returns the raw query result so it stays a pure read-side
 * hook with no UI strings.
 */
export function useCleaningTask(
  taskId: string | undefined,
): UseQueryResult<CleaningTask> {
  const tenantId = useTenantId();

  return useQuery({
    queryKey: cleaningKeys.task(tenantId, taskId ?? ""),
    queryFn: () => {
      if (!taskId) {
        // `enabled` guards the path below; this throw keeps the contract honest
        // if a future caller bypasses the guard.
        throw new Error("useCleaningTask requires a taskId");
      }
      return getCleaningDataSource().getTask(tenantId, taskId);
    },
    enabled: !!taskId,
    retry: false,
  });
}