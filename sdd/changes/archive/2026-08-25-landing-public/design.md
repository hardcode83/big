# Design: landing-public

## Context

The frontend has five shells, a typed route registry, and a single
`createRouteMetadata` helper that bakes `robots: { index: false, follow: false }`
into every surface — `lib/metadata/create-route-metadata.ts:1-14` documents
this as an invariant. Today `app/(workspace)/page.tsx` is an unconditional
`redirect("/dashboard")`, so the public entry point of the app is the login
form. Auth is **fully client-side**: tokens live only in JS memory
(`lib/auth/session-store.ts:5-7`, `lib/auth/auth-provider.tsx:62-67`), and the
only Server Component that ever redirects is that one page. PublicShell
already carries the chrome the maqueta needs (`features/shell/components/public-shell.tsx:10-14`,
ShellFrame + Brand + Topbar + ShellFooter + SkipLink) and the design tokens
landed with `design-system-tokens` (Inter, JetBrains Mono, full theme set,
`text-display-*`/`text-data-mono` roles). The marketing page itself, two
locales with a full landing namespace, the indexable metadata exception, and
the server-side session-aware redirect for `/` are all new.

## Decisions

### D1 — The root takes the anonymous/authenticated decision on the server via a presence-only cookie

**Chosen:** Introduce a single non-sensitive `autohostai.session.present=1`
cookie (`Path=/`, `SameSite=Lax`, no token, no expiry beyond the browser
session). `AuthProvider` writes it on successful login and on `refresh`
success, clears it on logout, on `sessionExpired`, and on a refresh failure.
`app/page.tsx` becomes a Server Component that reads the cookie and either
`redirect("/dashboard", 307)` or renders `<PublicShell><LandingView />`.

Why: R1.2 is a **server-side** redirect. The current auth model never
touches the server — `frontend-auth-session.md` lines 39-42 forbids writing
tokens to any persistent store, the access JWT lives in `session-store.ts`
only, and `BACKEND_INTERNAL_URL` is server-only (`frontend-foundation.md:67`).
A top-level navigation request carries no `Authorization` header, so without
a signal the server cannot tell. The two precedents in the same shape are
`autohostai.locale` (`lib/i18n/server.ts:21`, `lib/config/constants.ts` —
`LOCALE_COOKIE`) and `autohostai.theme` (`lib/theme/server.ts:21-23`) — both
non-sensitive, both written by a client island and read on the server. A
presence flag is in the same shape: it carries no credential, no user id, no
PII, only "the JS runtime held a session at some point".

Rejected: **Client-side redirect only** — the landing flashes for ~150 ms
before `useEffect` redirects. Breaks R1.2's server-307 requirement and the
"sirve la landing al anónimo sin redirigir" half of R1.1 for anyone with a
warm browser.

Rejected: **Forging an HttpOnly session cookie at the next-auth proxy** —
turns the auth flow into a server roundtrip on every API call, changes the
shape of every authenticated request, and is a much larger change than this
entry can carry. The session store's in-memory model is correct; only the
landing's redirect needs the signal.

Rejected: **Redirect cookie set in the backend on `/auth/login`/`logout`** —
couples the marketing decision to the backend response shape (a new cookie
on every login/logout), makes the server flow depend on a backend change
that this entry does not own, and is one more contract for the same job the
presence flag does.

### D2 — `/` lives at `app/page.tsx` and reuses `PublicShell`; the existing `(workspace)/page.tsx` is removed

**Chosen:** Delete `app/(workspace)/page.tsx`. Add `app/page.tsx` as the
Server Component that does the cookie check (D1) and renders either the
redirect or `<PublicShell><LandingView /></PublicShell>`. `LandingView` is a
new Server Component in `features/landing/`. `PublicShell`'s docstring is
amended to declare it serves `/`, `/login`, and `/forgot-password`.

Why: a `(public)` group already exists for `/login` and `/forgot-password`,
but its layout does not (and should not) do a session check — that decision
is specific to `/`. Keeping the page at the root of `app/` (no group) is
the cleanest split: `(public)/login/page.tsx` and `(public)/forgot-password/page.tsx`
keep their existing routes and chrome untouched, and only the new page does
the conditional redirect. R3.2's "no shell nuevo" is satisfied by reusing
`PublicShell`; no new component, no new chrome.

Rejected: **New `(marketing)` route group** — adds a group for one route, and
the only thing the group's `layout.tsx` would do is the same cookie check.
Pushing it into the page itself is one file instead of two.

