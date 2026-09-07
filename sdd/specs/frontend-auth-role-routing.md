# Frontend Auth Role Routing

## Purpose

The frontend application routes authenticated visitors to the shell that matches their role, defends UX-level access between roles on top of the session-aware guard already specified in `frontend-auth-session`, and resolves the post-login / post-tab-close decision at the application root without depending on the in-memory bearer. The changes implemented here cover six behaviours: role-based guard enforcement on the workspace and field shells, a one-tap intermediate landing for field users on shared devices, the migration of the session logout to a TanStack Query mutation, server-side discrimination between a stale presence cookie and a revoked JWT at `/`, the back-to-landing button on the login form purging the cookie before navigating, and the resulting `auth/me → 401 → purge cookie → render landing` path that lets a returning visitor land on the public landing instead of `/login`.

## Requirements

### Role-aware guard on protected shells

- WHEN an authenticated visitor opens `/dashboard`, any route under `/(workspace)/*`, `/cleaner`, `/tech` or `/platform`, THE SYSTEM SHALL render the segment's content only when `useAuth().user.role` belongs to the segment's allowed set: `[TENANT_OWNER, PROPERTY_MANAGER]` for the workspace shell, `[CLEANER]` for the cleaner shell, `[TECHNICIAN]` for the technician shell, `[SUPER_ADMIN]` for the platform console (`super-admin-console`).
- THE SYSTEM SHALL keep `ROLE_HOME` (`frontend/features/auth/lib/role-home.ts`) mapping `SUPER_ADMIN` to `/platform` — a role with no tenant of its own, so it never falls into the `/dashboard` default an unlisted role would get. `LoginForm`'s existing `roleHome(role)` redirect (used for every role but `CLEANER`/`TECHNICIAN`, which go through `/welcome` instead) needs no change to cover it.
- THE SYSTEM SHALL mount `/platform` under its own route group `app/(platform)/layout.tsx` — `AuthGuard allow={["SUPER_ADMIN"]}` wrapping a bare `ShellFrame` (topbar only, no sidebar, no bottom navigation, no footer) — never under `(workspace)/layout.tsx`'s `AuthGuard allow={["TENANT_OWNER", "PROPERTY_MANAGER"]}` or `(authenticated)/layout.tsx`'s no-`allow` guard: `SUPER_ADMIN` belongs to no tenant, so `WorkspaceShell`'s tenant selector and tenant-scoped navigation do not apply, and an unguarded group would let every other role see the console's content before a redirect effect fires.
- WHEN an authenticated visitor whose role is not in the segment's allowed set reaches one of those routes, THE SYSTEM SHALL redirect client-side to `/login?denied=role` and SHALL NOT render the segment's children.
- WHEN the visitor's session is in `anonymous` or `expired`, THE SYSTEM SHALL redirect to `/login?returnTo=<current pathname>` without evaluating the role allow-list.
- WHEN the visitor's session is in `loading` or `refreshing`, THE SYSTEM SHALL render a `StatePanel` with `aria-busy` and SHALL NOT evaluate the allow-list.
- THE SYSTEM SHALL keep `AuthGuard` typed with `allow?: readonly UserRole[]` (the `UserRole` union imported from the generated OpenAPI `components["schemas"]`). The default — when a layout omits `allow` — preserves the pre-change behaviour: any authenticated visitor passes.
- THE SYSTEM SHALL treat the role allow-list as UX protection only; the backend remains the authoritative enforcer and SHALL still reject with `403` any caller that bypasses the routing layer with a forged request.

### One-tap intermediate landing for field users

- WHEN `LoginForm` redirects after a successful login and the role resolved by `roleHome()` is `CLEANER` or `TECHNICIAN` and no valid `?returnTo=` is present, THE SYSTEM SHALL navigate to `/welcome?role=<role>` instead of directly to `/cleaner` or `/tech`.
- WHEN `/welcome` receives `?role=CLEANER` or `?role=TECHNICIAN` and the authenticated visitor's `useAuth().user.role` matches, THE SYSTEM SHALL render a `StatePanel` with the localized title `auth.welcome.title` and description `auth.welcome.body`, followed by a single `Button` whose `href` (via `next/link`) is `roleHome(role)` and whose `aria-label` is `auth.welcome.cta.<role>`.
- WHEN `/welcome` is reached without `?role`, with a `?role` that does not match the authenticated visitor's role, or while the session is still loading, refreshing, expired or anonymous, THE SYSTEM SHALL redirect (or, while waiting on the session, render a busy panel that then redirects) to `roleHome(user.role)` without exposing the intermediate screen.
- WHEN `/welcome` is reached, THE SYSTEM SHALL wrap it in an `AuthGuard` that accepts any authenticated role — the segment `(authenticated)` exists so the `Topbar` with `UserMenu` is mounted, giving the field user a way to close the session before committing to a shell.
- THE SYSTEM SHALL mount only the chrome that applies to a transition screen on the `(authenticated)` layout: `Brand` and `UserMenu` in the `topbar` slot, plus `SkipLink`; `ThemeSwitcher`, `LocaleSwitcher`, `PageTitle`, `sidebar`, `bottomNavigation` and `footer` SHALL NOT be mounted.

