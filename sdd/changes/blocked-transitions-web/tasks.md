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
      `error.{fetch, forbidden, conflict, generic}`), and the one-line "this list is bounded by
      the same 30-day window the celery job uses" copy that links to `docs/properties.md`. [R4.1, R5.1]
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
      links to the section added in 6.1 (R5.1). Confirm the line is one row at the design-system
      body size and does not introduce new variants.

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
- [ ] 7.4 Manual visual check in `dev` (or in the principal worktree, where the page hydrates —
      see project.md §Worktree bootstrap): open `/dashboard` as a `PROPERTY_MANAGER` and as a
      `TENANT_OWNER`; confirm stalls render with canonical literals and locale-formatted dates;
      cancel a cleaning (success and `409` paths) and resolve an incident; confirm the section
      disappears without a page reload. [R1, R2, R3, R5]
