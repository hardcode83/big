// Public API of the shell feature (design D2). app/ composes these entry points;
// internals stay private to the feature.
export { WorkspaceShell } from "./components/workspace-shell";
export { CleanerShell } from "./components/cleaner-shell";
export { TechnicianShell } from "./components/technician-shell";
export { PublicShell } from "./components/public-shell";
export { GuestShell } from "./components/guest-shell";
export { PageHeader } from "./components/page-header";
export { routeMetadata } from "./navigation/route-metadata";
