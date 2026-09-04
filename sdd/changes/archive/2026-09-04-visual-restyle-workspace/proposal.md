# Proposal: visual-restyle-workspace

## Why

`design-system-tokens` (archived 2026-08-24) translated the Stitch export's `DESIGN.md`
into the `@theme` layer — colours, typography, spacing, radii, the light/dark switcher —
but touched no screen. Every already-delivered screen (13 workspace routes, the three
field shells, the guest portal) still renders on the token layer's previous placeholder
values. This change is the other half: apply the new tokens to those screens, and nothing
else.

It exists as its own entry, separate from `design-system-tokens`, for a measurable reason:
that change alters tokens and primitives without shipping a screen; this one repaints every
screen without touching a token. Merged, they would be one change of unmanageable radius,
where a visual defect can't be attributed to the token or to its consumer.

Reference: `docs/design/2026-08-23-stitch-export/` (`DESIGN.md` for the token/effect spec,
six screen mockups, `README.md` for the full census of what was used and what was
discarded). Detailed reasoning per decision: `sdd/roadmap/visual-restyle-workspace.md`.

## What changes

Every screen in `features/shell/navigation/route-registry.ts` (13 workspace destinations),
plus the `/cleaner` and `/tech` field shells and the `/guest/[token]` portal, is restyled
to consume the tokens, typographic roles, spacing/radii and operational-state palette that
`design-system-tokens` already declares — replacing the neutral placeholder styling in
place today. A small set of new component-level visual effects from the export
(glassmorphism surfaces, ambient glow, hover gradient border, primary-button lift) is
introduced for the first time, on existing components, with an explicit accessibility
floor (no state carried by motion alone, no tap target shrinks). No screen's information
architecture, navigation structure, data, or API surface changes — this is presentation
only. Where the export's mockups imply data, features, or navigation the shipped DTOs and
route registry don't have, the DTO/registry wins and the mockup is not followed; four such
gaps were identified during design and diverted to their own roadmap entries rather than
absorbed here (see Out of scope).

## Requirements

### R1 — Reservations screen restyled first, as the fidelity reference

**As a** manager, **I want** the reservations screen restyled to the export's design, **so
that** the rest of the restyle has a proven, contract-compatible reference to imitate
instead of six mockups of uneven fidelity.

Acceptance criteria:

1. WHEN `/reservations` is restyled, THE SYSTEM SHALL apply the design tokens, typography
   and effects to the existing six-column table (Guest, Property, Stay, Status, Channel,
   Amount), its `Status`/`Check-in`/`Check-out`/`Clear filters` filter bar, and its
   Previous/Next pagination, without adding, removing, or reordering columns or filters.
2. THE SYSTEM SHALL leave the build-provenance badge and its "Build provenance" link
   (sourced from `app-version-provenance`) functionally unchanged, restyled only.
3. WHEN `reservas_executive_emerald_style` is used as the fidelity reference for this
   screen, THE SYSTEM SHALL treat any element of that mockup not already present in
   `reservations-web`'s shipped contract as non-authoritative.

### R2 — The other 12 workspace screens receive the same tokens, with the same navigation

**As a** manager or property owner, **I want** every other delivered workspace screen
(properties, dashboard, timeline, incidents, cleaning, pricing, statements, conversations,
approvals, reviews, and the remaining route-registry destinations) restyled with the same
token set, **so that** the product reads as one consistent system rather than one restyled
screen among a dozen unstyled ones.

Acceptance criteria:

1. THE SYSTEM SHALL preserve the existing 13-destination, four-group sidebar
   (`operation`/`work`/`revenue`/`administration`) exactly as `frontend-foundation`
   defines it; THE SYSTEM SHALL NOT remove, merge, or rename any destination and SHALL NOT
   add a destination the route registry does not already serve.
2. THE SYSTEM SHALL adopt only the compositional elements of the export's flatter sidebar
   sketch that are not navigation changes: the brand block with a "Panel de Control"
   subtitle, a visually emphasized primary CTA, and a help entry anchored at the bottom of
   the sidebar.
