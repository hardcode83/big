# Design: visual-restyle-workspace

## Context

`design-system-tokens` already declares every colour, typographic role, spacing/radius
token and the light/dark switcher in `frontend/app/globals.css` (three theme-bearing
blocks + two `@theme` blocks). No screen consumes the new roles yet: every "card" in the
tree is an ad-hoc `<div className="rounded-lg border bg-surface p-4 shadow-sm">` repeated
verbatim in `features/dashboard/components/property-card.tsx:80`,
`features/properties/components/list/properties-view.tsx:125`,
`features/cleaning/components/cleaning-task-row.tsx:139`,
`features/cleaner/components/list/cleaner-task-list-row.tsx:48`,
`features/pricing/components/{recommendation-row,rule-row}.tsx`; there is **no
`components/ui/card.tsx`** at all (`components/ui/` holds only alert-dialog, badge,
button, dropdown-menu, separator, sheet, skeleton, tooltip). `components/ui/button.tsx`
has `transition-colors` only, no lift/glow. `frontend/lib/ui/status-tone.ts` and
`features/incidents/lib/severity-tone.ts` are the one place tone colours live and are
already token-driven — they need no change, only more consumers. The guard
`frontend/test/color-tokens.test.ts` fails any raw Tailwind scale class, `dark:` variant,
or colour utility naming an undeclared token; it does **not** scan `@utility` bodies
authored inside `globals.css` itself, only class-name strings in `.ts/.tsx` files
(`test/color-tokens.ts:69-104,327`).

The only shipped glassmorphism today is `features/landing/components/stats-band.tsx:23`
(`bg-surface/60 backdrop-blur`, from `landing-public`) — the token-driven precedent this
change imitates everywhere else. No `hover:translate`, gradient, or glow exists in
non-test code today.

## Decisions

### D1 — Sidebar destination count: the proposal's "13" is wrong, the code has 12

`route-registry.ts` declares 12 entries with a `navigationGroup` (dashboard, timeline,
properties — `operation`; reservations, cleaning, incidents, conversations, approvals —
`work`; pricing, statements, reviews — `revenue`; settings — `administration`), and
`selectNavigationGroups()` (`features/shell/navigation/select-routes.ts:47-63`) filters
strictly on `navigationGroup !== undefined` before rendering `Sidebar`
(`features/shell/components/sidebar.tsx`). `settings-integrations` has neither
`navigationGroup` nor `order` (`route-registry.ts:257-266`), so it never appears in the
sidebar itself — it's reached from inside the Settings page, not the nav. Proposal R2
AC1 and the roadmap both say "13"; the sidebar the code renders has **12** destinations
in 4 groups. Per Jose's direction, this is corrected here rather than in the proposal:
this design and the tasks that follow it treat 12 as authoritative, and R2 AC1's intent
("preserve exactly what exists, add nothing, remove nothing") is unaffected either way.

### D2 — Introduce `components/ui/card.tsx`; effects land there, not per-screen

**Chosen:** a shadcn-shaped `Card` primitive (`Card`, `CardHeader`, `CardContent` —
mirroring the existing `Button`/`Badge` cva shape) becomes the one place that owns
`bg-surface`, `border`, `rounded-xl`, `shadow-sm`, and the new hover-gradient-border
effect (`card-hover-gradient`, D4). The six duplicated ad-hoc divs
(dashboard/properties/cleaning/cleaner/pricing×2) migrate to it. One edit point for an
effect that touches every screen, instead of six copies drifting independently — exactly
the failure mode `status-tone.ts`'s own docstring warns about for shared palettes.

