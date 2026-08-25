# BLOCKED — landing-public (post-review)

`/sdd:review landing-public` returned **FAIL** on 2026-08-25 with
findings A–D. After one fix round (4 commits), all four blocking
findings are closed and re-review is in progress. Findings E–F
remain deferred.

Lifecycle stays at `ACTIVE` until the re-review panel certifies the
fixes; `mark-local-verified` / `mark-ready` / `validate-ship` are NOT
run yet.

## Entries

- **phase**: review · **type**: deferred · **what & why**: E — latent
  hardening. `frontend/lib/auth/session-presence-cookie.ts` cookie
  writers accept arbitrary strings; not exploitable today (only caller
  passes constant `"1"`) but a future caller could inject cookie
  attributes. **resume**: tighten `writeCookie` / `clearCookie` to
  reject non-`"1"` values or hard-code the value internally (not a
  review blocker; can land any time).

- **phase**: review · **type**: deferred · **what & why**: F — minor.
  `frontend/app/opengraph-image.tsx` does not pin the Inter font the
  design D4 suggested; the rendered title uses the default sans. Benign
  at this size. **resume**: optional hardening; not a review blocker.

## Resolved this round

- **A** (README drift) — `frontend/README.md:21` now describes `/` as
  the public landing for anonymous visitors and the conditional
  redirect to `/dashboard` for authenticated browsers; the Variables
  de entorno section documents `NEXT_PUBLIC_APP_URL` with the
  dev-empty default. Commit `0bf7b8f`.

- **B** (theme whitelist gap) —
  `frontend/features/shell/components/public-shell.test.tsx` added
  to `MAY_NAME_THEME` in `frontend/test/theme-client-state.test.ts`
  with a justification mirroring the existing `topbar.tsx`
  exemption. Commit `9f2b82b`.

- **C** (missing footer / marketing-nav tests) — new
  `frontend/features/landing/components/landing-footer.test.tsx`
  asserts no `Pricing|Portfolio|Team|Sign Up` text renders and pins
  the empty-columns placeholder; new
  `frontend/features/landing/components/marketing-nav.test.tsx`
  asserts exactly two items (`/login` + `#features`), the
  mobile-hide utility on the anchor (OQ-2 resolved 2026-08-24), and
  the forbidden-text absence in both locales. Commit `8b1071e`.

- **D** (D4 per-descriptor enumeration) — `create-route-metadata.test.ts`
  adds two `it()`s in the existing `every other route id stays
  noindex (R2.2)` describe block: every non-landing descriptor is
  exercised through `createMetadataFromKeys` and asserts
  `robots: { index: false, follow: false }`; only `createLandingMetadata`
  yields `index: true`. Both shapes of Next's `Metadata.robots`
  (`Robots` and the string `"index, follow"`) are excluded for every
  non-landing descriptor. Commit `4a8ea6a`.