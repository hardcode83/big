# Tasks: landing-public

Change is purely frontend (no backend changes; R6.1). Tasks are grouped so the
system stays working after each section: plumbing (cookies/config/i18n/shell
extension) lands before any visible chrome, and the redirect from `/` flips
in the last section.

Requirements: R1 (root serves landing to anonymous, redirects authenticated
to `/dashboard`) · R2 (landing is the only indexable surface) · R3 (single
responsive design reusing `PublicShell`, marketing nav with `Login` +
`#features` only) · R4 (copy lives in `locales/{es,en}/landing.json`) · R5
(stats block uses two product statements in JetBrains Mono, no invented
numbers) · R6 (no API contract, no existing-screen, no public signup).

OQ-1 (stats copy) resolved 2026-08-24 by Jose: two product statements
without numbers; the block is static and lives entirely in the locale
catalogue. OQ-2/3/4 already resolved 2026-08-24.

Archive-time deliverables (proposal §R2.4, §R5.3, design §D11) are NOT tasks
of `/sdd:run` — they are edits to `sdd/specs/frontend-foundation.md`,
`sdd/specs/local-environment.md`, `sdd/specs/frontend-auth-session.md` and
the new `docs/landing.md` that `/sdd:archive` performs post-merge.

## 1. Session presence cookie (design D1) — foundation for R1

- [x] 1.1 Add `SESSION_PRESENT_COOKIE = "autohostai.session.present"` to
      `frontend/lib/config/constants.ts` next to `LOCALE_COOKIE`/`THEME_COOKIE`.
      Non-sensitive, mirrors their `Path=/` + `SameSite=Lax` posture. [R1]
- [x] 1.2 New `frontend/lib/auth/session-presence-cookie.ts` exporting
      `markSessionPresent()`, `clearSessionPresent()` and the cookie name
      constant re-exported from `constants.ts`. Implementation uses
      `document.cookie` with `path=/`, `samesite=lax`, no `expires` (browser
      session). Test in the same file (or alongside) covering the four
      transitions: set clears nothing else, clear actually removes the cookie,
      re-calling `mark` is idempotent, calling `clear` when unset is a no-op.
      [R1]
- [x] 1.3 Wire the cookie into `frontend/lib/auth/auth-provider.tsx` at every
      place that already touches `setSessionTokens`/`clearSessionTokens`:
      after successful `setSessionTokens` in `login`, call
      `markSessionPresent()`; in `logout`, in the
      `subscribeToSessionExpired` effect, and anywhere else that ends up
      calling `clearSessionTokens`, call `clearSessionPresent()`. The
      presence cookie tracks the JS session 1:1 — it is never persisted, and
      it carries no token, no user id and no PII. Test (extend
      `frontend/lib/auth/auth-provider.test.tsx` if present, otherwise a
      new file) asserts that login sets the cookie and logout clears it.
      [R1]
- [x] 1.4 Wire the cookie into
      `frontend/lib/auth/refresh-coordinator.ts`: on successful refresh call
      `markSessionPresent()`, on refresh failure (the `.catch` that calls
      `clearSessionTokens`) call `clearSessionPresent()`. Test asserts the
      same lifecycle pair. [R1]
- [x] 1.5 Verify the section leaves the rest of the app byte-equivalent:
      no public URL, no metadata change, no shell change. Run
      `cd frontend && npm run typecheck` and `cd frontend && npm test -- --run`
      (or whatever the local test invocation is — see project.md). [R1]

## 2. Public config: `NEXT_PUBLIC_APP_URL` allowlist (design D5)

- [x] 2.1 Add `appUrl: string` to `PublicRuntimeConfig` in
      `frontend/lib/config/public.ts`, sourced from
      `NEXT_PUBLIC_APP_URL` via `buildPublicRuntimeConfig()`. Empty when
      unset/off-shape, same posture as `apiBaseUrl`/`appVersion`. Extend
      `frontend/lib/config/public.test.ts` (or its current home) to assert
      empty-string fallback and that a valid absolute URL passes through.
      [R2]
- [x] 2.2 Add `NEXT_PUBLIC_APP_URL=` (empty) to `.env.example` with a
      comment explaining the dev default is empty and that prod sets the
      absolute URL. Per `steering/documentation.md`: name + comment, no
      value. [R2]

