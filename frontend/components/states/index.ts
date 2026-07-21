// Public API for the shared state components. None of these modules are
// "use client", so importing from this barrel never forces a consumer tree to
// become a Client Component (design D8/D9, task 5.3).
export { StatePanel, type StatePanelProps } from "./state-panel";
export { LoadingState, type LoadingStateProps } from "./loading-state";
export { ErrorState, type ErrorStateProps } from "./error-state";
export { EmptyState, type EmptyStateProps } from "./empty-state";
export {
  ModulePlaceholder,
  type ModulePlaceholderProps,
} from "./module-placeholder";