Rejected: **Keep `(workspace)/page.tsx` and add a cookie check inside it** —
the workspace layout mounts `AuthGuard`, which already redirects anonymous
users to `/login`. Having the landing inside `(workspace)` would mean the
landing renders inside `<WorkspaceShell>` (wrong chrome) or we have to
override the layout, neither of which is what we want.

### D3 — `PublicShell` gains an optional `marketingNav` slot; the chrome of `/login` and `/forgot-password` is unchanged

**Chosen:** Add `marketingNav?: ReactNode` to `PublicShell`'s props, rendered
in the `Topbar`'s **center** slot (between `Brand` and the locale/theme
switchers). The landing page passes a `<MarketingNav>` server component; the
two existing call sites pass nothing, and their chrome is byte-identical to
today's. `MarketingNav` renders only `Login` (a link to `/login`) and a
`#features` anchor — R3.3's "enlaces que tienen destino real".

Why: the maqueta's nav bar is the only piece of chrome the landing adds
over `/login`. Putting it inside the shell, behind an optional prop, keeps
the public shell single-sourced and lets `/login` keep its current narrow
topbar (which is the existing snapshot the design-system-tokens change
pinned). The center slot is empty for `/login` and `/forgot-password`,
so they do not regress.

Rejected: **New `MarketingShell` component** — duplicates `PublicShell`'s
chrome for one route; violates R3.2.

Rejected: **Render the nav bar inside `LandingView` and re-implement the
topbar layout** — every future public surface would either need to copy
that layout or import `LandingView`'s nav, and the center slot stops being
reusable.

### D4 — The indexable metadata exception is centralized by route name, not by flag

**Chosen:** Extend `lib/metadata/create-route-metadata.ts` with a new
`createLandingMetadata()` helper that builds the indexable block (title
outside the `%s | AutoHostAI` template, localized description, OG with
specific title/description/image, `metadataBase` from the public config
when set, `alternates.canonical` to its absolute URL, `robots: { index: true,
follow: true }`). The helper is the **only** path that emits
`index: true`; the existing `createRootMetadata` and
`createMetadataFromKeys` keep their `index: false` invariant. R2.3's
"declarando la landing como el único caso indexable **por nombre de ruta**"
is enforced by a single branch keyed on `route.id === "landing"`, and a
test asserts that **every** other descriptor yields `index: false` — so no
future page can flip a flag and become indexable by accident.

The OG image is generated at build time by `frontend/app/opengraph-image.tsx`
using `next/og`'s `ImageResponse` against the same emerald palette and
Inter typography the design tokens already publish (`app-version-visibility`
for the font loading pattern). No backend call, no external service — the
asset is shipped as a static PNG.

Rejected: **A generic `indexable: boolean` field on `ShellRouteDescriptor`** —
any page that adds the field becomes indexable. R2.3 explicitly forbids
this.

Rejected: **A generic `createIndexableMetadataFromKeys()` exposed for any
caller** — same problem; the helper's existence invites accidental use.
The landing-specific name documents the exception at the call site.

### D5 — `NEXT_PUBLIC_APP_URL` enters the public-config allowlist; dev gets an empty string, prod gets an absolute URL

**Chosen:** Add `appUrl: string` to `PublicRuntimeConfig`
(`lib/config/public.ts`), sourced from `NEXT_PUBLIC_APP_URL` and vetted by
the same shape guard the build identity uses (`""` for anything off-shape).
Empty in `.env.example` and in dev (no `metadataBase`, no `canonical`,
existing test in `create-route-metadata.test.ts:27` still passes for
non-landing routes). `createLandingMetadata()` reads it from the runtime
config and, when non-empty, sets `metadataBase`, the OG `url`, and
`alternates.canonical`; when empty it omits all three and falls back to the
"no public URL" posture that `frontend-foundation.md:60` already documents.

Why: indexable metadata needs an absolute URL for `canonical` and OG. Today
no public URL is authorized (the test at
`create-route-metadata.test.ts:27-28` pins this). The field goes through
the same allowlist as `apiBaseUrl`, `appVersion`, etc., so the snapshot
boundary guarantee in `frontend-foundation.md:67-69` still holds: nothing
non-allowlisted crosses the boundary.

Rejected: **Read `process.env.NEXT_PUBLIC_APP_URL` directly in the metadata
helper** — breaks the existing `app/proxy-scope.test.ts` invariant (only
`app/api/[...path]/route.ts` reads `process.env` outside the config layer)
and the `frontend-foundation.md:65` single-configuration-boundary rule.