## 3. Indexable metadata exception, centralized by route name (design D4) — R2

- [x] 3.1 Extend `frontend/lib/metadata/create-route-metadata.ts` with a new
      `createLandingMetadata()` export that builds the indexable block: a
      title outside the `%s | AutoHostAI` template (the landing is its own
      page, no parent segment to inherit), localized description from the
      landing catalogue, Open Graph with specific title/description (not the
      generic registry one) and — when `appUrl` is non-empty — a static
      `metadataBase`, the OG `url`, and `alternates.canonical` to the
      absolute landing URL. The helper is the **only** path in the file
      that emits `robots: { index: true, follow: true }`; existing
      `createRootMetadata` and `createMetadataFromKeys` keep `index: false`
      unchanged. [R2.1, R2.3]
- [x] 3.2 Extend `frontend/lib/metadata/create-route-metadata.test.ts`
      (alongside the existing `createRootMetadata`/`createMetadataFromKeys`
      cases) with:
      (a) `createLandingMetadata` returns `robots: { index: true, follow: true }`
      and a title outside the `%s | AutoHostAI` template, localized per
      cookie;
      (b) every existing route id from `routeRegistry` (asserted via
      `routeRegistry.map(r => r.id)`) still yields `robots: { index: false,
      follow: false }` from `createRootMetadata` and
      `createMetadataFromKeys` — no future descriptor can flip a flag and
      become indexable by accident;
      (c) when `appUrl` is empty, `createLandingMetadata` omits
      `metadataBase`/`alternates.canonical`/OG `url` (existing test at
      lines 27-28 keeps passing); when non-empty, all three are set to the
      absolute URL.
      [R2.1, R2.2, R2.3]
- [x] 3.3 (Archive-time — recorded here for traceability, not run-time) The
      `SHALL` of `sdd/specs/frontend-foundation.md:60` is amended by
      `/sdd:archive` post-merge to read *"toda superficie es `noindex,
      nofollow` salvo la landing pública, que es la única indexable"*, with
      the exception named by route (the same form used by
      `createLandingMetadata`), not by a generic flag. [R2.4]

## 4. i18n namespace and locale catalogues (design D7) — R4

- [x] 4.1 Add `frontend/locales/es/landing.json` and
      `frontend/locales/en/landing.json` with the full key set the page
      needs: hero (eyebrow, title, subtitle), four features (each: title,
      body), stats (two lines), CTA final (title, button label, button
      href), footer (product columns, company columns, legal columns —
      empty arrays for the latter per R3.3 — copyright). Use the existing
      flat structure that other catalogues use; no nested arrays beyond
      what's already in `locales/es/{navigation,dashboard}.json`. Strings
      in both locales. Stats lines: two product statements, NO numbers,
      NO percentages (R5.1 + R5.2 + OQ-1 resolution). [R4.1, R5.1, R5.2]
- [x] 4.2 Register the namespace in `frontend/lib/i18n/resources.ts`:
      add the two `import` lines, add `"landing"` to `NAMESPACES` (the
      array stays `as const`), and add `landing: esLanding` /
      `landing: enLanding` to the `resources.es` and `resources.en`
      tables. The two existing `describe` blocks in
      `frontend/lib/i18n/catalog-parity.test.ts` (`namespace registration`
      and `catalog parity ES/EN (D13)`) cover the new namespace
      automatically — `landing` enters the loop the moment it is added to
      `NAMESPACES`. Run that file once to confirm. [R4.2, R4.3]
- [x] 4.3 No string of the landing page is hardcoded in any component. The
      verification at the end of this checklist greps the diff for
      `frontend/features/landing/` to prove it. [R4.1]

## 5. `PublicShell` gains the `marketingNav` slot (design D3) — R3

- [x] 5.1 Extend `frontend/features/shell/components/public-shell.tsx`:
      add optional `marketingNav?: ReactNode` to the props. Amend the
      docstring to declare the shell now serves `/`, `/login` and
      `/forgot-password`. Pass `marketingNav` into `Topbar` as the new
      `center` slot (between `start`/Brand and `end`/locale+theme
      switchers). Update `Topbar`'s signature in
      `frontend/features/shell/components/topbar.tsx` to accept an
      optional `center` prop; render it between the two existing flex
      containers. `Topbar` stays a Server Component. [R3.2]
- [x] 5.2 New `frontend/features/shell/components/public-shell.test.tsx`
      (alongside `shell-frame.test.tsx`) that asserts:
      (a) with no `marketingNav`, the chrome of the shell is
      byte-equivalent to today — `<header>` contains Brand on the left and
      the theme+locale switchers on the right, no center slot rendered;
      (b) with `marketingNav` provided, the supplied node is rendered
      between Brand and the switchers.
      This is the regression guard for `/login` and `/forgot-password`,
      whose chrome must not change. [R3.2]

## 6. Landing feature (design D6, D8, D9, D10) — R3, R4, R5

- [x] 6.1 New `frontend/features/landing/lib/types.ts` with the section
      prop shapes (FeatureCard's `titleKey`/`bodyKey`/`iconName`,
      StatsBand's two string keys, FinalCta's titleKey/buttonLabelKey/
      buttonHrefKey, LandingFooter's column shape with `links:
      readonly { labelKey: string; href: string }[]`). No business
      types; this file only describes the components. [R3]
- [x] 6.2 New `frontend/features/landing/components/marketing-nav.tsx` (a
      Server Component) that renders exactly two items: a `Login` link to
      `/login` and a `<a href="#features">` anchor (no smooth-scroll JS,
      see 6.8). Below 768 px the `#features` link is hidden via the
      `hidden md:inline-flex` utility (no client island); the `Login`
      link is always visible and uses the existing `tap-target` utility
      for the touch target. The labels come from the `landing` catalogue
      (`marketing.login` / `marketing.featuresAnchor`). [R3.3]