3. WHEN a screen paints an operational-state or severity badge, THE SYSTEM SHALL continue
   to source its colour from `lib/ui/status-tone.ts` (or, for incident severity,
   `features/incidents/lib/severity-tone.ts`) exactly as `design-system-tokens` requires,
   never restating a colour locally.

### R3 — `/properties` is restyled as its existing table, not as a photo grid

**As a** manager, **I want** the properties screen restyled on its current six-column table
(Property, Code, City, Capacity, Status, Situation) with row cards on mobile, **so that**
the restyle doesn't invent data the backend doesn't serve.

Acceptance criteria:

1. THE SYSTEM SHALL apply the export's typographic hierarchy for page headers, its status
   pill treatment, and its "uppercase label + monospace value" data pattern to the existing
   table cells and mobile row cards.
2. THE SYSTEM SHALL NOT introduce a property photo, an occupancy percentage, a
   month-to-date revenue figure, or a star rating on `/properties`, because
   `PropertySummaryDto` carries none of them.
3. IF implementing this screen appears to require a field `PropertySummaryDto` does not
   expose, THEN THE SYSTEM SHALL leave that element out rather than adding a client-side
   placeholder or a new backend field.

### R4 — Dashboard property cards are restyled; the four aggregate blocks are not added

**As a** property owner, **I want** the dashboard's property cards restyled with the fields
they already show (operational state, open incidents, next action with owner, reservation,
guest, dates, and the amber/blue tone rules of PRD §9.1), **so that** the "what's
happening and who has the next move" answer stays under 10 seconds without inventing data.

Acceptance criteria:

1. THE SYSTEM SHALL restyle the property cards using seed data already returned by
   `GET /api/v1/dashboard/properties`, preserving the exact tone mapping of PRD §9.1
   (amber for `Cleaning scheduled`, blue for `Cleaning in progress`, and the rest as
   already implemented).
2. THE SYSTEM SHALL NOT add the three operational-KPI cards (today's cleanings, upcoming
   check-ins, open incidents), the weekly-occupancy chart, the cross-property activity
   feed, or a global search box to the dashboard, because none of the first three has FE
   composition scoped to this change and the fourth has no backend of any kind.
3. IF a future change scopes the FE composition of the operational-KPI cards, THEN THE
   SYSTEM SHALL treat that composition as its own roadmap entry, never as a silent addition
   to this restyle.

### R5 — Component-level effects, with an accessibility floor

**As a** user with `prefers-reduced-motion: reduce` or who operates by touch, **I want**
the new glassmorphism/glow/hover effects to never be the only carrier of state and to
never shrink a tap target, **so that** the restyle doesn't regress accessibility guarantees
`frontend-foundation` already committed to.

Acceptance criteria:

1. THE SYSTEM SHALL apply glassmorphism surfaces (`backdrop-blur`, 60-80% opacity
   backgrounds), ambient glow on primary actions and headings, a hover-revealed gradient
   top border on feature/stat cards, and a subtle lift on the primary button's hover state,
   sourced from `DESIGN.md`.