### Logout as a TanStack Query mutation

- WHEN the visitor confirms the logout dialog in `UserMenu`, THE SYSTEM SHALL invoke `useLogoutMutation().mutateAsync()` rather than the deprecated `useAuth().logout()`, and SHALL execute, in this order: `mutateAsync()` → `router.replace("/")` → `router.refresh()`.
- WHEN the mutation resolves (HTTP 2xx) or fails (5xx, network error), THE SYSTEM SHALL purge the session regardless of the outcome: `QueryClient` singleton cleared via the session cache purge helper, in-memory tokens cleared, and the `autohostai.session.present` cookie cleared. The local cleanup runs in the mutation's `try/finally` and is unconditional.
- WHEN the mutation fails with a transient error (status ≥ 500 or `NetworkError`), THE SYSTEM SHALL retry once using TanStack Query's `retry: 1` configured for the mutation; 4xx responses SHALL NOT trigger a retry.
- WHEN the mutation succeeds, THE SYSTEM SHALL call `queryClient.removeQueries({ queryKey: ["auth", "me"] })` so that the next `useAuth()` evaluation starts from `anonymous`.
- THE SYSTEM SHALL keep `useAuth().logout()` as a thin, deprecated wrapper that performs only the local cleanup (cache purge, token clear, cookie clear, status reset to `anonymous`) — without a server round-trip — so consumers outside `UserMenu` that still call it keep working without the network call. New call sites SHALL use `useLogoutMutation()` directly.

### Server-side discrimination of a stale presence cookie at the application root

- WHEN the visitor opens `/` without the `autohostai.session.present` cookie, THE SYSTEM SHALL render the public landing directly without making any request to the backend.
- WHEN the visitor opens `/` with the `autohostai.session.present` cookie present, THE SYSTEM SHALL call `GET /api/v1/auth/me` from the Server Component `RootPage` using `serverFetch` — a server-only helper that reads `getServerConfig().backendInternalUrl`, forwards the inbound `Cookie` header from `next/headers`, and applies `signal: AbortSignal.timeout(2000)`.
- WHEN `/auth/me` responds with a 2xx status, THE SYSTEM SHALL redirect to `/dashboard` with `redirect("/dashboard", "replace")` (a 307 Temporary Redirect).
- WHEN `/auth/me` responds with a 401 status, THE SYSTEM SHALL delete the `autohostai.session.present` cookie via `cookies().delete(SESSION_PRESENT_COOKIE)` and SHALL render the public landing — not `/login` — so the visitor can read what the product offers and decide whether to log in again.
- WHEN `/auth/me` fails with a 5xx status, a network error or a timeout, THE SYSTEM SHALL redirect to `/dashboard` without modifying the cookie; the failure is not equivalent to a logout and the cost of a stale cookie on the next visit is corrected by the 401 path.
- THE SYSTEM SHALL abort `/auth/me` after at most 2000 ms so that `/` never spends longer than two seconds in the cookie-present branch.
- THE SYSTEM SHALL keep `BACKEND_INTERNAL_URL` reader confined to `lib/api/server-client.ts` (the only consumer inside `lib/`); the rest of the frontend reads the public `apiBaseUrl` only. The proxy route `app/api/[...path]/route.ts` is not used for `/auth/me` from `RootPage`.

### Back-to-landing button purges the presence cookie before navigating