- [x] 6.3 New `frontend/features/landing/components/hero.tsx` (Server
      Component) that renders the eyebrow + title + subtitle from the
      `landing` catalogue (`hero.eyebrow`, `hero.title`, `hero.subtitle`)
      using the existing `text-display-*` and body tokens from
      `design-system-tokens`. No client JS. [R3]
- [x] 6.4 New `frontend/features/landing/components/feature-card.tsx` and
      `features-grid.tsx` (Server Components). The grid composes four
      cards in a 1-column mobile / 2-column tablet / 4-column desktop
      layout using existing layout utilities. Each card reads
      `features.reservations.{title,body}`, `features.cleaning.{title,body}`,
      `features.incidents.{title,body}`, `features.analytics.{title,body}`
      from the `landing` catalogue. Icons by name (lucide), kept
      serializable. [R3.1, R3]
- [x] 6.5 New `frontend/features/landing/components/stats-band.tsx`
      (Server Component) that renders two short lines from
      `landing:stats.line1` and `landing:stats.line2` with the
      `text-data-mono` token (JetBrains Mono). The block is a translucent
      card (Tailwind `bg-card/60 backdrop-blur`); NO numbers, NO
      percentages — the maqueta's "500+ Propiedades gestionadas" /
      "99% Satisfacción de propietarios" pair is **not** in the catalogue
      and SHALL NOT be added. Test (next to the component) renders the
      component with a stub translator and asserts the output text
      matches the locale catalogue exactly and contains no digit
      characters (`/\d/.test(text)` is `false`). [R5.1, R5.2]
- [x] 6.6 New `frontend/features/landing/components/final-cta.tsx`
      (Server Component) that renders the final title + button label
      (`landing:cta.title`, `landing:cta.buttonLabel`) and a link whose
      `href` resolves from `landing:cta.buttonHref` (currently
      `/login`). Button styled with the existing primary button utility.
      [R3]
- [x] 6.7 New `frontend/features/landing/components/landing-footer.tsx`
      (Server Component) that renders the three columns from the
      catalogue (`footer.product[]`, `footer.company[]`, `footer.legal[]`)
      and a copyright line (`footer.copyright`). All three arrays exist
      in both locales; `footer.legal` is `[]` in both per R3.3 (no
      Pricing/Portfolio/Team/Sign Up, no legal pages yet). Test renders
      the footer with stub data and asserts no link with text
      `Pricing|Portfolio|Team|Sign Up` appears. [R3.3]
