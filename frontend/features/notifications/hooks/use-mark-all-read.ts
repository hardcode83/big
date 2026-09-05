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

interface MarkAllReadContext {
  sessionGeneration: number;
  countPatched: boolean;
  previousCount?: number;
  previousLists: Array<[readonly unknown[], NotificationList | undefined]>;
}

/**
 * "Mark all as read" (R5.2), with the same optimism and the same reversal as `useMarkRead`
 * (R5.3, R5.4).
 *
 * Its scope is every unread notification of the token's user, never the page or filter on
 * screen — that is the backend's guarantee (design D6) and the reason the button can say
 * "all" honestly. The optimistic patch stamps every cached unread row and zeroes the counter,
 * which is the client-side shape of the same claim.
 *
 * It answers how many rows moved, and zero is a normal answer on an inbox already up to date
 * rather than a failure.
 */
export function useMarkAllRead(): UseMutationResult<
  number,
  Error,
  void,
  MarkAllReadContext
> {
  const identity = useNotificationsIdentity();
  const queryClient = useQueryClient();

  return useMutation<number, Error, void, MarkAllReadContext>({
    mutationFn: () => {
      if (identity === null) {
        throw new Error("Acknowledging notifications requires a session");
      }
      return getNotificationsDataSource().markAllRead(identity.tenantId);
    },
    retry: false,
    onMutate: async () => {
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

      await queryClient.cancelQueries({ queryKey: unreadKey });
      await queryClient.cancelQueries({ queryKey: listPrefix });

      const previousCount = queryClient.getQueryData<number>(unreadKey);
      const previousLists = queryClient.getQueriesData<NotificationList>({
        queryKey: listPrefix,
      });

      const now = new Date().toISOString();
      for (const [key, list] of previousLists) {
        if (!list) continue;
        queryClient.setQueryData<NotificationList>(key, {
          ...list,
          items: list.items.map((item) =>
            item.readAt === null ? { ...item, readAt: now } : item,
          ),
        });
      }
      queryClient.setQueryData<number>(unreadKey, 0);

      // Unconditional above, so the revert always has something to undo.
      return { sessionGeneration, countPatched: true, previousCount, previousLists };
    },
    onError: (_error, _variables, context) => {
      if (identity === null || context === undefined) {
        return;
      }
      // R3.4: the session may have ended while this request was in flight. On a `401` the
      // authenticated client purges the whole `QueryClient` BEFORE the request rejects, so a
      // revert that trusted its snapshot would write the departing user's rows and counter
      // back into a cache that was just emptied so the next person in this tab cannot read
      // them. `sessionGeneration` moves on every token write (`setSessionTokens`) and every
      // cache purge (`purgeSessionCache`) — not on a bare `clearSessionTokens()` — so this is
      // a fact about the session rather than a guess about what React has flushed into this
      // closure. Found by the section-5 security panel.
      if (context.sessionGeneration !== getSessionGeneration()) {
        return;
      }
      const unreadKey = notificationsKeys.unread(identity.tenantId, identity.userId);
      // Unconditional, unlike the first draft: `onMutate` writes the optimistic zero whether or
      // not there was a snapshot, so a revert that only ran when one existed left the bell
      // stuck at zero after a failed "mark all" — telling the user there is no work waiting
      // when there is. That is the exact state R5.3 forbids, and the `onSettled` invalidation
      // cannot heal it because the refetch fails for the same reason the write did.
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