### D6 — Stats block uses two product statements in `JetBrains Mono`, not the maqueta's invented numbers

**Chosen:** The stats block is two short lines rendered with the
`text-data-mono` token (no numeric values). The exact wording is the only
input this entry still needs from Jose (proposal §R5 calls it out explicitly)
and is captured as **OQ-1** below. The block's layout —two large mono lines
on a translucent card, same as the maqueta— is in scope; the words are not.

Rejected: **Publish the maqueta's "500+ Propiedades gestionadas" / "99%
Satisfacción de propietarios"** — directly contradicts `steering/product.md`
(2 viviendas Madrid, SaaS multi-tenant en fase futura) and the "nunca
maqueta visual" principle. Already declined by the proposal's R5.2.

### D7 — The `landing` namespace is registered in both locales with a parity test

**Chosen:** Add `frontend/locales/{es,en}/landing.json` with the full key
set (hero title + subtitle + eyebrow, four feature titles + four feature
bodies, two stat lines, CTA title + button label + button href, footer
columns: product / company / legal-with-empty-arrays-per-R3.3, copyright).
Register the namespace in `lib/i18n/resources.ts` (the import, the
`NAMESPACES` array, both the `es` and `en` resource tables). Add a test
that asserts `Object.keys(es.landing) === Object.keys(en.landing)` — the
same shape the existing per-namespace parity tests use. No string is
hardcoded in any component.

Why: the landing is almost entirely copy (proposal §R5.3 and the roadmap's
decision 5). The file is the largest locale catalogue in the project, and
`steering/frontend.md:18` and `steering/documentation.md:14` already require
this. A drift test is non-negotiable for a catalogue this size.

### D8 — The navigation bar renders `Login` and `#features`; `Pricing`, `Portfolio`, `Team`, `Sign Up` are not rendered

**Chosen:** `MarketingNav` is a server-rendered list with exactly two items
(a `Login` link to `/login` and a `#features` anchor that scrolls to the
features section of the landing). The other four items from the maqueta are
not rendered at all — no disabled state, no tooltip, no "coming soon".
R3.3 is the constraint.

Why: a "Sign Up" that does not sign anyone up is dishonest; a "Pricing"
link to a 404 is worse. The links come back when the pages they point to
exist — that is entries of their own, not this one.

### D9 — `LandingView` is a Server Component composed of section subcomponents

**Chosen:** `features/landing/components/landing-view.tsx` is the root
Server Component; it composes `Hero`, `FeaturesGrid` (with four `FeatureCard`
children), `StatsBand`, `FinalCta`, and `LandingFooter`. Each section is a
Server Component except any future island; the only client island in this
view is the `#features` smooth-scroll handler (small `useEffect`), if we
ship one — otherwise the anchor is a plain `<a href="#features">` and no JS
runs. The page's `generateMetadata` calls `createLandingMetadata()`.

Why: keeps the landing consistent with the "Server Components resolve
static text on the server" rule (`frontend-foundation.md:13-14`). All five
sections can be rendered server-side from the i18n catalogue without any
client state.

### D10 — The marketing nav's anchor link uses native `<a href="#features">`, no smooth-scroll JS

**Chosen:** The `#features` anchor is a plain `<a>` element. The browser's
default jump-to-anchor behavior does the rest. `scroll-behavior: smooth` is
added to `html` in `app/globals.css` (one CSS rule, no JS island needed).

Why: the proposal says the landing is the indexable surface and "una sola
isla cliente" is the only chrome the public shell admits. A `useEffect` for
smooth-scroll is the kind of client island that costs bundle size and
breaks the `getServerT`-only static copy pattern. The native anchor + a CSS
declaration is identical to the user and ships zero JS.

Rejected: **`useEffect` smooth-scroll handler** — adds a client island,
needs hydration, and `prefers-reduced-motion` already kills it via the
existing `globals.css` block (`design-system-tokens.md:45`).

### D11 — Spec and doc amendments land at archive time, not now

**Chosen:** This change does not edit `sdd/specs/frontend-foundation.md`,
`sdd/specs/guest-portal.md`, `sdd/steering/frontend.md`, or
`sdd/steering/documentation.md`. The amendments listed in the proposal's
"Affected specs" section (and the small amendment to
`frontend-auth-session.md` introduced by D1) are recorded as **archive
tasks** — they go in `/sdd:tasks` as concrete edits that `/sdd:archive` will
perform post-merge. `docs/landing.md` is created at archive time per R5.3.
The exact `frontend-auth-session.md` carve-out wording (Jose-approved 2026-08-24)
is: *"A single non-sensitive presence flag (`autohostai.session.present`)
is written on login and cleared on logout/expiry to enable the server-side
redirect for `/`; the flag carries no token, no credential, and no user
data."*

