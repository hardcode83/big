# Tasks: blocked-transitions-web

## Scope dependency

Section 5 (mutation hooks + dialogs) needs OQ1: the backend change that extends
`BlockedTransitionResponse` with `cleaning_task_id` and `incident_id` (design §OQ1). Until that
PR is merged in `main`, `useCancelCleaningTask({ taskId })` and `useResolveIncident({ incidentId })`
are typed against fields the generated `openapi.d.ts` does not yet carry — typecheck will be red
and the per-section test in 5.6 will fail. Sections 1–4 are independent and keep the system
working at every commit (the stalls appear in the card without action buttons, mirroring what
`cleaning-stall-blocks-next-stay` already promised). Run `/sdd:run` up through section 4 and
stop; resume with section 5 only once the OQ1 backend PR is on `main`.

## 1. Types, permissions, action map

- [x] 1.1 Add `EXECUTE_INCIDENTS` to the `Permission` union in `frontend/lib/auth/permissions.ts`
      and to `PROPERTY_MANAGER` in `ROLE_UI_PERMISSIONS`. Document in the JSDoc that the mirror
      stays partial and now also covers the card's resolve-incident action. [R2.4]
- [x] 1.2 Update `frontend/lib/auth/permissions.test.tsx` to assert: `PROPERTY_MANAGER` has both
      `MANAGE_CLEANING_TASKS` and `EXECUTE_INCIDENTS`; `TENANT_OWNER` has none of them;
      `CLEANER`, `TECHNICIAN`, `SUPER_ADMIN` have neither. [R2.1, R2.4]
- [x] 1.3 Create `frontend/features/dashboard/stalls/data/dto.ts` re-exporting
      `BlockedTransitionSummary` as the alias of
      `components["schemas"]["BlockedTransitionResponse"]`. Add a one-line JSDoc pointing at
      `cleaning-stall-blocks-next-stay` R2.2 so the next reader sees why fields are not enriched. [R1.2, R4.2, R4.3]
- [x] 1.4 Create `frontend/features/dashboard/stalls/lib/action-map.ts` with the closed types
      `ClockTrigger` (the three clock triggers: `CHECKIN_WINDOW_OPENED`, `CHECKIN_TIME_REACHED`,
      `CHECKOUT_TIME_REACHED`) and `ActionKind` (`"cancel-cleaning" | "resolve-incident"`), and the
      table `Record<ClockTrigger, Record<PropertyOperationalState, ActionKind>>` plus a runtime
      default of `null` and a compile-time guard `Exclude<…, never>` so a new trigger or state is
      a typecheck error. [R1.5, R2.2, R2.3]
- [x] 1.5 Write `frontend/features/dashboard/stalls/lib/action-map.test.ts` exercising the full
      cartesian product of `ClockTrigger × PropertyOperationalState` and asserting exactly the two
      active combinations from design D3 plus `null` for the rest. One assertion per cell, no
      `if`s. [R1.5]

## 2. Data layer and read hook

- [x] 2.1 Create `frontend/features/dashboard/stalls/data/dto.ts` (already in 1.3) — verify
      `BlockedTransitionSummary` lines up with `BlockedTransitionResponse` field-by-field. Add the
      `tenantScopedKey`-style query key in 2.3 below. [R1.2]
- [x] 2.2 Create `frontend/features/dashboard/stalls/data/stalls-source.ts` declaring
      `StallsDataSource` with one method `listBlockedTransitions(tenantId, page)`, and
      `frontend/features/dashboard/stalls/data/http/http-stalls-source.ts` implementing it against
      `createAuthenticatedClients` (mapping `snake_case` → DTO without renaming). Add
      `frontend/features/dashboard/stalls/data/mock/mock-stalls-source.ts` for tests, and
      `frontend/features/dashboard/stalls/data/index.ts` as the composition point that returns
      `new HttpStallsSource(...)` from `createAuthenticatedClients`. [R1.1, R1.4]