- [x] 6.8 Add `html { scroll-behavior: smooth; }` to
      `frontend/app/globals.css` (one rule, scoped to the html element).
      This is the CSS half of D10; no `useEffect` smooth-scroll handler
      is added — the `<a href="#features">` in `marketing-nav.tsx` uses
      native anchor behaviour. [R3]
- [x] 6.9 New `frontend/features/landing/components/landing-view.tsx` (a
      Server Component) that composes Hero, FeaturesGrid, StatsBand,
      FinalCta, LandingFooter, with `<section id="features">` wrapping
      the FeaturesGrid so the `#features` anchor targets it. The page's
      `generateMetadata` calls `createLandingMetadata()`. [R3, R2]
- [x] 6.10 New `frontend/features/landing/index.ts` re-exporting the
      public surface (`LandingView`, `MarketingNav`, the section types).
      [R3]

## 7. Route registry entry for the landing (design D2, D4) — R2, R3

- [x] 7.1 Add a `landing` descriptor to `routeRegistry` in
      `frontend/features/shell/navigation/route-registry.ts` with
      `pattern: "/"`, `href: "/"`, `profile: "public"`,
      `match: "exact"`, an icon name (e.g. `"LayoutDashboard"` or a new
      neutral one — pick whatever the existing `NavigationIconName` union
      permits; if a new icon name is needed, add it to the union and the
      icon resolver). `titleKey` / `descriptionKey` /
      `metadataTitleKey` / `metadataDescriptionKey` resolve to the
      landing catalogue (e.g. `landing:title` /
      `landing:description`). The descriptor's i18n keys are exercised by
      the existing `catalog parity ES/EN (D13)` block in
      `catalog-parity.test.ts` (line 95-109). [R3, R2]

## 8. Open Graph image at build time (design D4) — R2

- [x] 8.1 New `frontend/app/opengraph-image.tsx` that uses `next/og`'s
      `ImageResponse` against the same emerald palette and Inter
      typography the design tokens publish (`app-version-visibility` for
      the font loading pattern: `await fetch(new URL("./inter-bold.woff2",
      import.meta.url))` or the equivalent pinned by that change). The
      rendered image is a single line of product text from the
      `landing` catalogue on the emerald background. No backend call, no
      external service. The asset is shipped as a static PNG by Next's
      `ImageResponse` machinery. [R2.1]

## 9. Root page takes the anonymous/authenticated decision on the server (design D2) — R1, R2, R3

- [x] 9.1 New `frontend/app/page.tsx` (Server Component): imports
      `cookies` from `next/headers`, reads
      `autohostai.session.present`, and either
      `redirect("/dashboard", 307)` (when the cookie is present and
      equals `"1"`) or renders
      `<PublicShell marketingNav={<MarketingNav />}><LandingView /></PublicShell>`.
      Exports a `generateMetadata` that calls `createLandingMetadata()`.
      `redirect` uses Next's `redirect` from `next/navigation` with the
      `307` status. The component is async because `PublicShell` and
      `LandingView` are async Server Components; matches the pattern
      already used in `(public)/login/page.tsx`. [R1.1, R1.2, R1.4, R2.1,
      R3.2]
- [x] 9.2 Delete `frontend/app/(workspace)/page.tsx` (the unconditional
      `redirect("/dashboard")`). The new `app/page.tsx` is the only file
      at `/`. Confirm no other file imports from this path; `git grep -n
      '(workspace)/page'` should return zero matches after the deletion.
      [R1.3]
- [x] 9.3 (Archive-time — recorded here for traceability, not run-time)
      `sdd/specs/frontend-foundation.md:19` is amended by `/sdd:archive`
      to describe `/` as a conditional redirect on session, not an
      unconditional one. [R1.3]

## 10. `.env.example` (design D5) — R2

> Documented here as a single task so the env-var change lives next to the
> task that introduces it (2.1). If 2.1 is approved and 10.1 is missed, the
> contract drifts; together they close the loop.

- [x] 10.1 Confirm `NEXT_PUBLIC_APP_URL=` is present in `.env.example`
      with the dev-empty comment, after 2.2 lands. No value, no quotes.
      [R2]

## 11. Verification — every requirement has a runnable check

