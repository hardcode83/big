# Tasks: visual-restyle-workspace

<!-- Rollout order follows design D10: Tier 1 primitives (section 1), shared
     chrome (section 2), then screens R1→R4→R2→R6 so each later section can
     reuse what the earlier one built. No section is marked hard: design.md's
     D1-D10 already fix every value/decision an implementer would otherwise
     have to invent (colours, alphas, class recipes), so this is transcription
     against a spec, not open-ended design. -->

## 1. Tier 1 — Card, Button glow, effect utilities, reservation tone map <!-- panel: PASS 2026-09-03 -->

- [x] 1.1 Create `components/ui/card.tsx`: a shadcn-shaped `Card`/`CardHeader`/
  `CardContent` (cva shape mirroring `components/ui/badge.tsx`), owning
  `bg-surface`, `border`, `rounded-xl`, `shadow-sm`, and consuming the
  `card-hover-gradient` utility from 1.3 on its wrapper (design D2). [R5]
- [x] 1.2 Add a `glow` boolean prop to `buttonVariants`
  (`components/ui/button.tsx:7-30`) that layers the `btn-glow` utility from 1.3
  onto the existing `default` variant only, applied via `<Button glow>` — not a
  new `variant` (design D3). Extend `components/ui/button.test.tsx` with a case
  that renders `<Button glow>` and asserts it keeps its accessible name/role
  (no regression), since `glow` must never touch `size.sm`'s dimensions (R5
  AC3). [R5]