- [x] 2.3 Create `frontend/features/dashboard/stalls/hooks/query-keys.ts` exporting
      `stallsKeys.list(tenantId, page)` using `tenantScopedKey` so the cache key includes the
      tenant. Add a test asserting the key shape (prefix + tenantId + page) and that two
      `tenantId`s produce disjoint keys. [R1.4]
- [x] 2.4 Create `frontend/features/dashboard/stalls/hooks/use-blocked-transitions.ts` returning
      `{ data, byPropertyId }` where `byPropertyId` is a `Map<propertyId, BlockedTransitionSummary[]>`
      sorted by `due_since` ascending, with deterministic tie-break on `reservation_id` and
      `trigger` (R1.1). Pull `tenantId` from `useAuth()`; do not accept it as a parameter. [R1.1, R1.4]
- [x] 2.5 Create `frontend/features/dashboard/stalls/hooks/use-blocked-transitions.test.tsx` with
      a `MockStallsSource` returning three stalls across two properties plus an out-of-order
      `due_since`; assert sort order, tie-break, and tenant isolation by setting two `tenantId`s
      and confirming the second query never sees the first's stalls. [R1.1, R1.4]

## 3. Card integration (read path)

- [x] 3.1 Create `frontend/features/dashboard/stalls/components/blocked-transitions-section.tsx`
      rendering a `<section aria-labelledby>` only when `stalls.length > 0`. Each row shows
      `trigger` and `blocking_state` in a monospaced `<code>` (no translation, no colour swap
      beyond what the existing `STATE_COLOR_GROUP` already applies), and `due_since` formatted
      with `Intl.DateTimeFormat` in the user's locale. Reject any string that is not the literal
      canonical at render time. [R1.2, R4.2, R4.3]
- [x] 3.2 Modify `frontend/features/dashboard/components/dashboard-view.tsx` to call
      `useBlockedTransitions()` once, slice `byPropertyId` per card, and pass the slice as
      `stalls` to `PropertyCard`. Show the localized error state if the stalls query fails
      (`5xx` per R5.3); keep the cards loading the existing way if the stalls query is still
      pending (`isPending` → section omitted). Do **not** invoke `useBlockedTransitions` inside
      `PropertyCard`. [R1.1, R1.4, R5.3]
- [x] 3.3 Modify `frontend/features/dashboard/components/property-card.tsx` to accept an optional
      `stalls?: BlockedTransitionSummary[]` and render `<BlockedTransitionsSection stalls={stalls} />`
      after the existing incident count section, preserving the region order from
      `dashboard-web-frontend.md` §9.1. The component stays rendering unchanged when `stalls` is
      `undefined` or empty (R1.3). [R1.3, R1.4]
- [x] 3.4 Add a test in `frontend/features/dashboard/components/property-card.test.tsx` that
      asserts the section is rendered when `stalls.length > 0` and that the region order remains
      intact (incident count → stalls → next action → reservation → cleaning → last event). [R1.3]

## 4. i18n (catalog parity)

- [x] 4.1 Add the `card.blocked` block to `frontend/locales/es/dashboard.json` with: section title,
      description, `due_since` format, action labels and dialog strings
      (`cancel.cleaning.{label, dialog.title, reason.label, reason.placeholder, reason.help, confirm,
      sending, error.empty, error.generic}`, `resolve.incident.{…}`, plus
      `error.{fetch, forbidden, conflict}`), and the one-line "this list is bounded by
      the same 30-day window the celery job uses" copy that names the window documented in
      `docs/properties.md`. [R4.1, R5.1]
- [x] 4.2 Add the same `card.blocked` block to `frontend/locales/en/dashboard.json` with the
      identical key set. [R4.1]
- [x] 4.3 Run the i18n parity check (`frontend/lib/i18n/catalog-parity.test.ts`) and confirm it
      stays green. If the test discovers a missing key, fix it before moving on. [R4.1]

## 5. Mutations (depends on OQ1 backend PR) <!-- panel: PASS 2026-08-27 -->

