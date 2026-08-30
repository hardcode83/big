// Public boundary of the notifications feature (design D10, the `features/incidents/index.ts`
// mould). The three shells import `NotificationBell` from here and nothing else; the hooks,
// the keys and the data source are re-exported so one `@/features/notifications` import brings
// the whole feature into scope.
export { NotificationBell } from "./components/notification-bell";
export { NotificationInboxSheet } from "./components/notification-inbox-sheet";
export { NotificationRow } from "./components/notification-row";
export { useNotifications } from "./hooks/use-notifications";
export { useUnreadCount, UNREAD_POLL_INTERVAL_MS } from "./hooks/use-unread-count";
export { useMarkRead } from "./hooks/use-mark-read";
export { useMarkAllRead } from "./hooks/use-mark-all-read";
export { notificationsKeys } from "./hooks/query-keys";
export { mapNotificationsError } from "./lib/error-mapping";
export { notificationCopyKey } from "./lib/notification-copy";
export { notificationHref } from "./lib/notification-destinations";
export { getNotificationsDataSource } from "./data";
export type * from "./data";