Why: shared rule 7 makes the archive step the only place that mutates
`specs/`; doing it earlier would force the next reviewer to chase drift
between the spec and the code on every iteration. The amendments are
mechanical (s/redirect/conditional redirect/, append the named exception)
and pin exactly what the merge proved.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Cookie + session signal | `frontend/lib/auth/session-store.ts`, `frontend/lib/auth/auth-provider.tsx`, `frontend/lib/auth/index.ts`, new `frontend/lib/auth/session-presence-cookie.ts` | New `session-presence-cookie.ts` exposes `markSessionPresent()`, `clearSessionPresent()` and the cookie name constant. `auth-provider.tsx` calls them at the same lifecycle points that already touch `setSessionTokens`/`clearSessionTokens`. |
| Cookie constants | `frontend/lib/config/constants.ts` | Add `SESSION_PRESENT_COOKIE = "autohostai.session.present"`. |
| Public config | `frontend/lib/config/public.ts`, `frontend/lib/config/server.ts` | New `appUrl: string` in `PublicRuntimeConfig`, vetted to `""` when off-shape; sourced from `NEXT_PUBLIC_APP_URL`. |
| Root page | `app/page.tsx` (new), `app/(workspace)/page.tsx` (deleted) | New root reads the presence cookie via `next/headers`'s `cookies()`, redirects on present, renders `<PublicShell><LandingView /></PublicShell>` otherwise. |
| Public shell | `frontend/features/shell/components/public-shell.tsx` | Add optional `marketingNav` prop, render in Topbar center slot; amend docstring. |
| Public shell test | `frontend/features/shell/components/public-shell.test.tsx` (new, alongside `shell-frame.test.tsx`) | Assert that with no `marketingNav` the chrome is unchanged; with it, the nav renders. |
| Landing feature | `frontend/features/landing/{index.ts,components/landing-view.tsx,components/hero.tsx,components/features-grid.tsx,components/feature-card.tsx,components/stats-band.tsx,components/final-cta.tsx,components/landing-footer.tsx,components/marketing-nav.tsx,lib/types.ts}` | New `features/landing/` with five section components, the root view, and the marketing nav. |
| Route registry | `frontend/features/shell/navigation/route-registry.ts` | New `landing` descriptor with `pattern: "/"`, `href: "/"` (so `MarketingNav`'s `Login` link and any breadcrumb machinery pick it up), `profile: "public"`, `match: "exact"`. |
| Metadata helper | `frontend/lib/metadata/create-route-metadata.ts`, `frontend/lib/metadata/create-route-metadata.test.ts` | New `createLandingMetadata()` exports the indexable block (title outside the template, OG, canonical when `appUrl` is set, `index: true`). New test asserts every existing route id still yields `index: false` and that `landing` yields `index: true`. |
| i18n namespaces | `frontend/locales/{es,en}/landing.json` (new), `frontend/lib/i18n/resources.ts` | New `landing` namespace, registered in both `NAMESPACES` and both `resources.{es,en}`. |
| i18n parity test | `frontend/test/i18n-parity.test.ts` (new, or augment the existing one if present) | Asserts `Object.keys(es.landing) === Object.keys(en.landing)` and that every value is a non-empty string. |
| `useEffect` for refresh-driven cookie updates | `frontend/lib/auth/refresh-coordinator.ts` | When a refresh succeeds, call `markSessionPresent()`; when it fails or `subscribeToSessionExpired` fires, call `clearSessionPresent()`. |
| Smooth-scroll CSS | `frontend/app/globals.css` | One rule: `html { scroll-behavior: smooth; }`. |
| `.env.example` | `.env.example` (root) | Add `NEXT_PUBLIC_APP_URL=` with a comment explaining the dev default is empty and prod sets the absolute URL. |
| Archive deliverables (deferred to `/sdd:archive`, listed here for traceability) | `sdd/specs/frontend-foundation.md`, `sdd/specs/local-environment.md`, `sdd/specs/frontend-auth-session.md`, `docs/landing.md` | (1) `frontend-foundation.md:19` — redirect becomes conditional on session. (2) `frontend-foundation.md:60` — append the named landing exception. (3) `frontend-foundation.md:96` — list the new files. (4) `local-environment.md:500` — add the new files to the file inventory. (5) `frontend-auth-session.md:39-42` — append the presence-cookie carve-out, copy-pasted from the proposal's text. (6) `docs/landing.md` — new capability page with the stats block's framing and the "what the landing does NOT promise" list (R5.3). |

## Data & interfaces

- **New env var**: `NEXT_PUBLIC_APP_URL` (non-sensitive, allowlisted in
  `public.ts`). Empty in dev. Set in prod.
- **New cookie**: `autohostai.session.present`, value `1`, `Path=/`,
  `SameSite=Lax`, **not** `HttpOnly` (server must read it), **not** `Secure`
  in dev so localhost works; the existing `autohostai.theme` and
  `autohostai.locale` cookies follow the same pattern and the change to
  introduce `Secure` is out of scope.
- **No backend changes.** R6.1 is explicit: no routes, no DTOs, no
  generated client methods. `backend/openapi.json` and
  `frontend/lib/api/generated/openapi.d.ts` are untouched.
- **No new HTTP clients.** `LandingView` is a Server Component that only
  resolves i18n on the server.
- **No new shell.** `PublicShell` extends by an optional prop only.

## Risks & mitigations

- **`noindex` is a one-way door.** The moment the landing is reachable by
  Google, it exists outside the repo: search engines cache it, third-party
  scrapers mirror it, social previews persist. Mitigation: the
  `createLandingMetadata()` helper is the only producer of `index: true`,
  the test that asserts every other route id yields `index: false` is
  blocking, and the merge PR has the proposal's "Riesgo: noindex" paragraph
  as a checklist item so the merge decision is conscious.
- **Server-side cookie check creates a 1-frame flash risk if the cookie is
  stale.** A user who logged out in another tab keeps the cookie until the
  next `clearSessionPresent()` call. Mitigation: `clearSessionPresent()`
  fires on `sessionExpired` and on the next `useEffect` of any client who
  triggers a logout; the landing's redirect uses a `307 Temporary
  Redirect`, not a `301`, so a stale cookie that races a logout
  self-corrects on the next request.
- **The presence cookie is a server-visible signal that some users had a
  session in this browser.** It is non-sensitive (no token, no user id, no
  PII) and lives only for the duration of the browser session, but it is
  still a behavioural marker. Mitigation: it is set and cleared
  synchronously with the JS session store, never persisted, and the
  amendment to `frontend-auth-session.md` at archive time spells out
  exactly what it is and is not — see **OQ-3** below.
- **`(workspace)/page.tsx` deletion must not regress `/dashboard` for
  authenticated users who type `/`.** Mitigation: the new `app/page.tsx`
  redirects to `/dashboard` with `307` whenever the cookie is present; that
  path was the only one the deleted page ever supported.
- **Marketing nav center slot collides with `LocaleSwitcher` on narrow
  viewports.** Resolution (Jose, 2026-08-24): below 768 px the nav renders
  only the `Login` button; the `#features` link hides. Zero extra JS, no
  client island, matches the mobile maqueta's reduced chrome. The
  `tap-target` utility (`design-system-tokens.md:45`) covers the touch
  target.
- **Spec amendments at archive time** can drift if the merged change
  differs from the design. Mitigation: the archive tasks list the exact
  line numbers from today's snapshot; if a later reviewer has merged
  intervening changes that shift those lines, archive flags the diff and
  resolves it manually.

## Open questions

- **OQ-1 — Stats block wording (decision, blocks `/sdd:tasks`).** The two
  lines that fill the stats band in `JetBrains Mono` are the only content
  input Jose owes this entry before `/sdd:tasks` can break them down.
  Proposal R5 leaves the choice open (operational numbers the system can
  back, or product statements without numbers); the maqueta's "500+ /
  99%" pair is rejected. Resolution lives in `BLOCKED.md`; `/sdd:tasks`
  will refuse to proceed until this is answered.
- **OQ-2 — Mobile marketing nav** — *resolved 2026-08-24 (Jose)*: hide
  the `#features` link below 768 px; render only the `Login` button.
- **OQ-3 — Cookie carve-out text in `frontend-auth-session.md`** —
  *resolved 2026-08-24 (Jose)*: the proposed sentence stands verbatim and
  is captured in D11.
- **OQ-4 — OG image** — *resolved 2026-08-24 (Jose)*: generate via
  `frontend/app/opengraph-image.tsx` using `next/og`'s `ImageResponse`,
  captured in D4.
