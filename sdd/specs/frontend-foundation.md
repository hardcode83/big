# Frontend Foundation (Application Shell)

## Purpose

The frontend is a Next.js App Router application (TypeScript strict) that provides the **Application Shell**: the common layout, responsive navigation, base routes, and localized placeholders on which the product's functional modules are built progressively. It renders without a backend and contains no business logic, workflows, backend integrations, or authentication — those arrive in later changes. Its foundation defines the architectural boundaries, cross-cutting UI conventions, and extension points every future frontend module inherits.

## Requirements

### Architecture and dependency boundaries

- THE SYSTEM SHALL use Next.js (App Router) with TypeScript in `strict` mode; a type error fails `npm run typecheck`.
- THE SYSTEM SHALL organize code into layers with a one-directional dependency rule `app → features → components / lib`, enforced by ESLint `no-restricted-imports`: `components/` and `lib/` never import `app/` or `features/`, and a feature never imports another feature's internals (only its public `@/features/<name>` entry point).
- WHEN a future functional surface is added, THE SYSTEM SHALL provide a modular location (`features/<feature>/`) without requiring business logic in shared components.
- THE SYSTEM SHALL keep layouts, pages, and the shell chrome (shell wrappers, `ShellFrame`, `Topbar`, `Brand`, `SkipLink`, `PageHeader`, `RoutePlaceholder`) as Server Components, resolving their static text on the server via `getServerT`; `"use client"` is confined to interactive islands (active navigation, sidebar/collapse and drawer trigger backed by Zustand, bottom navigation, locale switcher, breadcrumbs/page title, overlay auto-close).
- THE SYSTEM SHALL support route-level code splitting: the navigation registry is serializable (icon names, not component imports), so future modules stay out of the shell bundle until their route is navigated.

### Application Shell and responsive navigation

- WHEN the frontend starts, THE SYSTEM SHALL render the complete Application Shell without requiring a functional backend, and redirect `/` to `/dashboard`.
- THE SYSTEM SHALL provide five independent sibling shells selected by static route group: WorkspaceShell (`workspace`), CleanerShell (`cleaner`), TechnicianShell (`technician`), PublicShell (`public`), and GuestShell (`guest`). There is no MaintenanceShell.
- WHEN the Workspace shell is displayed, THE SYSTEM SHALL provide sidebar + topbar on desktop (≥1024px, sidebar collapsible to an icon rail), a collapsible drawer on tablet (768–1023px), and topbar + fixed bottom navigation on mobile (<768px) with at most five destinations (Dashboard, Timeline, Cleaning, Incidents, and a "More" sheet). Responsive surfaces are selected via CSS media queries, not JavaScript viewport detection.
- THE SYSTEM SHALL make CleanerShell and TechnicianShell independent and mobile-first, rendering no artificial bottom navigation or sidebar when the profile has a single navigable destination; the public slug `/tech` is preserved while the internal profile is named `technician`.
- WHEN a user opens any PRD §24 route whose module is not implemented, THE SYSTEM SHALL render a localized planned-module placeholder ("En preparación" / "In preparation") within the common visual structure, containing no business logic, API calls, invented contracts, or business mock data.
- THE SYSTEM SHALL preserve access to the applicable primary destinations across desktop, tablet, and mobile layouts, driven by a single navigation registry.
- WHEN a user operates the shell by keyboard, THE SYSTEM SHALL provide a "skip to content" link, unique labelled landmarks (`header`, `nav`, `main`), a visible focus indicator, `aria-current` for the active route, `aria-expanded`/`aria-haspopup` for collapsible navigation, accessible names for icon-only controls, focus trap/return and Escape close for drawers, and ≥44×44px touch targets on bottom navigation, targeting WCAG 2.2 AA.

### Route registry

- THE SYSTEM SHALL maintain a single typed route registry (`features/shell/navigation/route-registry.ts`) covering exactly the surfaces defined in PRD §24 (21 descriptors), as the source of truth for navigation, breadcrumbs, metadata, and placeholders.
- A route descriptor SHALL carry only shell metadata (stable id, pattern, optional navigable `href`, i18n keys, serializable icon name, shell profile, match strategy, optional navigation group/order) and SHALL NOT carry permissions, endpoints, DTOs, data, counters, or business state.
- THE SYSTEM SHALL expose navigation only through per-profile selectors; there is no "all" selector, so a shell cannot render another profile's routes. Dynamic routes (`/properties/[id]`, `/cleaner/tasks/[id]`, `/tech/incidents/[id]`, `/guest/[token]`) carry no `href` and are not reachable from any menu.
- WHEN resolving the active route, THE SYSTEM SHALL match the most specific descriptor (exact, then longest valid prefix), normalizing trailing slash and ignoring query/hash; breadcrumbs are built from the descriptor's explicit key chain, never from raw path segments, and never expose IDs or tokens.

### Cross-cutting interface states

- THE SYSTEM SHALL provide reusable, accessible, mutually distinguishable conventions for loading (`aria-busy` status), error (`role="alert"`, retry only when a real reset callback is provided, never rendering raw error detail), empty (neutral, distinct from error/loading), and planned-module (`ModulePlaceholder`) states, all built on a shared `StatePanel` primitive and server-compatible.

### Internationalization (ES/EN)

