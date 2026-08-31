"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { getSessionGeneration } from "@/lib/auth";

import { restoreCount } from "./restore-count";

import { getNotificationsDataSource, type NotificationList } from "../data";
import { notificationsKeys } from "./query-keys";
import { useNotificationsIdentity } from "./use-notifications-identity";

interface MarkReadContext {
  sessionGeneration: number;
  countPatched: boolean;
  previousCount?: number;
  previousLists: Array<[readonly unknown[], NotificationList | undefined]>;
}

/**
 * Acknowledge one notification, optimistically (R5.1, R5.3, R5.4, design D13).
 *
 * **This is the first `onMutate` in the repository**, and the precedent next door points the
 * other way: `features/pricing/hooks/use-decide-recommendation.ts` rejects optimism in
 * writing, because there a `409` is a normal outcome and an optimistic patch would have lied
 * in exactly that case. The divergence is reasoned, not a lapse: acknowledging is idempotent
 * (design D3) and can only fail on the network or with a `404`, never with a domain conflict
 * that would leave the row in a state the client cannot paint.
 *
 * `onMutate` stamps `readAt` on the cached row and decrements the counter, so R5.1's "without
 * waiting for the next polling cycle" is true at the instant of the click rather than up to
 * sixty seconds later. `onError` restores the exact snapshot — row **and** counter, because
 * restoring only one of them leaves the bell disagreeing with the list. `onSettled` invalidates
 * both families (R5.4), on failure as well as success: after a failure the client's belief
 * about that row is precisely what is in doubt.
 *
 * The counter is floored at zero. Without it a decrement racing an in-flight refetch could
 * paint `-1` on a bell, which is not a state the backend can produce.
 */
export function useMarkRead(): UseMutationResult<void, Error, string, MarkReadContext> {
  const identity = useNotificationsIdentity();
  const queryClient = useQueryClient();

  return useMutation<void, Error, string, MarkReadContext>({
    mutationFn: (notificationId: string) => {
      if (identity === null) {
        throw new Error("Acknowledging a notification requires a session");
      }
      return getNotificationsDataSource().markRead(identity.tenantId, notificationId);
    },
    retry: false,
    onMutate: async (notificationId: string) => {
      if (identity === null) {
        return {
          sessionGeneration: getSessionGeneration(),
          countPatched: false,
          previousLists: [],
        };
      }
      const sessionGeneration = getSessionGeneration();
      const unreadKey = notificationsKeys.unread(identity.tenantId, identity.userId);
      const listPrefix = notificationsKeys.listPrefix(identity.tenantId, identity.userId);

      // Stop in-flight refetches first: one landing after the patch would overwrite it with
      // the server's pre-acknowledgement answer and the row would flick back to unread.
      await queryClient.cancelQueries({ queryKey: unreadKey });
      await queryClient.cancelQueries({ queryKey: listPrefix });

      const previousCount = queryClient.getQueryData<number>(unreadKey);
      const previousLists = queryClient.getQueriesData<NotificationList>({
        queryKey: listPrefix,
      });

      const now = new Date().toISOString();
      let stamped = false;
      for (const [key, list] of previousLists) {
        if (!list) continue;
        const items = list.items.map((item) =>
          item.id === notificationId && item.readAt === null
            ? ((stamped = true), { ...item, readAt: now })
            : item,
        );
        queryClient.setQueryData<NotificationList>(key, { ...list, items });
      }
      // Only decrement when a row actually moved from unread to read. Acknowledging one that
      // was already read is a success (R1.3) and must not take a second off the bell.
      const countPatched = stamped && previousCount !== undefined;
      if (countPatched) {
        queryClient.setQueryData<number>(unreadKey, Math.max(0, previousCount! - 1));
      }

      return { sessionGeneration, countPatched, previousCount, previousLists };
    },
    onError: (_error, _notificationId, context) => {
      if (identity === null || context === undefined) {
        return;
      }
      // R3.4: the session may have ended while this request was in flight. On a `401` the
      // authenticated client purges the whole `QueryClient` BEFORE the request rejects, so a
      // revert that trusted its snapshot would write the departing user's rows and counter
      // back into a cache that was just emptied so the next person in this tab cannot read
      // them. `sessionGeneration` moves on every token write and every clear, so this is a
      // fact about the session rather than a guess about what React has flushed into this
      // closure. Found by the section-5 security panel.
      if (context.sessionGeneration !== getSessionGeneration()) {
        return;
      }
      const unreadKey = notificationsKeys.unread(identity.tenantId, identity.userId);
      restoreCount(queryClient, unreadKey, {
        patched: context.countPatched,
        previousCount: context.previousCount,
      });
      for (const [key, list] of context.previousLists) {
        queryClient.setQueryData<NotificationList>(key, list);
      }
    },
    onSettled: () => {
      if (identity === null) {
        return;
      }
      void queryClient.invalidateQueries({
        queryKey: notificationsKeys.unread(identity.tenantId, identity.userId),
      });
      void queryClient.invalidateQueries({
        queryKey: notificationsKeys.listPrefix(identity.tenantId, identity.userId),
      });
    },
  });
}
