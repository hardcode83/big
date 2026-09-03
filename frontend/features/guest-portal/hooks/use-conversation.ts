"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getGuestPortalDataSource, type GuestPortalDTOs } from "../data";
import { guestKeys } from "./query-keys";
import { retryPolicy } from "@/lib/api/retry-policy";

/**
 * How often the thread is re-fetched while the tab is visible (R5.3, design D10).
 *
 * **Fifteen seconds is arithmetic, not taste.** The portal's throttle is 60 requests a minute
 * *per token, shared by all six routes* — one budget, not one per endpoint — and opening the
 * page already spends `info` and `checkin`. At 15s the thread costs 4/min, so three tabs open
 * on the same link still sit at 12/min. At 5s it would be 36/min, and a `429` there does not
 * degrade the conversation alone: the budget is shared, so it takes the whole page down with it.
 */
export const PORTAL_THREAD_POLL_MS = 15_000;

/**
 * The guest's own thread, re-fetched while the tab is visible and **not** while it is hidden.
 *
 * `refetchIntervalInBackground: false` is passed explicitly. **Not because the library defaults
 * it to `false`** — it has no default at all: the option is declared `refetchIntervalInBackground?:
 * boolean` and the only place it is read is `queryObserver`'s
 * `this.options.refetchIntervalInBackground || focusManager.isFocused()`, so leaving it unset is
 * merely *falsy* and lands on the same branch. Checked in `@tanstack/query-core` 5.101.2 rather
 * than assumed, because an earlier version of this comment claimed `false` was the default and a
 * reviewer then read the line as redundant.
 *
 * It is written out because R5.3 is a requirement about behaviour a reader has to be able to
 * verify, and a guarantee resting on an absent option is one nobody can see. What actually
 * implements it is `focusManager`, which subscribes to `visibilitychange` itself.
 * `use-conversation.test.tsx` hides the tab and asserts polling stops — and that test was
 * confirmed to go **red** when this flag is flipped to `true`, so it pins the behaviour rather
 * than describing it.
 *
 * No WebSocket and no SSE: the project has no realtime surface and this change does not open one.
 */
export function useConversation(token: string) {
  return useQuery({
    queryKey: guestKeys.conversation(token),
    // No `page`: the backend answers the most recent window when it is absent, which is the end
    // a conversation is read from (design D9).
    queryFn: () => getGuestPortalDataSource().getConversation(token),
    refetchInterval: PORTAL_THREAD_POLL_MS,
    refetchIntervalInBackground: false,
    retry: retryPolicy,
  });
}

/**
 * Sending one message.
 *
 * `retry: false` and not the shared policy: `retryPolicy` already refuses every `4xx`, so a
 * `429` would not be retried either way — but a **send** is not idempotent, and the backend says
 * so (each request is a new message). Making that explicit here means the guarantee does not
 * depend on reading a shared helper to find out what it does with a `5xx`.
 *
 * On success the thread key is invalidated rather than written to: the automatic reply is
 * produced in the same transaction as the guest's own message, so re-reading is what shows both
 * (R5.4). Writing the returned message into the cache by hand would show one and hide the other
 * until the next poll.
 */
export function usePostMessage(token: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: GuestPortalDTOs.PostMessage) =>
      getGuestPortalDataSource().postMessage(token, data),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: guestKeys.conversation(token) });
    },
  });
}
