"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getCleanerDataSource,
  type CleaningTaskMessage,
  type PaginatedResponse,
} from "../data";
import { cleanerKeys } from "./query-keys";

/**
 * Cleaning task staff-thread hooks (R1, design D3, D4, D5).
 *
 * `useCleanerTaskMessages` is lazy by design (D1): fetching is gated by the
 * `enabled` parameter the caller passes — the sticky `hasOpenedMessagesTab`
 * flag that section 2's `CleanerTaskTabs` owns — so the request never fires
 * before the cleaner opens the Messages tab, and keeps firing once she has
 * (R1.1).
 *
 * `useSendCleanerTaskMessage` never patches the cache optimistically (D5,
 * Rejected): it invalidates `cleanerKeys.messagesPrefix` in `onSettled`, on
 * both success and failure, mirroring the mutations in `use-cleaner-cycle.ts`
 * — "no debe haber un instante mostrando una transición que el backend no
 * confirmó".
 */

/** Throws immediately outside an authenticated tenant context, like the other read hooks in this module family (`use-cleaner-tasks.ts`). */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error(
      "The cleaner view requires an authenticated tenant context",
    );
  }
  return user.tenant_id;
}

/** Tolerates a missing tenant, like the mutation hooks in `use-cleaner-cycle.ts` — the guard lives in `mutationFn`, not at render time. */
function useOptionalTenantId(): string | undefined {
  const { user } = useAuth();
  return user?.tenant_id ?? undefined;
}

/**
 * One page of a cleaning task's staff thread (R1.1, D4). Page 1 is the
 * oldest messages; the caller advances `page` to load newer ones and appends
 * them to what is already shown (D4) — this hook only fetches one page at a
 * time.
 */
export function useCleanerTaskMessages(
  taskId: string,
  page: number,
  enabled: boolean,
): UseQueryResult<PaginatedResponse<CleaningTaskMessage>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleanerKeys.messages(tenantId, taskId, page),
    queryFn: () => getCleanerDataSource().getTaskMessages(tenantId, taskId, page),
    enabled,
    retry: retryPolicy,
  });
}

export interface SendCleanerTaskMessageVariables {
  content: string;
}

/**
 * Sends one message on the task's staff thread (R1.2). On settle — success
 * or failure alike — invalidates every cached page of this task's thread
 * (`cleanerKeys.messagesPrefix`), so a successful send is picked up by the
 * next refetch without a page reload (R1.2) and a failed one leaves the
 * cache consistent with what the backend actually holds (D5).
 */
export function useSendCleanerTaskMessage(
  taskId: string,
): UseMutationResult<
  CleaningTaskMessage,
  Error,
  SendCleanerTaskMessageVariables
> {
  const tenantId = useOptionalTenantId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ content }: SendCleanerTaskMessageVariables) => {
      if (!tenantId) {
        throw new Error("Sending a task message requires a tenant context");
      }
      return getCleanerDataSource().sendTaskMessage(tenantId, taskId, content);
    },
    retry: false,
    onSettled: async () => {
      if (!tenantId) return;
      await queryClient.invalidateQueries({
        queryKey: cleanerKeys.messagesPrefix(tenantId, taskId),
      });
    },
  });
}