> Run from the project root per `sdd/project.md` §Commands. From a
> worktree, the worktree bootstrap (same section) is required before the
> suite will run end-to-end — see "Worktree bootstrap" in project.md.

- [x] 11.1 `cd frontend && npm test -- --run` passes. Reference counts
      are measured, not remembered: the baseline before this change is
      whatever `npm test` gives on the parent commit; after the change
      it must be ≥ that count (no test removed). The
      `frontend-features-public-shell-test`, the
      `frontend-lib-auth-session-presence-cookie-test`, the
      `frontend-lib-metadata-create-route-metadata-test`,
      `frontend-lib-i18n-catalog-parity-test`, and the new
      `frontend-features-landing-*` files contribute at least one
      passing test each. [R1, R2, R3, R4, R5]
- [x] 11.2 `cd frontend && npm run typecheck` passes (the existing
      CI gate). [R1, R2, R3, R4, R5, R6]
- [x] 11.3 `cd frontend && npm run lint` passes if the repo has it
      configured (check `frontend/package.json` `scripts.lint`; skip
      with a note if absent). [R1, R2, R3, R4, R5, R6]
- [x] 11.4 `cd frontend && npm run api:check` (the CI contract gate
      for `frontend/lib/api/generated/openapi.d.ts`) passes. This change
      MUST NOT regenerate `backend/openapi.json` or
      `frontend/lib/api/generated/openapi.d.ts`: confirm with
      `git diff --stat main...HEAD -- backend/openapi.json
      frontend/lib/api/generated/openapi.d.ts` returning no lines.
      [R6.1]
- [x] 11.5 R6.2 (no existing screen touched) — `git diff --stat
      main...HEAD -- frontend/app/\(workspace\)/ frontend/app/\(public\)/
      frontend/features/{auth,cleaning,dashboard,incidents,pricing,
      properties,reservations,shell,provenance}/` shows no changed
      lines outside the new landing feature
      (`frontend/features/landing/`) and the shell component that is
      intentionally extended in 5.1. The two pre-existing screens that
      the shell change touches are `/login` and `/forgot-password` —
      their existing snapshot tests must remain green, confirming
      pixel-equivalence. [R6.2]
- [x] 11.6 R6.3 (no public signup) — `git grep -n 'sign.*up\|signup\|Sign
      Up\|signUp' frontend/features/landing/` returns no matches outside
      the catalogue (where the literal `Sign Up` does NOT appear, per
      R3.3). [R6.3]
- [x] 11.7 R4 (no hardcoded strings) — `git grep -n -E
      '"[A-Z][a-záéíóúñ]+ [a-záéíóúñ]+' frontend/features/landing/components/`
      returns only matches that resolve to imported constants or
      class-name strings; any prose literal triggers a fix. The test
      `frontend/test/i18n-parity.test.ts` (existing pattern) plus the
      catalog-parity loop in 4.2 are the structural guards; this grep is
      the manual confirmation. [R4.1, R4.2]
- [x] 11.8 R5.2 (no maqueta numbers) — `git grep -nE '500\+|99%|99
      ?%|Satisfacción' frontend/features/landing/ frontend/locales/`
      returns zero matches. [R5.2]
- [x] 11.9 Manual smoke check (R1, R3): with the stack up
      (`make up`), `curl -sI http://localhost:3000/` returns `200 OK`
      and HTML containing the hero title from the `landing`
      catalogue; `curl -sI http://localhost:3000/` after manually
      setting the cookie via DevTools returns `307` with
      `Location: /dashboard`. Then in the browser: viewport
      resized to 390 px and 1280 px, the `#features` link is hidden
      at 390 and visible at 1280 (R3.1 + R3.3). View Page Source shows
      `<meta name="robots" content="index, follow">` on `/` and
      `<meta name="robots" content="noindex, nofollow">` on every other
      surface (R2.1, R2.2).
      [R1.1, R1.2, R3.1, R3.3, R2.1, R2.2]
- [x] 11.10 Backend suite — `make up` once, then
      `docker compose exec backend uv run pytest`. This change does not
      touch the backend; the command exists to confirm the frontend
      build didn't break the contract (the OpenAPI artefact is checked
      against the backend in `api-contract` workflow and locally).
      [R6.1]
