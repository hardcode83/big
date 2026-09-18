// Barrel for the cleaner's feature. The two `(field)/cleaner` pages import
// their view from here (design D1).
export { CleanerTaskListView } from "./components/list/cleaner-task-list-view";
export { CleanerTaskDetailView } from "./components/detail/cleaner-task-detail-view";
// The cleaning-task messages hooks/types are also the manager's surface's
// only path to the thread's data (staff-messaging-manager-view design D5) —
// `features/cleaning/` reuses them rather than duplicating the hooks, and
// must reach them through this public entry point, never the internal
// `hooks/`/`data/` paths (eslint `no-restricted-imports`, design D2).
export {
  useCleanerTaskMessages,
  useSendCleanerTaskMessage,
} from "./hooks/use-cleaner-task-messages";
export type { SendCleanerTaskMessageVariables } from "./hooks/use-cleaner-task-messages";
export type { CleaningTaskMessage, PaginatedResponse } from "./data";