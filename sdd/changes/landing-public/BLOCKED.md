# BLOCKED — landing-public (post-review)

`/sdd:review landing-public` returned **FAIL** on 2026-08-25.
Findings A–D require code/test changes before `/sdd:review` can re-run.
Findings E–F are noted but not blocking.

Lifecycle stays at `ACTIVE`. `mark-local-verified` / `mark-ready` /
`validate-ship` are NOT run.

## Entries

- **phase**: review · **type**: decision · **what & why**: A —
  README drift. `frontend/README.md:21` still describes `/` as
  unconditional `redirect /dashboard`, omits the new indexable landing
  surface, and omits `NEXT_PUBLIC_APP_URL`. Violates
  `sdd/steering/documentation.md:17`. **resume**: edit `frontend/README.md`
  (the "Local" / "Variables de entorno" sections) to describe the new
  `/` behaviour and the `NEXT_PUBLIC_APP_URL` var, then re-run
  `/sdd:review landing-public`.

- **phase**: review · **type**: decision · **what & why**: B — test
  suite exits red. `frontend/features/shell/components/public-shell.test.tsx`
  describes "theme+locale switchers" and trips
  `frontend/test/theme-client-state.test.ts:69-121`. **resume**: add the
  new test file to the `MAY_NAME_THEME` allowlist (same shape as the
  existing `topbar.tsx` exemption at line 88), then re-run
  `/sdd:review landing-public`.

- **phase**: review · **type**: decision · **what & why**: C —
  regression tests promised by task 6.7 / D8 are missing. No
  `landing-footer.test.tsx` asserting no `Pricing|Portfolio|Team|Sign Up`
  link; no `marketing-nav.test.tsx` pinning the two-item invariant.
  **resume**: add both files mirroring the catalogue stub-data pattern
  in `frontend/features/landing/components/stats-band.test.tsx`, then
  re-run `/sdd:review landing-public`.

- **phase**: review · **type**: decision · **what & why**: D — D4's
  load-bearing guard is weaker than the design promised.
  `frontend/lib/metadata/create-route-metadata.test.ts` does not iterate
  `routeRegistry.map(r => r.id)` and assert `robots.index === false` on
  every descriptor. **resume**: add an exhaustive descriptor walk to
  the existing `every other route id stays noindex (R2.2)` describe
  block, then re-run `/sdd:review landing-public`.

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