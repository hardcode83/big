// Public API of the shell feature (design D2). app/ composes these entry points;
// internals stay private to the feature.
export { WorkspaceShell } from "./components/workspace-shell";
export { CleanerShell } from "./components/cleaner-shell";
export { TechnicianShell } from "./components/technician-shell";
export { PublicShell } from "./components/public-shell";
export { GuestShell } from "./components/guest-shell";
export { PageHeader } from "./components/page-header";
export { routeMetadata } from "./navigation/route-metadata";
// `notifications-inbox-web` D15 needs the profile as a TYPE: its destinations table is keyed
// by it, which is what makes "add a destination when `cleaner-app` ships" one cell rather than
// a search through components. Type-only, so it widens the runtime surface by nothing, and it
// goes through the barrel because the ESLint boundary forbids reaching into `navigation/`.
export type { ShellProfile } from "./navigation/route-registry";
// The panel slot of `notifications-inbox-web` D9. The shell owns the ephemeral overlay flags so
// `OverlayAutoCloser` can close them all on navigation; the panel lives in another feature,
// which must not deep-import this one's store. Narrow on purpose: the notifications slot and
// nothing else.
export {
  useNotificationsPanel,
  type NotificationsPanelState,
} from "./state/use-notifications-panel";