> **Gate**: section 5 runs only after the backend change extending `BlockedTransitionResponse`
> with `cleaning_task_id` and `incident_id` is merged in `main` and the regenerated
> `frontend/lib/api/generated/openapi.d.ts` carries those fields. Until then, types 5.1/5.2 will
> not compile. The design intentionally ships this section as a forcing function so the gap
> cannot close in silence.
>
> **Resolved 2026-08-27**: the backend change `blocked-transition-response-ids` is merged in
> `main` (PR #133, see `fe6c875`). `openapi.d.ts:970` carries `cleaning_task_id?` and
> `incident_id?`; section 5 runs.

- [x] 5.1 Create `frontend/features/cleaning/hooks/use-cancel-cleaning-task.ts` with
      `useMutation({ retry: false })` calling
      `POST /api/v1/cleaning-tasks/{task_id}/cancel` and accepting
      `{ taskId: string; reason: string }` (non-empty, max 500 chars enforced in the dialog).
      `onSettled` invalidates the `blocked-transitions` prefix plus the
      `cleaning` keys for the tenant. [R3.1, R3.2]
- [x] 5.2 Create `frontend/features/incidents/hooks/use-resolve-incident.ts` with
      `useMutation({ retry: false })` calling
      `POST /api/v1/incidents/{incident_id}/resolve` and accepting
      `{ incidentId: string; finalCost: number | string }`. `onSettled` invalidates the
      `blocked-transitions` prefix, the incidents keys, the dashboard cards, and the property
      timeline. [R3.1, R3.2]
- [x] 5.3 Create
      `frontend/features/dashboard/stalls/components/cancel-cleaning-dialog.tsx` as a modal
      (`<Sheet>` primitive) with a `<textarea>` (auto-focus via `key`-driven remount,
      max 500 chars with visible counter), `aria-describedby` between label and input,
      localized empty-reason error, and disabled submit while pending. The dialog renders the
      trigger / blocking_state of the targeted stall above the form as canonical literals. [R2.2, R3.1]
- [x] 5.4 Create
      `frontend/features/dashboard/stalls/components/resolve-incident-dialog.tsx` with a
      `<input type="number" inputMode="decimal" min="0" step="0.01">` for `final_cost`, a localized
      validation error if the value is not a positive decimal, and the same trigger /
      blocking_state header. [R2.3, R3.1]
- [x] 5.5 Wire the dialogs into `BlockedTransitionsSection`: a row whose `actionMapFor(stall)` is
      `"cancel-cleaning"` shows the cancel button only when
      `useHasPermission("MANAGE_CLEANING_TASKS")` is `true`; same for `resolve-incident` and
      `EXECUTE_INCIDENTS`. The row that has no actionable kind shows no button (R2.4 — never paint
      a button that would 403). [R2.2, R2.3, R2.4]
- [x] 5.6 Test `BlockedTransitionsSection` with a `MockStallsSource` returning one stall per
      action kind, render it under each role's `useHasPermission`, and assert the buttons
      appear/disappear accordingly. [R2.4, R3.2]
- [x] 5.7 Test the error mapping for the mutation: `4xx`/`5xx` from the cancel mutation surfaces
      the localized `error.generic` (R3.3); a `409` does not retry (`retry: false` — covered in
      `use-cancel-cleaning-task.test.tsx`). [R3.3, R3.4]

## 6. Documentation

- [x] 6.1 Add a section "Aviso de desajustes en la card del dashboard" to `docs/properties.md`
      below the existing cleaning block. Cover: the 30-day window inherited from
      `candidate_window` (sdd/specs/celery-jobs.md); why stalls older than 30 days stop appearing;
      the non-exhaustive nature of the list; the role split (owner's `READ_PROPERTIES` lets her
      see, `MANAGE_CLEANING_TASKS` / `EXECUTE_INCIDENTS` are manager-only); and what to do when
      a cancellation hits `409` because a guest is active (R5.1, R5.2).
- [x] 6.2 Add a one-line note in the card's stalls section copy (i18n keys from 4.1/4.2) that
      names the 30-day window documented in 6.1 (R5.1). Confirm the line is one row at the
      design-system body size and does not introduce new variants.
      **Amended 2026-08-28**: this task said "links to the section added in 6.1". R5.1 was
      amended in the proposal because the app serves no `/docs` route, so there is no in-app
      target to link to; the line names the window instead. Reasoning and the two rejected
      alternatives are in `proposal.md` R5.1 and `design.md` D8.

## 7. Verification

- [x] 7.1 Frontend suite passes: `docker compose exec frontend npm test` (after applying the
      worktree bootstrap `cp` block from `sdd/project.md` §Worktree bootstrap if running from a
      linked worktree — `features/provenance/workflow-contract.test.ts` and
      `lib/config/build-identity-contract.test.ts` will be red otherwise). Measure the baseline
      first; the suite is "passing" if it does not regress against the local count taken at the
      start of this run (per the `pricing-web` 2026-08-23 measurement rule in project.md). [R1–R5]
- [x] 7.2 Typecheck passes: `docker compose exec frontend npx tsc --noEmit`. If the openapi
      contract was updated, confirm `cd frontend && npm run api:check` (using the host-side
      workaround documented in project.md if running from a linked worktree) agrees with the
      regenerated `frontend/lib/api/generated/openapi.d.ts`. [R1.2, R4.2]
- [x] 7.3 Lint passes: `docker compose exec frontend npm run lint`. [R1–R5]
- [x] 7.4 Manual visual check, done by the change owner on 2026-08-29 against this worktree's own
      stack (`make up PORT_OFFSET=41`, seeded tenant, both stall kinds crafted so each card offered
      a different action). Verified with screenshots at every step:
      - **R1.2 / R4.2**: `CHECKIN_TIME_REACHED · AWAITING_CLEANING` and
        `CHECKIN_TIME_REACHED · MAINTENANCE_REQUIRED` render as untranslated monospaced literals in
        both locales, while `due_since` localises (`Aug 27, 2026, 3:00 PM` / `27 ago 2026, 15:00`).
      - **R2.1 / R2.4**: the `TENANT_OWNER` sees both sections in full and **zero** buttons, in ES
        and EN. The `PROPERTY_MANAGER` sees exactly one action per card — cancel on the cleaning
        stall, resolve on the incident stall — never both.
      - **R5.1 / R5.2**: the one-line window copy renders and is **not** a link (per the amendment),
        and promises no exhaustiveness.
      - **R3.1**: resolving sent the required `final_cost`; the backend moved the incident to
        `AWAITING_OWNER_APPROVAL` rather than `RESOLVED` because the amount crossed the approval
        threshold — exactly the outcome D5 cites when rejecting an optimistic cache patch.
      - **R3.4 / R3.3**: a second attempt returned `409` and the dialog showed the *conflict* copy,
        localized, with the form still mounted and the typed amount intact. No backend English
        leaked to the screen.
      - **R3.2**: confirming the cancellation removed the stall row **without a page reload**, and
        the rest of the card refreshed with it — badge `Awaiting cleaning` → `Occupied (estimated)`,
        cleaning status, and last event. That second half only works because of task 8.8; before it,
        the row would have vanished under a stale badge. The other property's stall was untouched.
      - Submit stays disabled until the reason is non-empty (confirmed visually: the button lights
        up on the first character).
      Two observations logged and **not** attributed to this change: `dashboard-api` composes
      `next_action.label` / `cleaning_status` in the user's `preferred_language`, so half a card
      stays in Spanish under an English UI (documented in `docs/dashboard.md`); and the session is
      deliberately not persisted across reloads (`lib/auth/session-store.ts`, guarded by a test that
      forbids writing tokens to any browser store). [R1, R2, R3, R5]

## 8. Review fixes (round 2, 2026-08-28)

Findings raised by the `/sdd:review` panel of 2026-08-28. The panel's own report and the
resolution of each entry live in the git history of `BLOCKED.md`. Nothing is left open: the last
item — D3's guard covering only the trigger axis — was relocated to its real home, the D3 decision
itself, as declared debt with the trigger that would make it worth paying. Keeping it in
`BLOCKED.md` would have parked a design limitation in a queue meant for pending work.

- [x] 8.1 Add `frontend/features/dashboard/stalls/lib/stalls-error.ts`: maps a failed mutation to a
      locale key **by HTTP status**, following `features/cleaning/lib/assign-error.ts` and
      `features/pricing/lib/pricing-error.ts`. `403 → card.blocked.error.forbidden`,
      `409 → card.blocked.error.conflict`, everything else → the per-action generic the caller
      passes. No `401` branch — the client's one-shot refresh owns that path, as both precedents
      document. Covered by `stalls-error.test.ts` (12 tests). [R3.3, R3.4]
- [x] 8.2 Branch both dialogs through `stallsErrorKey` so a `409` shows the conflict copy instead
      of the generic one, and a `403` says the permission is gone rather than "try again". [R3.4]
- [x] 8.3 Guard both dialogs against a double submit dispatched inside one React frame with a
      `submittingRef`, cleared in `onSettled`. `mutation.isPending` only flips on the next commit,
      so it cannot close that window on its own. Verified by removing the guard and watching the
      new test go red. [D7]
- [x] 8.4 Test the dialog error-render path in both dialogs: `isError` with a 500, a 409 and a 403,
      asserting the visible `role="alert"` copy, that the form stays mounted, and that the
      backend's technical message never reaches the DOM. [R3.3, R3.4]
- [x] 8.5 Render the localized `card.blocked.error.fetch` inside the stalls section when the
      dashboard's stalls query fails, instead of substituting an empty map. The flag travels
      `dashboard-view.tsx` → `PropertyCard` → `BlockedTransitionsSection`; a stalls outage never
      escalates to the page-level error state, so the cards stay on screen. [R5.3]
- [x] 8.6 Test R5.3 at both levels: the view passes the flag and keeps the cards
      (`dashboard-view.test.tsx`), and the real section renders the error, keeps its heading, paints
      no action buttons, and prefers the error over stale rows
      (`blocked-transitions-section.test.tsx`). [R5.3]
- [x] 8.7 Guard `formatDateTime`/`formatDate` against a malformed `due_since`: an unparseable value
      returns the raw string instead of throwing `RangeError` inside the render loop, and a
      null-ish value no longer renders the Unix epoch as if it were a real date. Covered by
      `features/dashboard/lib/format.test.ts` (9 tests). [R1.2]
- [x] 8.8 Add the two invalidations design D5 named and the cancel hook omitted —
      `dashboard-cards` (the property's operational state and cleaning cube) and
      `property-timeline` (the cancellation event) — and assert them in the hook test. [R3.2]
- [x] 8.9 Delete the one locale key with no consumer, `card.blocked.error.generic`, from both
      catalogs; the per-dialog generics are the real fallback because they name the action. Every
      remaining `card.blocked.*` key is now reachable from code (audited leaf by leaf). [R4.1]
- [x] 8.10 Amend `design.md` D4: `EXECUTE_INCIDENTS` is granted by the backend to `PROPERTY_MANAGER`
      **and** `TECHNICIAN`, so the old "es del manager" wording was wrong. The mirror's
      `TECHNICIAN: []` stays correct for this screen because `_SELF_SERVICE` does not include
      `READ_PROPERTIES`, which is what guards `GET /api/v1/blocked-transitions` — a technician
      cannot read the endpoint and never sees the section. The amendment names the trigger that
      would make the entry wrong. [R2.4]
- [x] 8.11 Amend `design.md` D5: record that the hooks live in the feature that owns the mutated
      resource (not under `stalls/`, which the text claimed and the code never did), and replace
      the "tres claves" sentence with the per-hook table — the two hooks invalidate four and five
      keys respectively, and the asymmetry is real. [D5]
- [x] 8.12 Amend `design.md` D9: enumerate what the barrel actually exports and why the dialogs sit
      under `features/dashboard/stalls/components/` while their hooks sit in `features/cleaning`
      and `features/incidents` — hook belongs to the resource's domain, dialog belongs to the
      screen that opens it. [D9]
- [x] 8.13 Correct the read-only claims this change invalidated: `README.md` and `docs/dashboard.md`
      (both the "Estado" blockquote and the `/dashboard` route bullet) now say which two write
      actions the card offers, to whom, and against which other domain's endpoints — while keeping
      true the statement that the four `dashboard-api` endpoints are themselves read-only.
- [x] 8.14 Re-verify: `npx tsc --noEmit` clean, `npm run lint` clean, `npm test` **162 files /
      1622 tests, 0 failures**. The five suites that failed on `@radix-ui/react-alert-dialog` in the
      2026-08-27 run now pass — the dependency materialized in the container volume, so that entry
      closed on its own rather than by any edit here.
- [x] 8.15 Amend R5.1 in `proposal.md` and D8 in `design.md`: the requirement asked the card to
      **link** to `docs/properties.md`, and the app serves no `/docs` route, so the href had no
      destination. The half that was already delivered stands — the section in `docs/properties.md`
      and the one-line `card.blocked.window` copy that names the 30-day window — and the link
      requirement is withdrawn. Both rejected alternatives (serving the docs; linking to the
      private GitHub repo, which would 404 for the PRD §1 owner the requirement was written for)
      are recorded in the proposal. Superseded wording grepped tree-wide: tasks 4.1 and 6.2 said
      "links to" and now say "names"; no code or locale referenced the anchor. [R5.1]
- [x] 8.16 Close the three findings the fix re-review raised against the fix itself:
      - `docs/properties.md` still told the reader the card **enlaza** to that section, and had a
        heading «Cuándo abrir esta sección desde la card» implying a navigable link. Both reworded.
        My first sweep missed them because its needles were Spanish-with-«la» and the file says
        «esta»; the second sweep matched on the stem `enlaz\w*` instead.
      - The same file claimed a `409` shows «el motivo que el backend devuelve … tal cual». That
        was never true and is now emphatically not: the dialog paints its own translated copy, and
        `stalls-error.ts` never dereferences `ApiError.message`. Corrected.
      - `design.md` §Changes by area still described the pre-fix world — hooks under
        `stalls/hooks/`, a 4-name barrel, `dashboardKeys.*` invalidation, a deleted locale key, and
        «enlace desde la card» — contradicting the D5/D8/D9 prose amended three sections above.
        Rows rewritten to point at the decisions instead of restating them, which is what let the
        two copies drift apart in the first place.
- [x] 8.17 Add design **D10**: the `format.ts` guard changes the contract of a module shared with
      three pre-existing consumers (`property-card.tsx`, `detail/property-detail-sections.tsx`,
      `detail/property-timeline.tsx`), and no decision covered that. D10 records why the fix
      belongs in the shared module rather than in a stalls-local helper (the other three had the
      same `RangeError`, and a private formatter is how one screen ends up with two date formats),
      why the raw value is returned instead of an empty string, and the accepted styling limit.
      Verified afterwards that every `frontend/…` path `design.md` names exists on disk and that
      no superseded path or key claim survives anywhere in the document.
- [x] 8.18 Fix the defect the visual pass found, which no test could see: the row was a single
      `flex-wrap` line holding two standalone separators, so whenever the date wrapped away from the
      literals the second `·` was stranded at the end of the line
      («CHECKIN_TIME_REACHED · MAINTENANCE_REQUIRED ·» with nothing after it). The row is now two
      rows — literals, then date plus action — so a wrap can only happen where no separator lives,
      and the remaining separator sits in a non-wrapping box with the literal it introduces, so it
      can lead a wrapped line but never trail one. Three regression tests, including one asserting
      every separator shares its box with a `<code>`. [R1.2]