2. WHERE a state or affordance (e.g. "this card is interactive") is communicated by a
   hover transition alone, THE SYSTEM SHALL also communicate it through a non-motion cue
   (colour, border, icon, or text), because `globals.css`'s `prefers-reduced-motion:
   reduce` block disables the transition entirely.
3. THE SYSTEM SHALL NOT reduce any interactive element below the existing 44×44 px
   `tap-target` utility to accommodate a new visual effect.
4. IF a new effect requires a colour value the design-token layer does not already declare
   (e.g. the teal ambient-glow tint), THEN THE SYSTEM SHALL declare it as a token in
   `design-system-tokens`'s domain rather than as a raw/arbitrary value, keeping
   `test/color-tokens.test.ts` passing.

### R6 — Field shell and guest portal get tokens, with no reference mockup

**As a** cleaner, technician, or guest, **I want** `/cleaner`, `/tech`, and
`/guest/[token]` restyled with the same tokens as the workspace, **so that** the whole
product — not just the manager-facing half — reflects the new identity.

Acceptance criteria:

1. THE SYSTEM SHALL restyle the three surfaces using the same token layer, typographic
   roles, and effect floor as R1-R5, without inventing a bespoke identity for them.
2. WHEN no export mockup exists for a given field-shell or guest-portal screen (the export
   contains none), THE SYSTEM SHALL derive its composition directly from the token layer
   and the corresponding workspace screen's restyled pattern, and this derivation SHALL be
   written down explicitly in this change's design rather than improvised during
   implementation.

### R7 — No behavioural drift

**As a** maintainer, **I want** this change to leave `features/*` behaviour untouched,
**so that** "restyle" keeps meaning what it says and doesn't quietly ship functional
changes under a styling banner.

Acceptance criteria:

1. THE SYSTEM SHALL leave every existing `features/*` behavioural test passing unmodified;
   the change's own definition of done is that no such test needed editing.
2. IF implementing a screen's restyle appears to require editing a `features/*` behaviour
   test, THEN THE SYSTEM SHALL treat that as evidence the change has stopped being a
   restyle, stop, and raise it rather than editing the test to make it pass.

## Out of scope

- **Sidebar reduction to 6 items** — the export's flat six-item sidebar drops 8 shipped
  destinations (timeline, cleaning, incidents, conversations, approvals, pricing,
  statements, reviews) and adds two ("Analítica", "Ayuda") that exist in no spec, no route,
  and no i18n key. Rejected; if a flatter nav is wanted, it needs its own roadmap entry
  with its own grouping analysis.
- **`/properties` photo grid** — the export's highest-fidelity-mismatch mockup (Villa
  Azure, Marina District NYC, USD amounts — none of it AutoHostAI data) implies a property
  photo, occupancy %, MTD revenue, and star ratings that `PropertySummaryDto` doesn't
  carry. Would need a new photo domain plus three capabilities that already have natural
  owners (`revenue-statements` for MTD revenue, `revenue-reviews` for ratings). Not
  registered as a roadmap entry from this export; census kept in
  `docs/design/2026-08-23-stitch-export/README.md`.
- **Dashboard's three operational-KPI cards' FE composition** — `dashboard-operational-kpis`
  (archived 2026-09-02) now serves `GET /api/v1/dashboard/operational-kpis`, but its own
  proposal explicitly deferred the consuming half to "a roadmap entry of its own, once the
  composition can be seen against real data" rather than to this restyle. Held to that.
- **Dashboard weekly-occupancy chart and cross-property activity feed** — no endpoint
  exists yet for either; tracked as `dashboard-occupancy-series` and
  `dashboard-activity-feed`, now declared `informs-from: visual-restyle-workspace`.
- **Dashboard global search** — not a data the system already has; a full new capability
  the export's topbar merely suggested. Not registered.
- **Two data-quality defects the export's reservations mockup happened to reproduce**
  (a raw UUID in the Property column, a bare `EUR` with no amount) — both were already
  fixed by separate archived changes (`reservation-property-identity`,
  `reservation-amount-empty-render`) before this proposal was written, so there is nothing
  left to exclude here; noted only because the roadmap's analysis note for this entry
  originally flagged them as live and deferred.
- **The export's page artefacts** — `<title>Dashboard - PropManage AI</title>`, `© 2024`,
  a footer duplicated ×4. Not ported, so not "fixed" either.
- **Any new backend route, DTO field, or database change.** If a screen's restyle surfaces
  a data gap, the gap is logged and the DTO wins — the screen adapts, never the other way.

## Affected specs

- `sdd/specs/design-system-tokens.md` — extended with the component-level effect layer
  (glassmorphism, glow, hover gradient border, button lift) and its accessibility floor;
  the token layer itself (colour/typography/spacing/radii) is not renegotiated.
- No behavioural spec (`frontend-foundation.md`, `dashboard-api.md`, `properties-crud.md`,
  `reservations.md`, etc.) is expected to change, because R7 makes an edited behaviour spec
  a signal that the change has left its own scope.