- WHEN the visitor opens `/login` and the `backToLanding` link is visible, THE SYSTEM SHALL render it as a `<button type="button">` (not an `<a>`) with `role="link"`, `aria-label` resolved via `auth.backToLanding` (the same key used before this change), and the default `tabIndex=0`.
- WHEN the visitor activates that button, THE SYSTEM SHALL execute, in this order: `clearSessionPresent()` → `router.replace("/")` → `router.refresh()`. The cookie purge must complete before the navigation is dispatched so that the next Server Component render of `/` sees the cookie absent and takes the cookie-absent branch (no network call, direct landing render).
- THE SYSTEM SHALL keep `clearSessionPresent()` as a thin helper on the auth session module that wraps `cookies().delete(SESSION_PRESENT_COOKIE)`. It is reused both here and from the mutation's `try/finally`.

### Returning visitor with a stale cookie lands on the public landing

- WHEN a visitor who authenticated in a previous runtime (so the in-memory JWT is gone but the browser still carries the long-lived `autohostai.session.present` cookie) opens the public URL, THE SYSTEM SHALL call `/auth/me` from `RootPage`, receive 401, delete the cookie, and render the public landing — in that sequence, with no redirect to `/login`.
- WHEN the same visitor opens the public URL without the cookie, THE SYSTEM SHALL render the public landing without any backend call.
- WHEN the same visitor opens the public URL with the cookie and a still-valid in-memory bearer, THE SYSTEM SHALL redirect to `/dashboard` — but the Server Component cannot verify the in-memory bearer, so this branch is reachable only via the client navigating to `/dashboard` directly (link, sidebar, URL paste) once the runtime mounts.
- THE SYSTEM SHALL NOT widen the cookie's `max-age` beyond the access-token lifetime (15 minutes) without introducing a refresh mechanism that the Server Component can consume; the asymmetry between the one-year cookie and the fifteen-minute access token is structural, and the 401-then-purge behaviour at `/` is the defence.

## Key files

- `frontend/features/auth/components/auth-guard.tsx` — `AuthGuard` with the optional `allow?: readonly UserRole[]` prop and the `/login?denied=role` redirect for authenticated visitors whose role is not allowed.
- `frontend/app/(workspace)/layout.tsx`, `frontend/app/(field)/cleaner/layout.tsx`, `frontend/app/(field)/tech/layout.tsx`, `frontend/app/(platform)/layout.tsx` — the four layouts that pass the segment-specific `allow` set to `AuthGuard`; the console's own screen (`super-admin-console`) is documented in `sdd/specs/super-admin-console.md`.
- `frontend/features/shell/navigation/route-registry.ts` — the `"platform"` `ShellProfile` value and its descriptor (`id: "platform"`, `pattern: "/platform"`, no `navigationGroup` — nothing else links to it, same treatment as `welcome`).
- `frontend/app/(authenticated)/layout.tsx` and `frontend/app/(authenticated)/welcome/page.tsx` — the `(authenticated)` route group and the one-tap `/welcome` screen for `CLEANER` and `TECHNICIAN`.
- `frontend/features/auth/components/login-form.tsx` — the `<button type="button">` that replaces the previous `<Link>` for `backToLanding`, with the handler order `clearSessionPresent() → router.replace("/") → router.refresh()`; also handles the `?denied=role` flash by showing `auth.deniedRole` and redirecting to `roleHome(user.role)`.
- `frontend/features/auth/hooks/use-logout-mutation.ts` — `useLogoutMutation`, a `useMutation` wrapper over `POST /api/v1/auth/logout` with `retry: 1`, `try/finally` local cleanup and `onSuccess` cache invalidation.
- `frontend/features/auth/components/user-menu.tsx` — `UserMenu` confirmation dialog and the `await logoutMutation.mutateAsync() → router.replace("/") → router.refresh()` flow.
- `frontend/lib/auth/auth-provider.tsx` — `logout()` kept as a deprecated local-only wrapper around the cleanup helpers.
- `frontend/lib/api/server-client.ts` — `serverFetch` (`import "server-only"`) that reads `BACKEND_INTERNAL_URL`, forwards the inbound `Cookie` header and applies a 2-second timeout.
- `frontend/app/page.tsx` — `RootPage` Server Component that calls `serverFetch("/api/v1/auth/me")` when the presence cookie is present and dispatches the 2xx/401/5xx branches described above.
- `frontend/features/auth/index.ts` — barrel that re-exports `useLogoutMutation` and `roleHome`.
- `frontend/locales/{es,en}/auth.json` — `deniedRole`, `welcome.title`, `welcome.body`, `welcome.cta.CLEANER`, `welcome.cta.TECHNICIAN`, plus the existing `backToLanding`, `logoutConfirmTitle`, `logoutConfirmBody`, `logoutConfirmCancel` and `logoutConfirmAction`.