- WHEN any visible string is rendered, THE SYSTEM SHALL resolve it through react-i18next keys present in both the `locales/es` and `locales/en` catalogs; no visible string is hardcoded (the only exception is the self-contained inline ES/EN catalog in `global-error.tsx`, which cannot depend on the i18n provider).
- THE SYSTEM SHALL resolve the locale per request from the non-sensitive `autohostai.locale` cookie, validated against `es | en` with `es` as the fallback, and synchronize `<html lang>`; an accessible topbar control switches ES/EN, updating i18next, the cookie, and `lang` without storing the locale in Zustand.
- IF a translation key is missing in either locale, THEN THE SYSTEM SHALL fail an automated catalog-parity test.

### Remote state, UI state, and API access

- WHEN a future module consumes remote data, THE SYSTEM SHALL route it through TanStack Query v5 with a tenant-scoped query-key factory that requires a non-empty `tenantId` (`['tenant', tenantId, resource, ...scope]`), making global/cross-tenant keys impossible to build by accident. The shell itself declares and runs no queries.
- THE SYSTEM SHALL limit Zustand to lightweight UI state (`use-shell-ui-store.ts`: per-profile sidebar collapse preference, ephemeral overlay flags) and SHALL NOT duplicate server state; only the sidebar-preference map is persisted, under the versioned key `autohostai.ui.shell.v1`, and overlays close on navigation.
- WHEN a future module performs an HTTP request, THE SYSTEM SHALL route it through the centralized `fetch` transport (`lib/api`), which is generic (base URL + PRD §23 error envelope), returns `unknown` at the boundary, never reads UI state, and exposes documented auth extension points (`getHeaders`, `onUnauthorized`) without implementing tokens. The shell performs no backend calls and invents no endpoints, DTOs, or payloads.

### Error boundaries

- WHEN an unrecoverable failure occurs in the RootLayout or its providers, THE SYSTEM SHALL render `global-error.tsx`, which owns its document, uses a self-contained localized catalog, manages initial focus, offers a real recovery action, and never exposes `error.message`, stack traces, secrets, or internal URLs.
- WHEN content within a shell segment fails, THE SYSTEM SHALL render that segment's `error.tsx` (composing `ErrorState`) within the content slot, preserving the shell chrome, without exposing the received error and offering retry only through App Router's `reset`.
- THE SYSTEM SHALL add no `loading.tsx`, Suspense, or artificial promises to static placeholders; a future `loading.tsx` composes `LoadingState` in its owning segment.

### Metadata

- THE SYSTEM SHALL produce localized App Router metadata from the route registry keys: a default title `AutoHostAI`, a `%s | AutoHostAI` template, a localized description, and generic Open Graph. Every surface is `noindex, nofollow`.
- WHEN metadata is generated for a dynamic route, THE SYSTEM SHALL use a generic localized label and SHALL NOT interpolate an id, token, or any `params` value (notably `/guest/[token]`); no `metadataBase`, canonical URL, or images are emitted without an authorized public URL.

### Configuration

- THE SYSTEM SHALL define a single configuration boundary (`lib/config`): `server.ts` (`server-only`) for private/runtime values, `public.ts` for an explicit allowlist of the serializable public snapshot, `runtime-config-provider.tsx` for client access, and `constants.ts` for non-sensitive defaults (locale `es`). Application code does not read `process.env` outside this boundary.
- THE SYSTEM SHALL keep `BACKEND_INTERNAL_URL` server-only and unread at shell render, expose a build-time public `NEXT_PUBLIC_APP_ENV`, and keep the feature-flag registry empty and allowlisted; no secret or non-allowlisted value reaches the browser.

### Authentication readiness (not implemented)

- THE SYSTEM SHALL document the future integration points for session context, authenticated transport, and route protection (an `AuthProvider` slot between i18n and query; API request-header/401 extension points; static-profile route groups) and SHALL NOT implement login, JWT issue/refresh, token persistence, RBAC, or functional route guards. The backend remains the authority for RBAC.

### Testing and documentation

- THE SYSTEM SHALL provide a Vitest + Testing Library + jest-dom + axe test setup, colocated tests, and versioned conventions documentation (`frontend/README.md`).
- WHEN the frontend is verified, THE SYSTEM SHALL run type-check, lint, tests, and a production build without depending on a backend or fictitious business data.

## Key files

- `frontend/app/` — RootLayout (server, providers + locale + metadata), route groups `(workspace)`/`(public)`/`(field)`/`(guest)`, 21 placeholder pages, five shell layouts, `global-error.tsx`, per-segment `error.tsx`.
- `frontend/features/shell/` — `navigation/` (route registry, selectors, active-route matching, breadcrumbs, route metadata), `state/use-shell-ui-store.ts`, `components/` (five shells + chrome: `ShellFrame`, `Topbar`, `Sidebar`, `BottomNavigation`, `MoreMenu`, `NavLink`, `Breadcrumbs`, `PageTitle`, `Brand`, `SkipLink`, `LocaleSwitcher`, `TabletNavTrigger`, `OverlayAutoCloser`, `RoutePlaceholder`, `PageHeader`).
- `frontend/components/` — `ui/` (shadcn primitives: Button, Sheet, Tooltip, Separator, Skeleton, Badge), `states/` (`StatePanel`, `LoadingState`, `ErrorState`, `EmptyState`, `ModulePlaceholder`).
- `frontend/lib/` — `api/` (transport + PRD §23 errors), `config/` (server/public/runtime boundary), `i18n/` (server/client init, locale resolution, catalogs), `query/` (client + tenant-scoped keys), `metadata/` (localized metadata builder), `utils.ts`.
- `frontend/locales/{es,en}/{common,navigation,states}.json` — translation catalogs.
- `frontend/{eslint.config.mjs,vitest.config.ts,tsconfig.json,components.json,test/}` — tooling and boundary enforcement.