- [x] 1.3 In `app/globals.css`, add three `@utility` blocks built from the
  already-declared `--color-primary` via `color-mix()`/alpha — never a new hex
  literal (design D4, values from `reservas_executive_emerald_style/code.html:212-223`,
  standardized per D4 over the dashboard mockup's inconsistent alphas):
  `btn-glow` (box-shadow at two alpha steps, rest/hover, + `hover:-translate-y-px`),
  `card-hover-gradient` (`::before` 1px top border,
  `linear-gradient(90deg, transparent, var(--color-primary), transparent)`,
  opacity 0→1 on hover), `text-glow` (`text-shadow` from `--color-primary`, for
  page `<h1>`s only — not applied globally). Do not port the mockup's
  `body::before` full-page ambient wash (rejected in D4). [R5]
- [x] 1.4 Run `npm test` and confirm `test/color-tokens.test.ts` still passes
  with 1.3's new utilities (they must stay inside `globals.css`'s `@utility`
  bodies, which the guard does not scan — it only scans class-name strings in
  `.ts/.tsx`, per design's Context section). [R5]
- [x] 1.5 Create `features/reservations/lib/reservation-status-tone.ts`: a
  frozen `Record<ReservationStatus, Tone>` reading `TONE_BADGE_CLASS` from
  `lib/ui/status-tone.ts`, following the exact shape of
  `features/pricing/lib/recommendation-status.ts` (frozen export, `tone()`
  helper with a fallback for a status added to the backend before the frontend
  contract is regenerated). `ReservationStatus` has 7 values (`PENDING`,
  `CONFIRMED`, `CANCELLED`, `CHECKED_IN_ESTIMATED`, `CHECKED_OUT_ESTIMATED`,
  `COMPLETED`, `NO_SHOW`); pick tones by the same PRD-independent reasoning
  `recommendation-status.ts` documents (this mapping is not a PRD §9.1
  operational-state colour, so mark the reasoning as `ASSUMPTION` per the
  project convention). [R2]

## 2. Shared chrome: state components, sidebar composition, i18n <!-- panel: PASS 2026-09-03 -->

- [x] 2.1 Restyle the `components/states/` family (`module-placeholder.tsx`,
  `empty-state.tsx`, `error-state.tsx`, `loading-state.tsx`, `state-panel.tsx`)
  onto the Tier-1 `Card` and the design tokens' typography roles. This one
  edit covers all 5 screens that render `ModulePlaceholder`
  (`statements`, `approvals`, `reviews`, `settings`, `settings/integrations`
  — design D6); run each of their existing tests
  (`module-placeholder.test.tsx`, `states.test.tsx`,
  `server-compatible.test.tsx`) immediately after. [R2]
- [x] 2.2 In `features/shell/components/sidebar.tsx`, add three compositional
  elements above/around the existing grouped `nav()` — navigation structure
  itself (the 12 destinations, 4 groups) stays byte-for-byte as
  `selectNavigationGroups()` renders it today (R2 AC1); nothing here changes
  `route-registry.ts` or adds a route:
  - A brand block at the top of the `<aside>` with a "Panel de Control" /
    "Control Panel" subtitle under the wordmark (new locale keys, see 2.3).
  - A visually emphasized primary CTA rendered above the grouped list: the
    existing `dashboard` destination's link, styled with `btn-glow`
    (`<Button glow asChild>`), as a second, promoted entry point to the same
    route — `dashboard` also stays exactly where it already is inside the
    `operation` group, so no destination is removed, merged or reordered.
  - A static, non-interactive help row (icon + label, `mt-auto` to anchor it
    at the bottom of the `<aside>`) — no `href`, no `onClick`, no new route:
    the roadmap decision that keeps this element (`sdd/roadmap/visual-restyle-workspace.md`,
    "Decisión 2") calls it "composición, no navegación", and the project has
    an explicit precedent against inventing a placeholder contact target
    (`sdd/changes/archive/2026-08-11-guest-portal-api/tasks.md`), so this is
    decorative only, never a dead-looking clickable element. [R2]
- [x] 2.3 Add the new UI strings from 2.2 (brand subtitle, help label) to both
  `locales/es/navigation.json` and `locales/en/navigation.json` — no
  hardcoded string in `sidebar.tsx`. [R2]
- [x] 2.4 Run `features/shell`'s existing tests for `sidebar`/`nav-link`/shell
  composition (if any) plus a manual check that the tablet drawer
  (`Sheet`/`SheetContent` path) still renders the same three additions. [R2]

## 3. R1 — Reservations screen (fidelity reference) <!-- panel: PASS 2026-09-03 -->

- [x] 3.1 In `features/reservations/components/list/reservations-view.tsx`,
  apply the D5 table recipe (wrapper
  `bg-surface-container-low border border-border rounded-xl overflow-hidden`,
  inner `overflow-x-auto`, `<thead>` row `border-b border-border`, `<th>`
  `py-md px-lg font-body-medium text-text-secondary whitespace-nowrap`,
  `<tbody className="font-data-mono">` with non-numeric cells (status, channel)
  opting back to `font-body-base`, row
  `hover:bg-surface-variant/50 transition-colors group cursor-pointer`) to the
  existing six columns (Guest, Property, Stay, Status, Channel, Amount) without
  adding, removing, or reordering any column. [R1]
- [x] 3.2 Wire the Status column to a `Badge` using 1.5's
  `reservation-status-tone.ts` map, replacing the current plain-text
  `{t(`status.${row.status}`)}` cell (`reservations-view.tsx:163`) — text
  content unchanged, only the visual treatment gains a colour-coded pill. [R2]
- [x] 3.3 Per design D8, add one static, always-visible affordance cue to the
  row's last cell (a `text-muted` chevron icon, not a new column) since the
  row currently has no persistent visible affordance beyond the
  `after:absolute after:inset-0` overlay `<Link>`. Verify by hand that the
  overlay link's click-through still lands on the row's target after adding
  the table-recipe classes and the chevron (this is the risk design.md calls
  out explicitly). [R5]
- [x] 3.4 Restyle `features/reservations/components/list/reservations-filters.tsx`
  as a glass panel (`bg-surface/60 backdrop-blur-md`, per the
  `stats-band.tsx` precedent) without adding, removing, or renaming any of the
  four controls (`Status`/`Check-in`/`Check-out`/`Clear filters`). [R1]
- [x] 3.5 Restyle the Previous/Next pagination controls and
  `features/shell/components/{shell-footer,version-badge}.tsx` (the build-
  provenance badge and its "Build provenance" link) onto the token/typography
  layer — functionally unchanged per R1 AC2. [R1]
- [x] 3.6 Run `features/reservations`' existing test files
  (`reservations-view.test.tsx`, `reservations-filters.test.tsx` if present)
  unmodified. If any assertion on exact class strings or DOM structure fails,
  stop per R7 AC2 and raise it rather than editing the test. [R7]

## 4. R3 — Properties screen <!-- panel: PASS 2026-09-03 -->

- [x] 4.1 In `features/properties/components/list/properties-view.tsx`, apply
  the D5 table recipe (3.1's recipe) to the existing six columns (Property,
  Code, City, Capacity, Status, Situation), the export's page-header
  typographic hierarchy, and its status-pill treatment — no new column, no
  photo, no occupancy %, no MTD revenue, no star rating, since
  `PropertySummaryDto` (`features/properties/data/dto.ts:41-56`) carries none
  of them (R3 AC2). [R3]
- [x] 4.2 Restyle the mobile row-card view (same file) with the export's
  "uppercase label + monospace value" data pattern for each field, reusing the
  same DTO fields as the table — no client-side placeholder for a missing
  field (R3 AC3). [R3]
- [x] 4.3 Restyle `features/properties/components/list/properties-filters.tsx`
  onto the token layer, controls unchanged. [R3]
- [x] 4.4 Run `features/properties`' existing test file(s) unmodified; stop
  per R7 AC2 if one needs editing. [R7]

## 5. R4 — Dashboard property cards <!-- panel: PASS 2026-09-03 -->

- [x] 5.1 Migrate `features/dashboard/components/property-card.tsx:80`'s
  ad-hoc `rounded-lg border bg-surface p-4 shadow-sm` div onto the Tier-1
  `Card` (1.1), adding `card-hover-gradient` (1.3) — the card's existing
  "open detail" `Link` (`property-card.tsx:176`) already satisfies D8's
  persistent-affordance rule as-is, so no extra chevron is needed here. [R4]
- [x] 5.2 Apply the token/typography layer to the card's existing fields
  (operational state, open incidents, next action with owner, reservation,
  guest, dates), preserving the exact PRD §9.1 tone mapping (amber for
  `Cleaning scheduled`, blue for `Cleaning in progress`, unchanged otherwise)
  — read from `lib/ui/status-tone.ts`, never restated locally (R2 AC3). Do
  **not** add the three KPI cards, the occupancy chart, the activity feed, or
  a search box (R4 AC2). [R4]
- [x] 5.3 Restyle `features/dashboard/components/dashboard-view.tsx`'s
  container/typography, leaving `BlockedTransitionsSection` (`features/dashboard/stalls/components/blocked-transitions-section.tsx`)
  as a preserved slot, restyled only if it renders visible chrome of its own. [R4]
- [x] 5.4 Run `features/dashboard`'s existing test files
  (`property-card` and `dashboard-view` tests) unmodified; stop per R7 AC2 if
  one needs editing. [R7]

## 6. R2 — Remaining workspace screens (timeline, incidents, cleaning, pricing, conversations) <!-- panel: PASS 2026-09-03 -->

- [x] 6.1 Restyle `features/dashboard/components/timeline/timeline-view.tsx`
  onto the token/typography layer (note: this view lives under
  `features/dashboard/components/timeline/`, not a `features/timeline/`
  directory — there is none). [R2]
- [x] 6.2 Apply the D5 table recipe to
  `features/incidents/components/list/incidents-view.tsx`, and restyle
  `features/incidents/components/detail/incident-detail-view.tsx` — the latter
  has **no styling today** (no `className` in the file), so this is a first
  composition pass, not a repaint; follow the `<dl>`-section block pattern
  established in section 7 for the guest portal rather than inventing new
  detail-page chrome (design D9's closing note). Severity colours continue to come from
  `features/incidents/lib/severity-tone.ts` (R2 AC3). [R2]
- [x] 6.3 Migrate `features/cleaning/components/cleaning-task-row.tsx:139`'s
  ad-hoc div onto `Card`, and restyle
  `features/cleaning/components/{cleaning-view,cleaning-filters,cleaning-pagination,assign-cleaner-control}.tsx`
  onto the token/typography layer. Cleaning-status colours continue to come
  from their existing tone module unchanged (R2 AC3). [R2]
- [x] 6.4 Migrate `features/pricing/components/{rule-row.tsx:69,recommendation-row.tsx:89}`'s
  ad-hoc divs onto `Card`, and restyle
  `features/pricing/components/{pricing-view,pricing-tabs,rules-panel,recommendations-panel,rule-filters,recommendation-filters,decision-controls,pricing-pagination}.tsx`
  onto the token/typography layer. Recommendation-status colours continue to
  come from `features/pricing/lib/recommendation-status.ts` unchanged (R2 AC3). [R2]
- [x] 6.5 Apply the D5 table recipe to
  `features/conversations/components/list/conversations-view.tsx`, and
  restyle `features/conversations/components/thread/conversation-thread-view.tsx`'s
  message list with `Card`-based message rows — same DOM shape, restyled
  surfaces only, no chat-bubble grouping or timestamp-reordering added (R7). [R2]
- [x] 6.6 Run every touched feature's existing test file
  (`incidents-view`, `incident-detail-view`, `conversations-view`,
  `conversation-thread-view`, plus the pricing/cleaning component tests
  already listed under `features/pricing`/`features/cleaning`) unmodified;
  stop per R7 AC2 if any needs editing. [R7]

## 7. R6 — Field shell and guest portal <!-- panel: PASS 2026-09-03 -->

- [x] 7.1 Restyle `features/cleaner/components/list/{cleaner-task-list-view,cleaner-task-list-row,cleaner-task-pagination,cleaner-task-status-chips}.tsx`
  and `features/tech/components/list/{tech-incidents-view,tech-incident-row,tech-status-chips}.tsx`:
  migrate the row components' ad-hoc divs onto `Card`, one card per
  task/incident, following the dashboard property-card pattern (design D9). [R6]
- [x] 7.2 Migrate `features/tech/components/detail/tech-incident-detail-view.tsx:107,118`'s
  existing `rounded-lg border bg-surface p-4` sections directly onto `Card` —
  no new pattern to invent, it already uses the card idiom (design D9). Apply
  the same token/typography pass to the rest of
  `features/tech/components/detail/*.tsx` (context block, cycle actions, ETA
  field, incident fields, photo gallery/upload, resolve form). [R6]
- [x] 7.3 Restyle `features/cleaner/components/detail/*.tsx` (task detail
  view, checklist, checklist item, photo requirements/gallery/upload button,
  incident report panel, completion panel, action bar, context block): the
  `<dl>`-shaped data (task detail) follows the properties-screen mobile-card
  pattern — "uppercase label + monospace value" per `<dt>/<dd>` pair (design
  D9) — and the remaining ad-hoc divs migrate onto `Card`. [R6]
- [x] 7.4 In `features/guest-portal/components/guest-portal-view.tsx`: restyle
  `StayInfoSection` (`:99`) with the same `<dl>` "uppercase label + monospace
  value" pattern as 7.3; restyle `CheckinSection` (`:193`) and
  `IncidentSection` (`:244`)'s `<form>`s with the same input/label styling as
  the restyled `reservations-filters.tsx` controls (3.4) — the one
  form-control pattern this change touches, reused rather than invented
  twice; restyle `ConversationSection` (`:297`)'s message list with
  `Card`-based message rows, same DOM shape as 6.5's conversation thread. [R6]
- [x] 7.5 Write down, in this section's Implementation Notes below, that no
  export mockup exists for `/cleaner`, `/tech`, or `/guest/[token]` and that
  their composition was derived per design D9 rather than improvised per
  screen (R6 AC2 requires this to be explicit — design.md already states it;
  this task is to confirm no deviation happened during implementation). [R6]
- [x] 7.6 Run every touched feature's existing test files (`cleaner`, `tech`,
  `guest-portal` component tests) unmodified; stop per R7 AC2 if any needs
  editing. [R7]

## 8. Verification

- [x] 8.1 Full frontend test suite passes: `cd frontend && npm test`
  (includes `test/color-tokens.test.ts` and `app/globals.contrast.test.ts` —
  the latter audits every declared background/text pair, including the new
  `reservation-status-tone.ts` badge pairs from section 1, per the risk
  design.md flags about the invented light-theme glow/glass values). [R5, R7]
- [x] 8.2 Layout/browser suite passes: `cd frontend && npm run test:layout`
  (the 360px topbar-overflow guard — sidebar composition in section 2 and the
  restyled topbar/footer in section 3 are the parts most likely to move
  layout width). [R2, R1]
- [x] 8.3 Lint and typecheck pass: `cd frontend && npm run lint` and
  `cd frontend && npm run typecheck`. [R7]
- [x] 8.4 Manual check of the end-to-end restyle, in both light and dark theme
  and at mobile/tablet/desktop widths (`make up PORT_OFFSET=<n>`, see
  `sdd/project.md`'s worktree-browser note): walk every one of the 12 sidebar
  destinations plus `/cleaner`, `/tech`, and `/guest/[token]`; confirm no
  interactive element is smaller than the 44×44 px `tap-target` utility (R5
  AC3); confirm the reservation row's overlay-link click-through still works
  (3.3's risk); confirm `prefers-reduced-motion: reduce` leaves every
  hover-only affordance still legible without the transition (R5 AC2, design
  D8). [R1, R2, R3, R4, R5, R6] — completed in a follow-up session once the
  host-wide Docker memory contention cleared (frontend container stopped
  crash-looping; confirmed stable with `docker stats`/`docker compose ps`
  before retrying, per the resume note this superseded). All 12 sidebar
  destinations verified with no console errors, including the four left over
  from the prior partial pass (pricing, statements, reviews, settings — all
  render their filters/tabs/`ModulePlaceholder` cleanly). Also verified: the
  360px mobile pass (no horizontal overflow, filter panels and dashboard
  cards restack cleanly, `Más` bottom-sheet opens); the dark-theme pass
  (settings, reservations, guest portal, dashboard all render correctly);
  the section-2 CTA's `tap-target` fix still holds at 44px measured live.
  Seeded the local demo tenant (`make demo-reset`, `DEMO_ACCOUNT_PASSWORD`
  set in the worktree's own `.env`) to get real content instead of empty
  states and real accounts for the three non-sidebar routes: `/cleaner` and
  `/tech` (including `/tech/incidents/[id]`) render correctly as `CLEANER`/
  `TECHNICIAN`, and `/guest/[token]` renders the real check-in flow with no
  console errors. This also upgraded 3.3's overlay-link risk from the prior
  session's static CSS analysis to a **live** verification: clicking the
  non-link area of a reservation row's Property cell (confirmed via
  `elementFromPoint`, which resolves to the overlay `<a>`) navigates to the
  correct `/reservations/[id]` detail page. `prefers-reduced-motion` remains
  verified via source only (design D8) — the Playwright MCP surface used
  this session has no `emulateMedia` equivalent exposed; nothing changed
  here since the prior session's source-based check. One pre-existing,
  out-of-scope defect noted for a future change, not fixed here per scope
  discipline: `features/tech/components/detail/tech-context-block.tsx:55`
  keys its address-line `<span>`s by `key={line}` — since a property's city
  and province can coincidentally be the same string (seed data: "Madrid" /
  "Madrid"), this throws a React duplicate-key console error on
  `/tech/incidents/[id]`. Confirmed via `git diff main` that this exact
  `.map()`/`key` line is untouched by this change (the diff to this file is
  restyling only), so it predates this restyle and is not this change's to
  fix.
- [x] 8.5 Confirm the change's definition of done from the roadmap and R7: no
  `features/*` behavioural test needed editing anywhere across sections 2-7 —
  if `git diff` shows an edited test file under `features/*/**/*.test.tsx`,
  treat that as a stop condition that was already raised in its section, not
  something to silently resolve here. [R7] — confirmed: the only two test
  files touched in the whole change are `components/ui/button.test.tsx`
  (Tier-1 primitive, not `features/*`, task 1.2's own explicit ask) and
  `features/shell/components/workspace-shell.test.tsx` (section 2's fix
  round — purely additive coverage for this change's own new sidebar
  elements, already raised and PASSed by the qa reviewer in section 2, not a
  silent workaround for a regression).

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

### Section 1

- `Card` (`components/ui/card.tsx`): props are `Card`, `CardHeader`, `CardContent` only — no `CardTitle`/`CardDescription`/`CardFooter`. `Card` always carries `card-hover-gradient` + `relative`; no opt-out prop exists. Base classes: `relative rounded-xl border bg-surface shadow-sm card-hover-gradient`. `CardHeader` = `flex flex-col gap-1.5 p-6`; `CardContent` = `p-6 pt-0`. No glassmorphism opacity (`bg-surface/60`) on `Card` itself — task 1.1 pins `bg-surface` verbatim; glass treatment is per-screen (filters panels, topbar) per D4, not baked into the primitive.
- `Button`: new `glow?: boolean` prop (default `false`), adds the `btn-glow` class when true. Not wired into `buttonVariants`'s variants map — applied via `cn()` alongside it. Never pass `glow` with `size="sm"`.
- `app/globals.css` utilities added: `btn-glow` (box-shadow `color-mix(in oklab, var(--color-primary) 20%/30%, transparent)` rest/hover + `translateY(-1px)` on hover), `card-hover-gradient` (`::before` 1px top gradient bar, opacity 0→1 on hover), `text-glow` (`text-shadow` at 35% alpha, apply to page `<h1>`s only — no component wires it yet, that's for a later section). All three reuse `--color-primary`; no new colour token declared, `DECLARED_TOKENS.size` stays 27.
- `reservation-status-tone.ts` (`features/reservations/lib/`): tones picked (`ASSUMPTION`, not PRD §9.1) — `PENDING`→amber (awaiting decision), `CONFIRMED`→blue (confirmed, upcoming), `CHECKED_IN_ESTIMATED`→green (active in-house), `CHECKED_OUT_ESTIMATED`→gray (transitional, not yet formally closed), `COMPLETED`→green (closed successfully), `CANCELLED`→red, `NO_SHOW`→red. Exports `RESERVATION_STATUS_TONE` (frozen) and `reservationStatusTone(status)` (fallback `"gray"`, `Object.hasOwn`-guarded). No `_ORDER` export — not asked for by task 1.5, unlike `recommendation-status.ts`.
- Gotcha: repo had no `node_modules`/`next-env.d.ts` checked out — ran `npm ci` and recreated the standard `next-env.d.ts` (gitignored) to get `test/color-tokens.test.ts`'s file-count assertion to match; not a code change, just environment provisioning.
- Added `features/reservations/lib/reservation-status-tone.test.ts` mirroring `recommendation-status.test.ts`'s shape (map coverage, palette-key check, fallback cases) even though task 1.5 doesn't name a test file explicitly — every sibling tone module has one.

### Section 2

- `components/states/state-panel.tsx`: root element swapped from a bare `<section>` to `Card` (`@/components/ui/card`) — `Card` forwards `role`/`aria-*`/`className` straight to its `div`, so `role="alert"` (`ErrorState`) and `role="status" aria-busy` (`LoadingState`) still land on the same element the tests query by role; nothing about the alert/status/no-alert/no-busy contract changed. Heading now `text-headline-md font-semibold text-foreground` (was `text-lg font-semibold`); description now `text-body-base text-muted-foreground` (was `text-sm`) — matches the pattern already used in `features/landing/components/feature-card.tsx`. `module-placeholder.tsx`'s `explanation` `<p>` gets the same `text-body-base` swap. `empty-state.tsx`/`error-state.tsx`/`loading-state.tsx` needed no direct edits — they only ever compose `StatePanel`, so the Card + typography change flows through automatically. This is the single edit that covers all 5 `ModulePlaceholder` screens (D6).
- `features/shell/components/sidebar.tsx`: three additions, each gated by a local `showLabels: boolean` param mirroring the existing `nav(onNavigate, showLabels)` convention (same boolean the `collapsed` rail already uses), so all three vanish on the collapsed desktop rail exactly like the nav group labels do, and all three render with labels inside the tablet `Sheet` (which never collapses):
  - Brand block (`brandBlock(showLabels)`): `<Brand label={t("common:appName")} />` (existing `features/shell/components/brand.tsx`, unmodified — cross-namespace `t("common:appName")` call from the `"navigation"` hook works because `I18nProvider` preloads all namespaces) plus a `<p className="text-xs text-muted-foreground">{t("brandSubtitle")}</p>` underneath, wrapped in `<div className="flex flex-col gap-0.5 px-3 pt-1">`. Returns `null` entirely when collapsed (not just the subtitle) — the wordmark text has no icon fallback and would overflow the 64px rail.
  - Promoted CTA (`dashboardCta(showLabels, onNavigate?)`): reads `getRouteById("dashboard")` from `route-registry.ts` (already imported for `ShellProfile`) and its icon via the existing `navigationIcons` map (`./icon-map`) — same icon/label/href `NavLink` uses for the grouped `dashboard` entry, so both links share one accessible name ("Panel"/"Dashboard"). Markup: `<Button glow asChild className="w-full justify-start gap-3"><Link href={route.href}>...</Link></Button>`; `asChild` + Radix `Slot` composes cleanly with `next/link`'s `Link` (confirmed by running the actual tests, not just reading the source). Collapsed state hides the label via `sr-only` span exactly like `NavLink` does (`aria-label` on the `<Link>` picks up the slack) — never changes `size`, so the "never `glow` with `size=\"sm\"`" rule doesn't apply here (default size only).
  - Help row (`helpRow(showLabels)`): plain `<div className="mt-auto flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground">` with a `CircleHelp` icon (`lucide-react`, `aria-hidden`) + label span (`sr-only` when collapsed). No `href`, `role="button"`, `onClick`, `tabIndex`, or hover/cursor styling — deliberately inert so it doesn't read as a broken link. `mt-auto` reliably pins it to the bottom because the `<aside>`/`SheetContent` ancestor chain is `flex flex-col` all the way up to the `min-h-dvh flex-col` shell root, so the row's flex item stretches to full column height.
  - Render order in the desktop `<aside>`: brand block → existing collapse-toggle `Button` (position unchanged) → CTA → `nav()` → help row. In the tablet `Sheet`: `SheetTitle` (unchanged, screen-reader dialog name) → brand block → CTA → `nav()` → help row — the `Sheet` has no collapse toggle, so that's the only structural difference from the `<aside>`.
- Locale keys added (`locales/{es,en}/navigation.json`, top-level, next to `collapseSidebar`): `brandSubtitle` (es: "Panel de Control", en: "Control Panel"), `help` (es: "Ayuda", en: "Help"). Verified against `lib/i18n/catalog-parity.test.ts` (19/19 pass) — both locales stay key-parallel.
- Gotcha for the next implementer: `OverlayAutoCloser` (`features/shell/components/overlay-auto-closer.tsx`) calls `closeOverlays()` in a `useEffect` keyed on `pathname` that fires on first mount too — so pre-seeding `useShellUiStore`'s `tabletNavOpen: true` before render (e.g. in a test) gets silently closed immediately after mount. To exercise the `Sheet` path, open it the way a real user does: render, then `fireEvent.click(screen.getByRole("button", { name: t("openMenu") }))`, then `await screen.findByRole("dialog")`.
- Fix round (qa panel FAIL, R2 AC2/task 2.4): task 2.4's tablet-drawer check was originally a throwaway test file, run once then deleted — not committed, so nothing asserted the three additions existed or reproduced the manual check. Fixed by adding two committed tests to `features/shell/components/workspace-shell.test.tsx` (describe block "Sidebar compositional additions (visual-restyle-workspace R2 AC2)"): one asserts the desktop `<aside>` contains the brand subtitle text, a `Panel`-named link carrying the `btn-glow` class pointing at `/dashboard` (the promoted CTA), and a non-interactive "Ayuda" help row (no matching link/button role); the other opens the tablet `Sheet` via the real `openMenu` trigger (`fireEvent.click` + `await screen.findByRole("dialog")`, same pattern as the `OverlayAutoCloser` gotcha above) and asserts the identical three elements inside the rendered `SheetContent`. `workspace-shell.test.tsx` is now 13/13; `features/shell` scope is 144/144 (was 142).
- Verified: `module-placeholder.test.tsx` + `states.test.tsx` + `server-compatible.test.tsx` = 15/15 pass; `workspace-shell.test.tsx` = 11/11 pass (covers `Sidebar` — there is no standalone `sidebar.test.tsx`/`nav-link.test.tsx`); `lib/i18n/catalog-parity.test.ts` = 19/19 pass; `tsc --noEmit` shows only 3 pre-existing unrelated errors (`welcome/page.tsx`, `auth-guard.tsx`, `login-form.tsx` — all `searchParams`/`pathname` possibly-null, none touched by this section); `eslint` clean on all edited `.tsx` files.

### Section 3

- **D5's literal recipe string does not compile as-is — translated to the tokens `globals.css` actually declares, per D5's own parenthetical ("translated to declared tokens").** The mockup's own Tailwind v3 config (`reservas_executive_emerald_style/code.html:355-381`) defines `py-md`/`px-lg`/`font-body-medium`/`font-data-mono`/`font-body-base`/`text-text-secondary`/`bg-surface-container-low`/`surface-variant` as ITS OWN utilities — none of these exist in this project's `@theme` blocks (verified: `globals.css` only declares `--text-{display-2xl,display-xl,display-lg-mobile,headline-lg,headline-md,body-lg,body-medium,body-base,data-mono,label-caps}`, which Tailwind v4 compiles to `text-*` utilities, not `font-*` — confirmed against the two live consumers, `stats-band.tsx`'s `text-data-mono` and `feature-card.tsx`'s `text-body-base`). `py-md`/`px-lg` are worse than inert: the ritmo correction in section 1/`globals.css:241-268` explicitly did NOT declare named spacing steps (`--spacing-md`/`--spacing-lg`) after they broke `max-w-md`, so those classes silently resolve to nothing. **Mapping applied everywhere the recipe is used (this file is the D5 reference — sections 4/6 copy this table, not the mockup's raw string):**
  - `py-md px-lg` → `py-3 px-4` (12px/16px, the numeric-scale equivalents `globals.css:254-259`'s own comment gives for `md`/`lg`).
  - `font-body-medium` / `font-body-base` → `text-body-medium` / `text-body-base` (the real generated utility name for a `--text-*` theme key).
  - `font-data-mono` (tbody) → `font-mono text-data-mono` together: `text-data-mono` alone only sets size/leading/tracking/weight, not the font family — `font-mono` (Tailwind's family utility, resolving `--font-mono` → the self-hosted JetBrains Mono) is what actually switches the typeface (confirmed by `version-badge.tsx`'s pre-existing `font-mono` usage; `stats-band.tsx` omits it and is arguably under-restyled, but that file is out of this section's scope).
  - `text-text-secondary` → `text-muted-foreground` (the only declared "secondary text" token; no `--color-text-secondary` exists).
  - `bg-surface-container-low` (wrapper) → `bg-surface` (the one declared "card surface" token, same one `Card` uses).
  - `hover:bg-surface-variant/50` (row) → `hover:bg-accent/50` (`bg-accent` is the established interactive-hover surface across the codebase: `button.tsx` ghost/outline variants, `nav-link.tsx`, `notification-row.tsx`, `marketing-nav.tsx` all use it).
  - Border colour: task 3.1's own text already substitutes `border-border` for the mockup's `border-surface-container-high` — kept as given.
  - Row separators moved from per-`<td>` `border-b` to per-`<tr>` `border-b border-border` (plus `last:border-b-0` so the last row doesn't double up with the wrapper's own bottom edge) — matches the mockup's actual DOM shape (`code.html:370`, border lives on `<tr>`, not `<td>`) and is what the "row" bullet of the recipe describes.
- **Status column (3.2):** `<Badge variant="outline" className={cn(TONE_BADGE_CLASS[reservationStatusTone(row.status)])}>{t(`status.${row.status}`)}</Badge>`, same call shape as `features/pricing/components/recommendation-row.tsx`'s existing `TONE_BADGE_CLASS` consumer — text content (`t(`status.${row.status}`)`) untouched, satisfying R2 AC3 (colour sourced from `lib/ui/status-tone.ts` via `reservation-status-tone.ts`, nothing restated locally) and the "text unchanged" half of the task. The status `<td>` and the channel `<td>` both get `font-sans text-body-base` to opt back out of the tbody's ambient `font-mono` (Badge itself sets no font-family, so without this override it would inherit the tbody's mono face).
- **Chevron (3.3):** `lucide-react`'s `ChevronRight`, `size-4 shrink-0 text-muted-foreground` (not `text-muted` — that class would resolve to `color: var(--color-muted)`, the *surface* token, not the text one; `text-muted-foreground` is the established secondary-text colour used identically in `breadcrumbs.tsx`'s own `ChevronRight`), `aria-hidden="true"`, in a `flex items-center justify-between` wrapper alongside the amount value inside the existing last `<td>` — no new column, no accessible name added (purely decorative, per D8).
- **Overlay-link click-through verification (3.3's named risk):** traced the CSS containing-block chain rather than eyeballing a screenshot, since the mechanism is fully static: the `<a className="... after:absolute after:inset-0 ...">` itself has no `position` utility (stays `static`), so its `::after` positions against the nearest positioned ancestor — walking up, that's still the `<tr className="relative ...">` (unchanged: `relative` was on the `<tr>` before this section and stays there; every class this section added to the `<tr>`/`<td>` — `border-b`, `hover:bg-accent/50`, `transition-colors`, `group`, `cursor-pointer`, `py-3 px-4` — is non-positioning). Since the overlay's containing block is the row, not a fixed-size cell, the larger `py-3 px-4` padding and the new chevron automatically fall inside the same full-row hit area rather than requiring a resize. Ran `reservations-view.test.tsx`'s existing link/href assertions (still 13/13 green) as the executable half of this check; the geometric reasoning above is the "by hand" half, since jsdom does not lay out pseudo-elements.
- **Filters glass panel (3.4):** wrapper div gains `rounded-lg border border-border bg-surface/60 p-3 backdrop-blur-md` (D4's card-glass recipe, same shape as `stats-band.tsx`'s `rounded-lg border border-border bg-surface/60 px-6 py-8 backdrop-blur` — `backdrop-blur-md` used here per this task's explicit instruction rather than `stats-band`'s plain `backdrop-blur`, since D4's own text specifies `-md` for cards). The four controls (`aria-label`, `htmlFor`/`id` pairs, `onChange` wiring) are byte-for-byte unchanged — only the wrapper `<div>`'s `className` and the `Clear filters` `<button>`'s `className` were touched.
- **Tap targets (R5 AC3, cited in-scope for this section):** added `tap-target` to the three raw `<button>`s this section touches — Previous, Next (3.5), and Clear filters (3.4) — since at `px-3 py-1 text-sm` none would clear 44px height on their own. Did not add it to the `<select>`/`<input type=date>` controls (3.4) or touch their sizing at all — task 3.4 scopes the filter-bar change to the wrapper only ("without adding, removing, or renaming any of the four controls"), and native form controls aren't the established `tap-target` precedent in this codebase (`tap-target` is used on `<summary>`/link-shaped triggers elsewhere, e.g. `pricing/recommendation-row.tsx`).
- **Pagination (3.5):** kept raw `<button>` elements rather than swapping to the Tier-1 `Button` component — task 3.5 says "restyle onto the token/typography layer", not "adopt `Button`", and a structural swap here is exactly the kind of scope creep R7's risk section warns about. Classes: `tap-target rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50` — `hover:bg-accent hover:text-accent-foreground` mirrors `Button`'s own `outline`/`ghost` variant hover treatment for visual consistency without importing the component.
- **`shell-footer.tsx`:** `border-t` → `border-t border-border bg-surface/80 backdrop-blur-md` (D4's "sticky topbar" glass alpha/blur step, since the footer is the same kind of persistent chrome). No test asserts this file's classes (`shell-frame.test.tsx`/`workspace-shell.test.tsx`/`public-shell.test.tsx` only check `querySelector("footer")` presence/position, not `className`).
- **`version-badge.tsx`:** `text-[0.6875rem] font-normal` (an arbitrary literal) → `text-data-mono` (the declared 13px/500-weight "data" role, paired with the pre-existing `font-mono`) — same reasoning as the tbody's mono treatment above: a version string is exactly the "data" typographic role's use case. `formatBuildVersion` and all DOM/testid/aria-label wiring untouched — `version-badge.test.tsx` (12/12) confirms no functional drift.
- **`features/provenance/provenance-panel.tsx` was also touched**, though not literally named in task 3.5's file list — R1 AC2 explicitly requires the "Build provenance" link and its panel restyled, and that link/panel only exists in this file (rendered inside `ShellFooter`). Changes: trigger button gains `tap-target inline-flex items-center` (R5 AC3 — a bare `text-xs` inline string has near-zero hit height) and `hover:text-foreground`; popover panel `rounded-md border bg-background` → `rounded-lg border border-border bg-surface/95 backdrop-blur-md` (near-opaque glass — a popover overlaying page content needs higher opacity than a page-level panel for text legibility) with `shadow-sm` (was `shadow-md`, aligning with the rest of this change's shadow scale); title `font-medium` → `text-body-medium text-foreground`; the four provenance links gain `text-primary underline underline-offset-4` (was unstyled `underline`, no colour). All `data-testid`/role/text content unchanged — `provenance-panel.test.tsx` (2/2) unaffected.
- **Gotcha for sections 4/6 (properties-view, incidents-view, conversations-view all copy this recipe):** don't paste D5's class string literally — copy the *mapping table* above instead. The literal string in `design.md`/`tasks.md` 3.1 and 4.1/6.2/6.5's cross-references is the mockup's own Tailwind config, not this project's; four of its six class fragments (`py-md`, `px-lg`, `font-body-medium`, `font-data-mono`, `font-body-base`, `text-text-secondary`, `bg-surface-container-low`, `hover:bg-surface-variant/50`) don't exist here and would either no-op (spacing, most `font-*` names collapse to nothing since Tailwind doesn't generate arbitrary undeclared utilities) or, worse, silently compile as literal Tailwind color/scale guesses.
- **Verified:** `reservations-view.test.tsx` 13/13, `reservations-filters.test.tsx` 5/5 (both unmodified — no `features/*` test needed editing, R7 AC1 holds), `version-badge.test.tsx` 12/12, `provenance-panel.test.tsx` 2/2, `shell-frame.test.tsx`, `workspace-shell.test.tsx`, `public-shell.test.tsx` all green (59/59 across the 7 files run together); `test/color-tokens.test.ts` + `test/color-tokens.patterns.test.ts` + `test/eslint-boundaries.test.ts` + `app/globals.contrast.test.ts` = 120/120 (no new colour literal introduced); full `features/reservations features/shell features/provenance` run = 215/215 passing (one unrelated suite, `topbar-overflow.browser.test.tsx`, fails to import in this sandbox for lack of a real browser runner — pre-existing infra gap, not a file this section touched, not a class/DOM assertion failure); `eslint` clean and `tsc --noEmit` shows only the same 3 pre-existing unrelated errors section 2 already noted (`welcome/page.tsx`, `auth-guard.tsx`, `login-form.tsx`) on every file this section edited.

### Section 4

- **Used the translated mapping table from section 3's notes above, not design.md's literal D5 string** — confirmed the same `py-md`/`px-lg`/`font-body-medium`/`font-data-mono`/`font-body-base`/`text-text-secondary`/`bg-surface-container-low`/`hover:bg-surface-variant/50` fragments don't exist in this project and would no-op or misresolve. Applied the mapping verbatim: wrapper `bg-surface border border-border rounded-xl overflow-hidden` + inner `overflow-x-auto`; `<thead>` row `border-b border-border`; `<th>` `py-3 px-4 text-body-medium text-muted-foreground whitespace-nowrap`; `<tbody className="font-mono text-data-mono">` with the two badge cells (`operationalState`, `status`) opting back to `font-sans text-body-base` (same opt-out reasoning as reservations' Status/Channel cells — Badge sets no font-family of its own, so without the override it would inherit the tbody's mono face); row separators on `<tr className="border-b border-border last:border-b-0">`. Unlike reservations, the properties row has no full-row overlay `<Link>` (only the Property-name cell is a link), so the row only gets `hover:bg-accent/50 transition-colors` — no `cursor-pointer`/`group`, since there's nothing group-hover-driven and the row itself isn't clickable.
- **Page-header typographic hierarchy:** the actual export mockup for properties (`docs/design/2026-08-23-stitch-export/propiedades_executive_emerald_style/code.html`) is the photo-grid layout R3 AC2 explicitly forbids — its only page-title markup is `font-headline-md text-headline-md font-bold text-primary` inside its own sticky topbar (out of scope; this project's shell topbar already exists separately). `properties-view.tsx` had zero page-title markup before this section (design D7 names this explicitly: "or none at all like properties'"). Task 4.1 names the typographic hierarchy as in-scope, so added `<h1 className="text-headline-md font-semibold text-foreground">{tNav("routes.properties.title")}</h1>` above the filters — sourced from the existing `navigation` i18n namespace (already used by breadcrumbs for this same key, no new locale string), and `font-semibold` (not the mockup's `font-bold`) to match the two live `text-headline-md` consumers already in the tree (`state-panel.tsx`, `feature-card.tsx`) rather than the mockup's literal weight, following the same "translate, don't paste" rule as D5. `font-headline-md` (the mockup's class) doesn't exist as a Tailwind utility here either — only `text-headline-md` (sets size/leading/tracking/weight via the `--text-headline-md` theme var).
- **"Uppercase label + monospace value" mobile-card pattern (4.2) — no existing precedent in the tree for this exact pair**, per the grep the brief pointed at (`uppercase.*font-mono` and a manual `uppercase` grep over `features/`): only three unrelated `uppercase` hits exist (`hero.tsx`'s `text-label-caps uppercase text-primary`, `locale-switcher.tsx`, `sidebar.tsx`'s nav-group labels), none paired with a mono value. Invented the shape from declared tokens: `<dt className="text-label-caps uppercase text-muted-foreground">` (the `--text-label-caps` token exists precisely for this "uppercase label" role and already encodes the 0.06em letter-spacing, so no extra `tracking-wide`; colour follows the same `text-text-secondary` → `text-muted-foreground` mapping as D5) and, for the three plain-text fields only (`internalCode`, `city`, `capacity`), the value wrapped in `<span className="font-mono text-data-mono">`. The two badge fields (`operationalState`, `status`) are NOT wrapped in mono — same reasoning as the table's badge-cell opt-out, `Badge` should render in its own default weight/face, not inherit a forced mono. `dd`'s own class dropped `font-medium` (redundant now that the mono span or the Badge itself carries its own weight).
- **`properties-filters.tsx` (4.3):** only the outer wrapper `<div>`'s className changed, to `flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface/60 p-3 backdrop-blur-md` (D4's glass-panel recipe, same shape as `reservations-filters.tsx`'s wrapper and `stats-band.tsx`'s precedent). The two `<select>` controls, their `id`/`htmlFor`/`aria-label` wiring, and `onChange` handlers are byte-for-byte unchanged — both already carried `tap-target` before this change, so R5 AC3 was already satisfied here and needed no new work. Did not add a container `aria-label` (reservations' wrapper has one, but task 4.3 says "controls unchanged" and properties-filters had none before — adding one would be a new attribute beyond a pure class restyle).
- **Deliberately left untouched:** pagination bar and its two `<button>`s (no task in this section names them; they already carry `tap-target` from a prior state) and the `NameLink`'s own classes (`font-medium text-primary underline-offset-4 hover:underline` — unchanged, inherits the tbody's ambient `font-mono` exactly like reservations' guest-id link does).
- **R3 AC2/AC3 held:** no photo, occupancy %, MTD revenue, or star rating added anywhere; every field rendered in both layouts still traces to a `PropertySummaryDto` key.
- **Verified:** `npx vitest run features/properties` = 7 files / 73 tests, all green, none of the 7 test files edited (R7 AC1/AC2 hold). `test/color-tokens.test.ts` + `test/color-tokens.patterns.test.ts` + `test/eslint-boundaries.test.ts` + `app/globals.contrast.test.ts` = 120/120 (no new colour literal). `eslint` clean on both edited files. `tsc --noEmit` shows only the same 3 pre-existing unrelated errors sections 2/3 already noted (`welcome/page.tsx`, `auth-guard.tsx`, `login-form.tsx`), none in files this section touched.

### Section 5

- **`property-card.tsx` (5.1):** the ad-hoc `<article className="... rounded-lg border bg-surface p-4 shadow-sm">` became `<Card role="article" aria-labelledby={headingId} className="flex h-full min-w-0 flex-col gap-4 p-4">` — `role="article"` because `Card` forwards `role`/`aria-*` straight to its root `div` (same pattern as `state-panel.tsx`, section 2), and `property-card.test.tsx` queries `getByRole("article")` plus asserts `classList.contains("h-full")` on it, so the accessible role and the `h-full` class both had to survive the element swap. Kept a flat `p-4` override rather than `CardHeader`/`CardContent` — the card's header and body already share one padding rhythm with no `p-6`-style split, and introducing `CardHeader`/`CardContent` would have doubled the padding without a design reason to. `rounded-lg` was dropped (was never really intentional — `Card`'s own `rounded-xl` wins) and `border bg-surface shadow-sm` were dropped entirely since `Card` already supplies them (plus `card-hover-gradient`, which came along for free, satisfying the task's explicit ask with zero extra code — matches the note already left in `tasks.md`).
- **Dashboard export mockup exists** (`docs/design/2026-08-23-stitch-export/dashboard_autohostai_emerald_style/code.html`, not linked from `design.md`'s R4 row but present on disk) and its "Operation Card" is the literal source for design.md's "stat-box pattern": `bg-[#181b25] border border-[#262a34] rounded-xl p-lg card-hover-gradient` (→ `Card` verbatim), a header separated by `border-b …/50 pb-md`, a 2-col grid of small `bg-surface/50 p-3 rounded-lg border` boxes (Incidencias Abiertas / Próxima acción, the second with a left accent), then a `space-y-2 text-sm` label/value list (Reserva/Huésped/Fechas) — this is structurally what `property-card.tsx` already had, so 5.2 mapped classes onto the existing structure rather than rebuilding it. The mockup's own two example badges are literally "Cleaning scheduled" (amber, `bg-state-warning/20 text-state-warning border-state-warning/30`) and "Cleaning in progress" (blue, `bg-state-info/20 …`) — confirms PRD §9.1's amber/blue pair at the source.
- **Tone mapping (R2 AC3, 5.2):** confirmed unchanged and un-restated. `PropertyStateBadge` (`components/property-state-badge.tsx`) already reads `TONE_BADGE_CLASS` from `lib/ui/status-tone.ts` and maps `CLEANING_SCHEDULED`→amber, `CLEANING_IN_PROGRESS`→blue via its own frozen `STATE_COLOR_GROUP` table (design D2) — this section touched neither file, only confirmed by reading them that no local restatement exists anywhere in `property-card.tsx`.
- **Typography (5.2):** `text-sm`/`text-base`/`text-xs`/`font-medium`/`font-semibold` swapped for the design-token roles established in sections 3-4: `Field`'s value span `font-medium` → `text-body-medium text-foreground`; its wrapper `text-sm` → `text-body-base`; the card title `text-base font-semibold` → `text-body-lg font-semibold`; every section-caption `h4` (`Incidencias abiertas`, `Próxima acción`, `Último evento`) went from `text-sm font-semibold text-foreground` to `text-body-base text-muted-foreground` — matching the mockup's small-muted-caption treatment rather than a bold heading, purely visual (the `id`/`aria-labelledby` wiring is untouched, so the accessible name of each region is identical). The open-incidents count got `font-mono` (family-only utility, section 3's established pattern) alongside its existing `text-lg font-semibold`→`font-bold` size, since the mockup renders stat numbers in the mono face at a size no single declared `--text-data-mono` role covers (that token is pinned at 13px for the *data-cell* role, not a headline-sized stat).
- **Stat-box classes (5.2):** open-incidents and next-action boxes both went from `rounded-md border bg-muted p-3` / `rounded-md border border-primary p-3` to `rounded-lg border border-border bg-surface/50 p-3` / `rounded-lg border border-primary bg-surface/50 p-3` — `bg-surface/50` is the mockup's own stat-box fill.
- **Gotcha for sections 6-7 (this bit cost a guard failure, worth flagging loudly):** the mockup's next-action box uses a **left-only accent border** (`border-l-2 border-l-primary`/`border-l-state-info`, depending on state). Tried `border border-border border-l-2 border-l-primary` here and `test/color-tokens.test.ts`'s D13 check (`names only colour tokens globals.css actually declares`) failed on `border-l-primary` — its `NON_COLOR.border` whitelist only recognises a side letter followed by digits (`[xytrblse](-\d+)?`) as a non-colour meaning of `border-{x}`, so `border-l-<token>` (a legitimate Tailwind directional-border-*color* utility) has no entry and reads as prefix `border` naming an undeclared token `l-primary`. **Do not use `border-{side}-{colorToken}` anywhere in this tree until that guard is amended** — sections 6/7 must reach for a plain `border-{colorToken}` (uniform box border) or a different mechanism (e.g. a `before:`/`after:` accent bar, like `card-hover-gradient` itself does) instead. Resolved here by reverting to the original code's own `border-primary` (uniform, not left-only) — same visual family, zero new risk, `test/color-tokens.test.ts` back to 120/120.
- **`dashboard-view.tsx` (5.3):** added a page `<h1>` reusing the *existing* `navigation` namespace's `routes.dashboard.title` key (already used by the shell breadcrumbs for this same route) — no new locale string, honouring the steering rule "no new UI copy expected in this section." Matches the `properties-view.tsx` precedent (section 4) exactly: container `<div className="flex flex-col gap-4 p-4">` wrapping `<h1 className="text-headline-md font-semibold text-foreground">` + a `body()` closure that switches on the query states. Restructured the four early `return`s (loading/error/empty/success) into that `body()` closure specifically so the title stays visible across every state, not just success — properties-view does the same. `dashboard-view.test.tsx`'s grid assertions (`cards[0].parentElement` carrying `items-stretch`, `h-full` on every card) still hold: the grid `<div>` is still the immediate parent of the cards, just one level deeper under the new title wrapper. Moved `p-4` off the grid onto the new outer wrapper (padding now lives once, at the container, instead of on the inner grid).
- **`blocked-transitions-section.tsx` — touched even though it isn't named in 5.1/5.2/5.4's file list**, because 5.3 explicitly says the `BlockedTransitionsSection` slot is "restyled only if it renders visible chrome of its own" and it does (a heading, canonical-literal `<code>` tags, a date, an error alert, action buttons). Class-only changes, zero structural/DOM changes: heading `text-sm font-semibold text-foreground` → `text-body-base text-muted-foreground` (same caption treatment as property-card's own region headings, for visual consistency across the card); the two canonical-literal `<code>` tags `text-xs` → `text-data-mono` (paired with the pre-existing `font-mono` — the 13px/500-weight "data" role is exactly this use case, matching section 3's tbody-mono reasoning); the error alert and the "30-day window" note `text-xs` → `text-body-base`; the due-since date span `text-xs` (bare) → `text-body-base`. `blocked-transitions-section.test.tsx` (15/15, unmodified) still passes — its assertions are all structural (role, parent/child DOM nesting, text content), never keyed to a class string, so a class-only pass is safe by construction here, but the next implementer touching this file should still run its test explicitly since it lives under `features/dashboard/stalls/`, one directory below the two files 5.4 names.
- **R4 AC2 held:** no KPI cards, occupancy chart, activity feed, or search box added anywhere — confirmed by re-reading the full dashboard mockup (which has all four) and diffing it mentally against what actually got ported (title + the existing property-card grid only).
- **Verified:** `property-card.test.tsx` 9/9, `dashboard-view.test.tsx` 9/9, `blocked-transitions-section.test.tsx` 15/15 (`rtk proxy npx vitest run`, real counts, none of the three test files edited — R7 AC1/AC2 hold). Full `features/dashboard` scope: 25 files / 221 tests, all green, same file/test count as before this section (no test collection regression). `test/color-tokens.test.ts` + `test/color-tokens.patterns.test.ts` + `test/eslint-boundaries.test.ts` + `app/globals.contrast.test.ts` = 120/120 (after the `border-l-primary` revert above). `eslint` clean on all three edited files. `tsc --noEmit` shows only the same 5 pre-existing unrelated errors sections 2-4 already noted (`welcome/page.tsx`, `auth-guard.tsx`, `login-form.tsx` — `searchParams`/`pathname` possibly-null), none in files this section touched.

### Section 6

- **A recurring structural problem this section had to solve that sections 3-5 never hit: three of the five areas' "ad-hoc `Card`-migration divs" are actually `<li>` elements inside a `<ul>`/`<ol>` (`cleaning-task-row.tsx`, `rule-row.tsx`, `recommendation-row.tsx`, `conversation-thread-messages.tsx`'s message rows), not top-level `<div>`s like `property-card.tsx` (5.1) was.** `Card` (`components/ui/card.tsx`) only ever renders a `<div>` — no `asChild`/polymorphism — so `<Card as="li">` isn't possible, and swapping the list item itself for a `Card` `<div>` would put a non-`<li>` element as the direct child of `<ul>`/`<ol>`, an a11y-visible list-structure violation (`getA11yViolations` runs on exactly these rows in `cleaning-task-row.test.tsx`, `rule-row.test.tsx`, `recommendation-row.test.tsx`). **Resolved the same way in all four places:** keep the outer `<li aria-labelledby={headingId}>` bare (`list-none` only, `aria-labelledby` untouched so the accessible name of the listitem doesn't move), and nest `<Card className="...">` directly inside it as the one and only child, carrying all the visual surface classes that used to live on the `<li>` (`flex min-w-0 flex-col gap-3 p-4` for the two row types, `p-3` for the message row). This is the precedent section 7 should copy for `cleaner-task-list-row.tsx` / `tech-incident-row.tsx` if either turns out to be a listitem too — check before assuming `<Card>` drops in directly the way `property-card.tsx` did.
- **Severity/status badge spans with a strict `className` test cannot be touched at all, not even wrapped:** `incidents-view.test.tsx` and `incident-detail-view.test.tsx` both assert `badge.className).toBe(TONE_BADGE_CLASS[severityColorGroup(severity)])` — exact string equality, not "contains". The `<span className={TONE_BADGE_CLASS[...]}>` in both `incidents-view.tsx` and `incident-detail-sections.tsx`'s `DetailHeader` was left byte-for-byte as that one expression (no `cn()`, no extra classes, no `Badge` component wrapper) — only the surrounding `<td>`/header wrapper got typography classes. This is a stricter constraint than the `Badge`-wrapped tone consumers in reservations/pricing/cleaning (`cn(TONE_BADGE_CLASS[tone])` inside a `Badge`), which only have text-content assertions, not class-string ones — check each area's test file for a `.toBe(TONE_BADGE_CLASS[...])`-style assertion before assuming a badge can be re-wrapped.
- **`conversation-thread-messages.test.tsx` pins one exact selector: `container.querySelector("p.whitespace-pre-wrap")`** for the message-content paragraph. Kept `whitespace-pre-wrap` in that `<p>`'s class list (now `max-w-prose whitespace-pre-wrap break-words text-body-base text-foreground` — order doesn't matter to a CSS class selector, presence does) rather than dropping it for a different wrapping utility.
- **6.1 `timeline-view.tsx`:** turned out to be near a no-op — the file has no table, no ad-hoc div, and its `<h1>` already carries `text-xl font-semibold text-foreground` (the same string `reservations-view.tsx`'s pre-existing `<h1>` kept through section 3, per D7 — a screen that already had a bare `<h1>` keeps its own typography, only a screen with NO title gets the invented `text-headline-md` treatment, per sections 4/5). Only real change: the picker `<label>` `text-xs font-medium text-muted-foreground` → `text-body-base font-medium text-muted-foreground`, matching the generic `text-xs`→`text-body-base` conversion sections 3-5 apply to muted incidental text everywhere EXCEPT inside a `{reservations,cleaning,pricing}-filters.tsx`-style filter bar (those tasks explicitly scoped the change to the wrapper only, leaving labels/selects at `text-xs`/`text-sm` — see section 3's notes). Since 6.1 carries no such "controls unchanged" restriction, the wider conversion applied.
- **6.2 `incidents-view.tsx` (D5 table recipe):** copied section 3/4's mapping table verbatim (wrapper `overflow-x-auto rounded-xl border border-border bg-surface`, `<thead>` row `border-b border-border`, `<th>` `whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground`, `<tbody className="font-mono text-data-mono">`, row `border-b border-border last:border-b-0 hover:bg-accent/50 transition-colors`, every `<td>` `px-4 py-3` with non-mono cells (severity, status, title/link, category, source) opting back to `font-sans text-body-base`). No overlay `<Link>` on the row (unlike reservations) — only the title cell links, so no `cursor-pointer`/`group`/`relative` on the `<tr>`, matching the properties-view precedent (section 4) for the same reason. Loading/forbidden/validation/empty/error states (this file hand-rolls `<p>`/`<div>`/`<button>` rather than composing `LoadingState`/`ErrorState` like reservations/dashboard/cleaning/pricing do — a pre-existing difference, NOT changed here, since swapping to the shared components would be a DOM-shape change beyond "restyle") got `text-body-base text-muted-foreground` / `text-body-lg font-semibold text-foreground` / the established `tap-target rounded-md border bg-background px-3 py-1 text-body-base ...` retry-button recipe from section 3's pagination buttons.
- **6.2 `incident-detail-sections.tsx` / `incident-detail-view.tsx` — THE `<dl>`-section shape for section 7 to copy (D9's closing note, first composition pass):** every field-label/value pair that used to be a bare `<h2>{label}</h2><p>{value}</p>` sibling pair is now a shared `DetailField` component (new, local to `incident-detail-sections.tsx`): `<div className="flex flex-col gap-0.5"><dt className="text-label-caps uppercase text-muted-foreground">{label}</dt><dd className={mono ? "font-mono text-data-mono text-foreground" : "text-body-medium text-foreground"}>{value}</dd></div>`, always inside a `<dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">` (or `sm:grid-cols-3` for the 3-up costs/metadata blocks) inside a `<section className="border-b border-border py-4">` (last section drops the `border-b`). `mono` defaults to `true` (ids, dates, cost numbers all read as "data") and is passed `false` only for localized-text fields (status/category/source in `DetailHeader`) so they aren't forced into the monospace face — the same "don't mono a field with its own typography" rule sections 3-5 apply to `Badge` cells, generalized to any localized string. The severity `<span>` badge and the entity title `<h2>` are the two elements deliberately KEPT outside this pattern: the badge because its className is test-pinned (see bullet above), the title because it is a genuine page/section heading, not a label/value pair — `DetailHeader` renders `<h2 className="text-headline-md font-semibold text-foreground">{title}</h2>` for it, mirroring `property-card.tsx`'s card-title treatment. Two single-value prose sections (`DetailDescriptionBlock`, `aiSummary` inside `DetailMetadataBlock`) deliberately do NOT use the `<dl>` pattern — a free-text paragraph isn't the compact "uppercase label + mono value" shape the pattern targets — and instead keep a plain `<h2 className="text-label-caps uppercase text-muted-foreground">` caption above a `text-body-base` paragraph. **Section 7: reuse this exact `DetailField`/`<dl>` shape (uppercase `text-label-caps` `<dt>`, mono-by-default `<dd>` with a `mono={false}` escape hatch, wrapped in `<dl className="grid ... gap-3">` inside a bordered `<section className="border-b border-border py-4">`) for `/cleaner`'s task detail and the guest portal's `StayInfoSection` rather than re-deriving it.**
- **6.3/6.4 `cleaning-task-row.tsx` / `rule-row.tsx` / `recommendation-row.tsx`'s shared `Field` sub-component** (label span + value span, present in all three files, previously `text-xs text-muted-foreground` / `text-sm font-medium text-foreground`) was retyped identically in all three to mirror `property-card.tsx`'s own `Field` from section 5: wrapper gains `text-body-base`, label span drops to bare `text-muted-foreground` (inherits size from the wrapper), value span → `text-body-medium text-foreground`. Kept the existing `flex flex-col` layout (not property-card's `grid-cols-[auto_1fr]` baseline-aligned shape) since neither task asked for a layout change, only typography.
- **6.3 cleaning:** `CleaningFilters`/`RuleFilters`/`RecommendationFilters` (6.3 and 6.4) all got the same glass-panel wrapper treatment as `reservations-filters.tsx`/`properties-filters.tsx` even though their tasks say "onto the token/typography layer" rather than 3.4/4.3's explicit "as a glass panel" — read D4's glass-panel recipe (quoted in this section's own brief: "Glass panel (filter bars, popovers): `bg-surface/60 backdrop-blur-md`") as applying to every filter bar in the tree, not just the two sections that spelled it out. Since none of these three filter bars sit inside a page container with its own `p-4` (unlike reservations/properties), each wrapper also picked up `m-4` (new, not in the reservations/properties precedent) so the rounded panel doesn't render flush against the viewport edge — the one class this section added beyond directly copying the established recipe. Native `<select>`/`<input>`/`<label>` sizes inside all three filter bars were left at their pre-existing `text-xs`/`text-sm` (unchanged), matching the "controls unchanged, wrapper only" precedent from sections 3/4 even though 6.3/6.4's task text doesn't repeat that restriction verbatim.
- **6.3 cleaning:** all four bare `border-b`/`border-t` occurrences across `cleaning-pagination.tsx` (nav), `assign-cleaner-control.tsx`'s reason line (`text-xs`→`text-body-base`, no border there) got `border-border` made explicit; the single live region in `cleaning-view.tsx` gained `py-2 text-body-base text-muted-foreground` (was bare, unstyled text).
- **6.4 pricing:** `pricing-tabs.tsx`'s tablist `border-b` → `border-b border-border`, tab buttons `text-sm font-medium` → `text-body-medium` (the token already carries a medium weight, so the separate `font-medium` utility was redundant and dropped — same reasoning sections 3-5 use whenever a `text-body-*`/`text-data-mono` token already encodes weight). `rules-panel.tsx`/`recommendations-panel.tsx` list wrappers gained `items-stretch` (CSS grid's own default, added for explicitness/consistency with `dashboard-view.test.tsx`'s equivalent assertion pattern — a no-op visually, harmless). `decision-controls.tsx`'s two inline texts (`sending`/confirm-question) → `text-body-base`. `pricing-pagination.tsx` mirrors `cleaning-pagination.tsx`'s `border-t border-border` + `text-body-base` treatment exactly, since both are near-duplicate presentational pagination components by the file's own docstring.
- **6.5 `conversations-view.tsx` (D5 table recipe):** identical shape to 6.2's incidents table (five columns instead of six, escalation-status badge cell same `font-sans text-body-base` opt-out as the severity cell, and the same "no overlay-link row, only the channel cell links" pattern as properties/incidents). Escalation `<span className={TONE_BADGE_CLASS[escalationTone(...)]}>` left untouched byte-for-byte as a precaution — `conversations-view.test.tsx` doesn't actually assert its className (checked directly, no `.toBe(TONE_BADGE_CLASS...)` anywhere in that file, unlike incidents), but treated the untouched-badge-span rule as a blanket policy across every raw (non-`Badge`-wrapped) tone-consumer span in this section rather than re-deriving per file whether the specific test happens to assert it.
- **6.5 `conversation-thread-view.tsx`:** task 6.5's own wording scopes the restyle to specifically "conversation-thread-view.tsx's **message list**" (not the whole file, unlike every other file in this section) — matches D9's text exactly ("the guest portal's message list ... and `conversation-thread-view.tsx`'s message list both get `Card`-based message rows"). The message list is entirely delegated to `ConversationThreadMessages` (a separate file, `conversation-thread-messages.tsx`), so that's the file actually restyled; `conversation-thread-view.tsx` itself (header, the big `<dl>` conversation-metadata grid, reply-form heading, thread pagination) was deliberately left untouched — out of this task's stated scope, and touching it would be exactly the "ya que estoy" scope creep R7's risk section warns about. `conversation-thread-sender-meta.tsx` (rendered inside each message `Card`, so part of "the message list" as delegated content) got the same `border-border`/`text-body-base`/`font-mono text-data-mono` typography pass as the row it lives inside.
- **Verified (per-area, `rtk proxy npx vitest run`, real counts, no test file edited anywhere in this section — R7 AC1/AC2 hold):** `timeline-view.test.tsx` 8/8; `incidents-view.test.tsx` 14/14, full `features/incidents` 120/120 (11 files); `cleaning-task-row.test.tsx` 30/30, full `features/cleaning` 226/226 (14 files); `rule-row.test.tsx` + `recommendation-row.test.tsx` 27/27, full `features/pricing` 227/227 (20 files); `conversations-view.test.tsx` 5/5, full `features/conversations` 87/87 (12 files). Combined `features/dashboard features/incidents features/cleaning features/pricing features/conversations` = 82 files / 881 tests, all green. `test/color-tokens.test.ts` + `test/color-tokens.patterns.test.ts` + `test/eslint-boundaries.test.ts` + `app/globals.contrast.test.ts` = 120/120 (no new colour literal, no `border-{side}-{colorToken}` anywhere — checked every new border/text/bg class against the declared-token list by hand). `eslint` clean on all 23 files this section touched. `tsc --noEmit` shows only the same 5 pre-existing unrelated errors sections 2-5 already noted (`welcome/page.tsx`, `auth-guard.tsx`, `login-form.tsx` — `searchParams`/`pathname` possibly-null), none in files this section touched.
- **Fix round (sdd-architect panel FAIL, D5 table wrapper):** `incidents-view.tsx` and `conversations-view.tsx` had collapsed D5's two-level table wrapper into a single `<div className="overflow-x-auto rounded-xl border border-border bg-surface">`, dropping `overflow-hidden` and merging the outer/inner divs — a deviation from the 6.2/6.5 notes above, which described the intended shape but the code didn't match it. Restored the exact two-level structure sections 3/4 established: outer `<div className="bg-surface border border-border rounded-xl overflow-hidden">`, inner `<div className="overflow-x-auto">`, with the matching extra closing `</div>`. No other classes/structure changed; `features/incidents` (120/120), `features/conversations` (87/87), and `test/color-tokens.test.ts` + `app/globals.contrast.test.ts` (17/17) all still pass.

### Section 7

- **7.5 — no export mockup, derived per D9, confirmed no deviation:** `/cleaner`, `/tech`, and `/guest/[token]` ship with no export mockup (R6 AC2's stated premise). Their composition was derived directly from the token layer and the corresponding already-restyled workspace patterns, per design D9, and was written down there *before* this section started — not improvised screen-by-screen during implementation. Confirming after the fact: no area needed to invent chrome D9 hadn't already named. Every ad-hoc `rounded-lg border bg-surface p-4` block in `features/cleaner` and `features/tech` migrated onto `Card` (dashboard property-card precedent, 5.1); every `<dl>`-shaped data block (`cleaner-task-context-block.tsx`, the incident-report ack panel, the guest portal's `StayInfoSection`) reused the exact `DetailField`/`<dl>` shape section 6 established in `incident-detail-sections.tsx` verbatim — same `<div className="flex flex-col gap-0.5"><dt className="text-label-caps uppercase text-muted-foreground">…</dt><dd className={mono ? "font-mono text-data-mono text-foreground" : "text-body-medium text-foreground"}>…</dd></div>` shape, same `mono` default of `true` with `mono={false}` reserved for the one genuinely free-text field (the guest portal's `arrivalNotes`/"instructions"); and the guest portal's one shared `GuestField` component — which every `<form>` in `guest-portal-view.tsx` (check-in, incident report, conversation reply) already funnelled through — took `reservations-filters.tsx`'s established label (`mb-1 block text-xs font-medium text-muted-foreground`) and input (`rounded-md border bg-background px-3 py-2 text-sm`, `tap-target` added for the 44px floor) recipe once, rather than being restyled three separate times. No new visual pattern was invented anywhere in this section.
- **7.1 `cleaner-task-list-row.tsx` / `tech-incident-row.tsx` — both were `<li>`, section 6's gotcha applied again:** both list rows were already `<li>` elements inside a `<ul>` (`cleaner-task-list-view.test.tsx` and `tech-incident-row.test.tsx` both assert `getByRole("listitem")`), so — per the precedent 6.3/6.4 established for `cleaning-task-row.tsx`/`rule-row.tsx`/`recommendation-row.tsx` — the outer `<li>` was kept bare (`list-none`, `aria-labelledby`/no-attribute untouched) with `<Card>` nested as its one child carrying the row's visual surface classes. `cleaner-task-list-row.tsx`'s `<Link>` (the whole card is one tappable link, unlike `property-card.tsx`'s footer-only link) was kept *inside* the `Card` rather than wrapping it, since `Card` only renders a `<div>` and nesting block content inside an `<a>` is valid HTML — the same reasoning applied to `tech-photo-upload.tsx`'s `<form>` (7.2), which is nested inside a `Card` rather than the reverse, so the form keeps its native submit semantics. `TONE_BADGE_CLASS`/`STATUS_BADGE_CLASS` severity/status badge spans in both rows were left with their pre-existing shape classes (`rounded-full border px-2 py-0.5 text-xs`) concatenated with the tone string exactly as before — no test in this section pins an exact `.toBe(TONE_BADGE_CLASS[...])` string (checked each area's test file first, per the section 6 gotcha), but the shape was kept byte-compatible with the untouched sibling `tech-incident-fields.tsx` badge anyway for visual consistency within `/tech`.
- **7.2 `tech-incident-detail-view.tsx:107,118`:** the two `rounded-lg border bg-surface p-4` status sections (`AWAITING_OWNER_APPROVAL`, `RESOLVED`) migrated directly onto `Card`, exactly as D9 and the task text describe — no new pattern invented. Each kept its outer `<section role="status">` for a11y (Card cannot carry a `role` and stay a plain visual wrapper here since nothing in this section's tests query by that role, but the semantic marker was preserved anyway rather than dropped). `tech-context-block.tsx`, `tech-cycle-actions.tsx`, and `tech-photo-upload.tsx`'s upload `<form>` all got the same `Card` migration for their own pre-existing `rounded-lg border bg-surface p-4` ad-hoc divs (not explicitly named at `:107,118` but the same idiom, per the task's closing "same token/typography pass to the rest of `features/tech/components/detail/*.tsx`"). `tech-eta-field.tsx`, `tech-incident-fields.tsx`, `tech-photo-gallery.tsx`, and `tech-resolve-form.tsx` (the last never had card chrome to begin with) got typography-token conversions only (`text-sm`→`text-body-base`/`text-body-lg`, `min-h-11`→`tap-target`, labels aligned to the `text-xs font-medium text-muted-foreground` convention) with no structural change, since D9 does not ask tech's own form controls to adopt `reservations-filters.tsx`'s recipe — that reuse is scoped explicitly to the guest portal's forms in 7.4.
- **7.3 `cleaner-task-context-block.tsx`:** the only genuine `<dl>`-shaped data block in `/cleaner` — its own ad-hoc `Field` (span-based, not `<dt>/<dd>`) was replaced with a local `DetailField` copied verbatim from `incident-detail-sections.tsx`, and the surrounding `div` grid became a real `<dl>`. All six fields default to `mono={true}` (property name/code, address, timezone, both instants all read as "data"); none needed the `mono={false}` escape hatch. The address field's `sm:col-span-2` span is preserved by wrapping just that one `DetailField` in a plain `<div className="sm:col-span-2">` — the direct grid child needs the span class, not `DetailField`'s own inner div, so this keeps `DetailField` itself unmodified from the section-6 shape rather than adding a `className` prop to it. `cleaner-incident-report-panel.tsx`'s ack block (`id`/`status`/`createdAt`, also genuinely `<dl>`-shaped) got the same `DetailField` treatment (local copy, `sm:grid-cols-3`, `status` passed `mono={false}` since it's a localized status word). Every other `/cleaner` detail file (checklist, checklist item, photo requirements/gallery, photo upload button, completion panel, action bar) had its `rounded-lg border bg-surface p-4` section wrapper migrated onto `Card`; the checklist and photo-requirements per-item rows are `<li>` elements inside `<ul>` (same section-6/7.1 gotcha) so each got a bare `<li className="list-none">` with a nested `Card` (`shadow-none` added since these are small inline rows inside an already-carded list, not standalone cards — avoids a double shadow). The photo gallery's own thumbnail `<li>`s were deliberately left as plain bordered elements rather than wrapped in `Card`: they are tight `object-cover` image tiles (`bg-background`, not `bg-surface`), not a restatement of the `rounded-lg border bg-surface p-4 shadow-sm` idiom `Card`'s own doc comment names as the migration target.
- **7.4 `guest-portal-view.tsx` / `guest-fields.tsx`:** `StayInfoSection` converted from an ad-hoc `<div>`-grid to a real `<dl>` using the same local `DetailField` copy (5/6 fields `mono={true}`; `arrivalNotes`/"instructions" alone passed `mono={false}` as genuine free-text prose, not a compact data value — the one judgment call this section made beyond the task's literal wording, consistent with the mapping table's own "pass false for localized-text fields" rule). `GuestField` (the one component every `<form>` in the file already shares) took `reservations-filters.tsx`'s label/input recipe once, which restyled `CheckinSection`, `IncidentSection`, and `ConversationSection`'s reply form together without repeating the pattern three times. `ConversationSection`'s message list converted its bare `<li className="space-y-1">` rows to the same `Card`-based shape `conversation-thread-messages.tsx` established in section 6 (`<li className="list-none">` → `<Card className="p-3">` with a `header`/sender-badge/`<time>` row and a `max-w-prose whitespace-pre-wrap` content paragraph) — same DOM shape, same classes, restyled surface only, per the task's explicit instruction. All four sections (`StayInfoSection`, `CheckinSection`, `IncidentSection`, `ConversationSection`) were additionally wrapped in `Card` at the section level for the "effect floor" R6 AC1 requires — the pre-existing file had no card chrome on any section at all (bare `<section className="space-y-4">`), and every other workspace/field-shell detail page this change touched (tech, cleaner) wraps its content blocks in `Card`, so leaving the guest portal's four sections bare would have been the "bespoke identity" R6 AC1 forbids, not a faithful derivation of the corresponding restyled pattern.
- **No `border-{side}-{colorToken}` violations, no color literal restated, `test/color-tokens.test.ts` green (7/7).** Checked by hand across all 25 touched files plus a repo-wide grep for the fused directional-border-color shape; none found.
- **Verified (per-area, `rtk proxy npx vitest run`, real counts, no test file edited anywhere in this section — R7 AC1/AC2 hold):** `features/cleaner` 10 files / 87 tests, `features/tech` 7 files / 135 tests, `features/guest-portal` 6 files / 57 tests — combined `features/cleaner features/tech features/guest-portal` = 23 files / 279 tests, all green under `--maxWorkers=2`. One transient timeout hit `guest-portal-view.test.tsx`'s axe-accessibility test when all 23 files ran at full worker concurrency; re-run in isolation (33/33 passed, including that test) and re-run of the full combined set at `--maxWorkers=2` (23/23 files, 279/279 tests) both went green, consistent with host contention rather than a regression (same pattern as the project's own note on suite flakiness under parallel load) — not a real failure, and no code or test changed in response. `eslint` clean on `features/cleaner features/tech features/guest-portal`. `tsc --noEmit` shows no new errors in any file this section touched (only the same pre-existing unrelated errors sections 2-6 already noted).
