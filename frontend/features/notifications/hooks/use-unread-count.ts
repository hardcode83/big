"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";

import { getNotificationsDataSource } from "../data";
import { ANONYMOUS_NOTIFICATIONS_KEY, notificationsKeys } from "./query-keys";
import { useNotificationsIdentity } from "./use-notifications-identity";

/** The cadence of R3.3, in milliseconds. Exported so the test names the same number once. */
export const UNREAD_POLL_INTERVAL_MS = 60_000;

/**
 * The bell's counter (R3.3, design D11).
 *
 * **This is the only polling query in the repository**, and the number is not a guess:
 * `dispatch_notifications` runs once a minute (`CADENCES` in
 * `backend/app/scheduler/schedule.py`), so asking more often cannot discover anything that
 * exists. `refetchIntervalInBackground: false` stops a hidden tab from asking at all — a
 * backgrounded browser has nobody looking at the bell.
 *
 * The listing deliberately does NOT poll (see `use-notifications.ts`): a list that reloads
 * under the finger of whoever is reading it is a defect, and R5.1's "without waiting for the
 * next cycle" is bought by the invalidation in `use-mark-read.ts`, not by a shorter interval.
 *
 * Disabled while there is no resolved session, so the field shells can render their topbar
 * during the guard's redirect without firing a request (D16).
 */
export function useUnreadCount(): UseQueryResult<number> {
  const identity = useNotificationsIdentity();
  return useQuery({
    queryKey: identity
      ? notificationsKeys.unread(identity.tenantId, identity.userId)
      : ANONYMOUS_NOTIFICATIONS_KEY,
    queryFn: () => getNotificationsDataSource().countUnread(identity!.tenantId),
    enabled: identity !== null,
    refetchInterval: UNREAD_POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
    retry: retryPolicy,
  });
}