Rejected: leave each screen's div as-is and add the hover-gradient class six times —
rejected because a seventh consumer (guest portal's `StayInfoSection`, `IncidentSection`)
would make it seven, and R7 already flags "ya que estoy" duplication as this change's
named risk.

### D3 — Button gets a `glow` variant, not a new default

**Chosen:** add a `glow` boolean prop (not a new `variant`) to `buttonVariants`
(`components/ui/button.tsx:7-30`) that layers `shadow-[...]` + `hover:-translate-y-px`
onto the existing `default` variant, applied only where R5 AC1 asks for it (primary
actions), via `<Button glow>`. `size.sm` (`h-9`, `:21`) stays under 44px and is
unaffected — R5 AC3 forbids pairing the lift with a shrunk target, so `glow` is not wired
to `size.sm` call sites without also checking their tap-target compliance first (task-
level check, not a design constraint).

Rejected: a `variant: "primary-glow"` — rejected because it would duplicate `default`'s
colour rules instead of composing with them, doubling any future edit to the primary
button's base colour.

### D4 — Glow, glassmorphism and the hover-gradient border reuse `--color-primary`; no new hex

`DESIGN.md`'s glow tint (`#00897b`) does not match the token layer's resolved primary
(`#006b5f` light / `#70d8c8` dark, `globals.css:34,68`) — it's a literal from the mockup's
own Tailwind-v3 config, not a token. Introducing it as a second "brand teal" would create
exactly the drift `design-system-tokens` exists to prevent. **Chosen:** every new effect
is expressed as a `@utility` block in `globals.css`, built from the already-declared
`--color-primary` via `color-mix()`/alpha, never a new hex literal:

- Glassmorphism: `bg-surface/60 backdrop-blur-md` (cards) and `bg-surface/80
  backdrop-blur-xl` (sticky topbar) — both already guard-compliant opacity-modifier
  syntax, same shape as the `stats-band.tsx` precedent. No new utility needed.
- `@utility btn-glow` — `box-shadow` built from `--color-primary` at two alpha steps
  (rest/hover), plus `translate-y` on hover for D3's `glow` prop.
- `@utility card-hover-gradient` — `::before` 1px top border,
  `linear-gradient(90deg, transparent, var(--color-primary), transparent)`, opacity
  0→1 on hover, for Feature/Stat cards (`Card` from D2).
- `@utility text-glow` — `text-shadow` from `--color-primary`, for headings per R5 AC1;
  applied narrowly (page `<h1>`s on the reference screens), not globally.

Because these are hand-authored CSS in `globals.css` referencing an existing declared
token, `color-tokens.test.ts` never sees a new colour literal to reject, and no entry is
added to the palette in `design-system-tokens`'s domain (R5 AC4 is satisfied by *reuse*,
which is a stronger reading of "declare it as a token" than adding a duplicate one).

The two mockups disagree on the glow's alpha (reservations: rest 0.2/hover 0.3 —
`code.html:212-223`; dashboard: 0.39/0.23 — inconsistent with itself, let alone with
reservations). **Chosen:** standardize on the reservations mockup's values, because R1
already designates that screen as the fidelity reference every other screen imitates;
extending that to a numeric disagreement is the same rule, not a new one.

Rejected: the mockup's page-level ambient wash (`body::before`, a fixed 200%×200%
radial-gradient at 3% opacity, `code.html:252-262`) — rejected because R5 AC1 scopes glow
to "primary actions and headings," not the page background, and a permanent full-page
wash is exactly the kind of uninvited addition the roadmap's "riesgo principal" warns
against.

### D5 — No shared `Table` primitive; one class recipe, three call sites

Reservations (`reservations-view.tsx`), incidents-list (`incidents-view.tsx`), and
conversations-list (`conversations-view.tsx`) each hand-roll a `<table>`; none uses a
shared component today. **Chosen:** keep three separate `<table>` elements, but they
share one documented class recipe (below), established on `/reservations` as the R1
reference and copied verbatim to the other two. No new `components/ui/table.tsx`.

Recipe (from `reservas_executive_emerald_style/code.html:355-381`, translated to
declared tokens): wrapper `bg-surface-container-low border border-border rounded-xl
overflow-hidden`, inner `overflow-x-auto`; `<thead>` row `border-b border-border`, `<th>`
`py-md px-lg font-body-medium text-text-secondary whitespace-nowrap`; `<tbody
className="font-data-mono">` with non-numeric cells (status, channel-equivalent text)
opting back to `font-body-base`; row `hover:bg-surface-variant/50 transition-colors
group cursor-pointer`.

Rejected: extracting a shared `Table` primitive now — rejected because none of the three
tables is a literal duplicate (different column sets, different row-link patterns —
reservations uses an `after:absolute after:inset-0` overlay link at
`reservations-view.tsx:151-157` that must not break), so a shared component would need
render-prop columns on day one for a change whose whole premise is "no new
architecture." Revisit if a fourth table appears.

### D6 — Restyle `ModulePlaceholder` once; it covers 5 of the 12 screens

`statements`, `approvals`, `reviews`, `settings`, and `settings/integrations` all render
the same `RoutePlaceholder` → `components/states/module-placeholder.tsx`
(`app/(workspace)/{statements,approvals,reviews,settings,settings/integrations}/page.tsx:12`
each). **Chosen:** one edit to `ModulePlaceholder` (plus the `EmptyState`/`ErrorState`/
`LoadingState`/`StatePanel` family in `components/states/`, 30 importing files total)
covers all five, rather than five separate passes. This also means R2's "12 other
screens" is, in implementation terms, closer to 8 real layouts (reservations already
counted under R1; properties and dashboard under R3/R4) plus this one shared component —
worth stating so tasks doesn't budget five placeholder screens as five times the work.

