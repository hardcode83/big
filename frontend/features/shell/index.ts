// Public API of the shell feature (design D2). app/ composes these entry points;
// internals stay private to the feature.
//
// **This door is client-safe, and that is a contract, not an accident.** The five shells and
// `routeMetadata` live in `./server` instead, because each of them reaches `server-only` and a
// Client Component that imports this barrel would drag them into the browser bundle. Nothing
// catches that locally — `tsc` and the test suites pass — it only surfaces as a `next build`
// failure in CI. Keep it that way: anything added here must be importable from a Client
// Component, and anything that is not goes in `./server`.
export { PageHeader } from "./components/page-header";
// `notifications-inbox-web` D15 needs the profile as a TYPE: its destinations table is keyed
// by it, which is what makes "add a destination when `cleaner-app` ships" one cell rather than
// a search through components. Type-only, so it widens the runtime surface by nothing, and it
// goes through the barrel because the ESLint boundary forbids reaching into `navigation/`.
export type { ShellProfile } from "./navigation/route-registry";
// The panel slot of `notifications-inbox-web` D9. The shell owns the ephemeral overlay flags so
// `OverlayAutoCloser` can close them all on navigation; the panel lives in another feature,
// which must not deep-import this one's store. Narrow on purpose: the notifications slot and
// nothing else. This is the runtime import that made the client-safety of this barrel load
// bearing — before the split it pulled every shell in behind it.
export {
  useNotificationsPanel,
  type NotificationsPanelState,
} from "./state/use-notifications-panel";
