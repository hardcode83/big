// Server-composition API of the shell feature (design D2).
//
// This half is split from `index.ts` because the two halves have different audiences and
// only one of them is importable from a client graph. Everything exported here reaches
// `server-only` — the shells through `lib/theme/server`, `routeMetadata` through
// `lib/metadata/create-route-metadata` → `lib/i18n/server` — so a Client Component that
// imported it would fail `next build` with "It should only be used from a Server Component",
// even though `tsc` and the test suites stay green. That is exactly how it reached CI during
// `notifications-inbox-web`: the panel imported the barrel for its state hook and dragged the
// five shells into the browser bundle behind it.
//
// Only `app/` consumes this entry point, which is why the split costs nothing: the ESLint
// boundary restricts `@/features/*/**` for files under `features/`, and `app/` composes
// downstream layers freely (`eslint.config.mjs`). A feature that needs the shell imports
// `@/features/shell`, and that door is now client-safe by construction rather than by luck.
export { WorkspaceShell } from "./components/workspace-shell";
export { CleanerShell } from "./components/cleaner-shell";
export { TechnicianShell } from "./components/technician-shell";
export { PublicShell } from "./components/public-shell";
export { GuestShell } from "./components/guest-shell";
export { routeMetadata } from "./navigation/route-metadata";
