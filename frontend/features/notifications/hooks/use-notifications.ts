"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";

import { getNotificationsDataSource, type NotificationFilters, type NotificationList } from "../data";
import { ANONYMOUS_NOTIFICATIONS_KEY, notificationsKeys } from "./query-keys";
import { useNotificationsIdentity } from "./use-notifications-identity";

/**
 * One page of the caller's inbox (R4.5).
 *
 * **No `refetchInterval` here, and that is design D11 rather than an omission.** The counter
 * polls because a bell has to notice work arriving; a list that reloads itself while somebody
 * is reading it is a defect. It refreshes when the panel opens and when an acknowledgement
 * invalidates it, which is what R5.1 actually asks for.
 */
export function useNotifications(
  filters: NotificationFilters = {},
): UseQueryResult<NotificationList> {
  const identity = useNotificationsIdentity();
  return useQuery({
    queryKey: identity
      ? notificationsKeys.list(identity.tenantId, identity.userId, filters)
      : ANONYMOUS_NOTIFICATIONS_KEY,
    queryFn: () =>
      getNotificationsDataSource().listNotifications(identity!.tenantId, filters),
    enabled: identity !== null,
    retry: retryPolicy,
  });
}