### D7 — `PageHeader` stays optional, not mandated

`features/shell/components/page-header.tsx` exists, is exported from
`features/shell/index.ts:10`, and has zero consumers today — it's a bare `border-b px-4
py-3` flex row taking a `title`/`actions` slot, not a typography component. **Chosen:**
screens keep their existing header markup (whether a bare `<h1>` like reservations'
`text-xl font-semibold` at `reservations-view.tsx:85`, or none at all like properties')
and apply the export's typographic role classes (`font-headline-lg text-headline-lg`,
etc.) directly, rather than migrating every screen onto `PageHeader` as part of this
change.

Rejected: mandate `PageHeader` adoption everywhere — rejected because it's a structural
swap (new wrapper element, new import) on every one of the 16 surfaces for a change whose
premise is restyling what exists, not consolidating chrome; the token/typography result
looks identical either way. `PageHeader` remains available for whichever future change
wants it.

### D8 — Accessibility floor for hover-only affordances (R5 AC2)

The mockups' interactivity cues are hover-only in three places: reservation table rows
(`hover:bg-surface-variant/50` + `group-hover:text-on-surface`, `code.html:370`),
dashboard/feature cards (`card-hover-gradient`'s border reveal), and secondary-button
hover tint. Under `prefers-reduced-motion: reduce` (`globals.css:314-323`,
`!important`), the *transition* is killed but a plain `:hover` rule still applies on
mouse — so the real gap is users who see the page but never trigger `:hover` (touch,
keyboard, or reduced-motion users who also don't hover-scrub), not motion itself.
**Chosen, as a standing rule for every such element in this change:**

- If the element already ends in a persistent, non-hover, visible action (dashboard's
  property card already has an "open detail" `Link` at `property-card.tsx:176`;
  reservations' status pill and cleaner/tech's "open" affordances are already always
  visible) — that satisfies AC2 as-is; no addition needed.
- If it doesn't (reservation table rows have no persistent visual affordance today
  beyond the overlay `<Link>`), add one static, always-rendered cue inside the existing
  last cell — a `text-muted` chevron icon — never a new column (R1 AC1 forbids that).

### D9 — Field shell and guest portal composition, made explicit (R6.2)

No export mockup exists for `/cleaner`, `/tech`, or `/guest/[token]`. Their composition
derives from the token layer plus the closest already-restyled pattern, not improvised
per screen:

- **`/cleaner` and `/tech` task lists** (`cleaner-task-list-view.tsx`,
  `tech-incidents-view.tsx`, both mobile-only single-column `max-w-md` containers) follow
  the dashboard property-card pattern (D2's `Card`), one card per task/incident.
- **`/tech`'s incident detail already uses a card idiom** (`rounded-lg border bg-surface
  p-4`, `tech-incident-detail-view.tsx:107,118`) — migrates to `Card` directly, no new
  pattern to invent.
- **`/cleaner`'s task detail and the guest portal's `StayInfoSection`** (`<dl>`-shaped
  data, `guest-portal-view.tsx:99`) follow the properties-screen mobile-card pattern:
  "uppercase label + monospace value" (D3 of the roadmap), applied to each `<dt>/<dd>`
  pair.
- **The guest portal's two `<form>`s** (`CheckinSection:193`, `IncidentSection:244`) take
  the same input/label styling as the restyled `reservations-filters.tsx` controls —
  the one form-control pattern this change touches, reused rather than invented twice.
- **The guest portal's message list** (`ConversationSection:297`) and
  `conversation-thread-view.tsx`'s message list both get `Card`-based message rows with
  token typography; neither gains chat-bubble grouping, timestamps-reordering, or any
  IA change — same DOM shape, restyled surfaces only (R7).
- **`incident-detail-view.tsx` has zero styling today** (no `className` in the file) —
  its "restyle" is a first styling pass, not a repaint. It follows the same section-block
  pattern as the guest portal's `<dl>` sections rather than inventing new detail-page
  chrome.

### D10 — Rollout order: primitives first, screens second

Not a scope decision but a sequencing one worth fixing here so `/sdd:tasks` doesn't
serialize 16 independent screen tasks that each reinvent the primitives mid-flight.
**Tier 0** (already shipped): the token layer itself. **Tier 1** (foundation, touched
once, propagates everywhere): `components/ui/button.tsx` (D3, 32 consumers),
`components/ui/card.tsx` (new, D2), `components/states/*` (D6, 30 consumers),
`globals.css` new `@utility` blocks (D4), the new `Record<ReservationStatus, Tone>` map
(R2 AC3 — reservations' status column is plain text today,
`reservations-view.tsx:163`, no badge at all). **Tier 2**: the per-screen container/
typography pass, R1 (reservations) first as the reference, then the remaining 11
screens/surfaces, each swapping its ad-hoc div for `Card`/badge/typography classes built
in Tier 1.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Primitives | `components/ui/card.tsx` (new), `components/ui/button.tsx`, `app/globals.css` | New `Card`; `glow` prop on `Button`; `@utility btn-glow/card-hover-gradient/text-glow` (D2-D4) |
| Shared chrome | `components/states/{module-placeholder,empty-state,error-state,loading-state,state-panel}.tsx` | Token/typography + `Card` surface (D6) |
| Tone mapping | `features/reservations/lib/reservation-status-tone.ts` (new) | `Record<ReservationStatus, Tone>` reading `TONE_BADGE_CLASS`, wired into the status column (R2 AC3) |
| R1 reference | `features/reservations/components/list/{reservations-view,reservations-filters}.tsx`, `features/shell/components/{shell-footer,version-badge}.tsx` | Table recipe (D5), filter bar glass panel, badge status pill, footer/build-badge restyle |
| R2 remaining screens | `features/{timeline,incidents,cleaning,pricing,conversations,approvals}/components/**`, `app/(workspace)/{settings,statements,reviews}/**` | Container/typography pass onto Tier-1 primitives; `incidents-view.tsx`/`conversations-view.tsx` adopt the D5 table recipe |
| R3 properties | `features/properties/components/list/{properties-view,properties-filters}.tsx` | Table recipe + mobile `Card` row with label/mono-value pattern |
| R4 dashboard | `features/dashboard/components/{dashboard-view,property-card}.tsx` | `Card`, stat-box pattern, `card-hover-gradient`; `BlockedTransitionsSection` slot preserved as-is |
| R5 effects | `app/globals.css`, `components/ui/{card,button}.tsx` | Central definition consumed everywhere else (already covered above) |
| R6 field/guest | `features/{cleaner,tech,guest-portal}/components/**` | Derived composition per D9; forms reuse reservations-filters control styling |
| Sidebar/shell composition | `features/shell/components/sidebar.tsx`, `locales/{es,en}/navigation.json` | Brand block "Panel de Control" subtitle, emphasized primary CTA, help entry anchored at bottom (roadmap D2's kept subset) — navigation structure itself untouched |

## Data & interfaces

None. No DTO, endpoint, schema, or event changes (R3 AC2/AC3, R4 AC2, and the proposal's
"Out of scope" section all forbid it). The only new "interface" is presentational:
`Card`'s prop shape (`className`, children — mirrors `Badge`) and `Button`'s new `glow`
boolean.

## Risks & mitigations

- **`Card` migration touching 6+ files could edit a `features/*` behavioural test if one
  asserts exact class strings or DOM structure.** Mitigation: `Card` renders the same
  element type (`div`) with the same semantic children, no new `data-testid`/`role`
  removed; migrate one consumer at a time and run its feature's test file immediately
  after. Per R7 AC2, if any test still needs editing, stop and raise it rather than
  editing the test — that screen's markup stays ad-hoc (still gets token classes) instead
  of blocking the whole change.
- **`incident-detail-view.tsx` is unstyled today**, so its pass is closer to first
  composition than restyle — higher chance of drifting into an IA decision mid-
  implementation. Mitigation: D9's rule (derive from the `<dl>`-section pattern already
  established elsewhere) is fixed here, not left to the implementer.
- **The reservation row's `after:absolute after:inset-0` overlay link** (`reservations-
  view.tsx:151-157`) is easy to break while adding the D8 chevron or D5's table
  wrapper classes, since it depends on the row being `position: relative` and the link
  being the DOM-first interactive element. Mitigation: called out explicitly in tasks;
  verify click-through still lands on the row's target after restyling.
- **Two mockups disagree with each other** (glow alphas, D4) and are dark-theme-only
  (`DESIGN.md` defines no light-theme effect values) — light-theme glow/glass values are
  invented, not ported, and need their own contrast/legibility check since
  `app/globals.contrast.test.ts` only audits declared background/text pairs, not
  effect layers.
- **Scope creep** ("ya que estoy" fixes) is the roadmap's own named top risk. Mitigation
  is already structural: D1-D10 leave nothing about data, navigation, or DTOs open to
  reinterpretation during `/sdd:run`; R7 AC2 is the hard stop if a `features/*` test
  needs touching.

## Open questions

None outstanding — the sidebar-count discrepancy (D1) was resolved with Jose during this
phase (correct it here, not in the proposal); every other judgment call above is decided
with its rejected alternative recorded.
