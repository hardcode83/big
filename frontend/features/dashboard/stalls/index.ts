/**
 * Barrel for the dashboard card's blocked-transitions feature
 * (proposal `blocked-transitions-web` D9).
 *
 * Only the names the card and the dashboard view consume are exported.
 * The internal hooks, source implementation and action-map are deliberately
 * not exported: a feature consumer reaches the public surface through
 * `features/dashboard` (the barrel), not through here.
 */

export { useBlockedTransitions } from "./hooks/use-blocked-transitions";
export { BlockedTransitionsSection } from "./components/blocked-transitions-section";
export { CancelCleaningDialog } from "./components/cancel-cleaning-dialog";
export { ResolveIncidentDialog } from "./components/resolve-incident-dialog";
export { actionMapFor, type ActionKind, type ClockTrigger } from "./lib/action-map";
export type {
  BlockedTransitionSummary,
  BlockedTransitionPage,
} from "./data/dto";
export { stallsKeys } from "./hooks/query-keys";