# Tasks: staff-messaging-web

## 1. Cleaning task messages — data layer <!-- panel: PASS 2026-09-15 receipt:d82a2105 -->

- [x] 1.1 Add `CleaningTaskMessage` and `SendCleaningTaskMessageInput` types to
      `frontend/features/cleaner/data/dto.ts` (`{id, authorId, authorRole, content,
      createdAt}`, camelCase per D3). [R1]
- [x] 1.2 Add `getTaskMessages(tenantId, taskId, page)` and
      `sendTaskMessage(tenantId, taskId, content)` to `CleanerDataSource`
      (`frontend/features/cleaner/data/cleaner-source.ts`) and implement both in
      `HttpCleanerSource` (`frontend/features/cleaner/data/http-cleaner-source.ts`),
      mapping the backend's snake_case envelope to the camelCase DTO — mirror the
      existing methods' shape (`getTaskPhotos`, `uploadPhoto`). Add coverage in
      `http-cleaner-source.test.ts`. [R1]
- [x] 1.3 Add `messages(tenantId, taskId, page)` and
      `messagesPrefix(tenantId, taskId)` to `cleanerKeys`
      (`frontend/features/cleaner/hooks/query-keys.ts`), same shape as `photos`. [R1]
- [x] 1.4 Add `"messages"` and `"sendMessage"` to `CleanerErrorKind` and their
      branches in `mapCleanerError` (`frontend/features/cleaner/lib/error-mapping.ts`):
      404 on `messages` → `not-found` state (same as other reads); 422 on
      `sendMessage` → the length-validation copy. [R1, R4]
- [x] 1.5 Add `useCleanerTaskMessages(taskId, page)` (read, `retryPolicy`, enabled
      only once a tab-open flag is true — see task 2.3) and
      `useSendCleanerTaskMessage(taskId)` (mutation, invalidates
      `cleanerKeys.messagesPrefix` in `onSettled`, per D5) in a new
      `frontend/features/cleaner/hooks/use-cleaner-task-messages.ts`. Unit tests in
      a sibling `.test.tsx`. [R1]

## 2. Cleaning task messages — UI <!-- hard --> <!-- panel: PASS 2026-09-15 receipt:3307ac66 -->

- [x] 2.1 Add the `messages.*` i18n keys to `frontend/locales/es/cleaner.json` and
      `frontend/locales/en/cleaner.json`: tab label, empty state, error state,
      composer placeholder/label, character counter, validation errors
      (required/too long), send button (idle/pending), send-error copy. [R5]
- [x] 2.2 New `frontend/features/cleaner/components/detail/cleaner-task-messages-panel.tsx`:
      message list (oldest-first, "cargar mensajes más recientes" button when
      `totalPages > page`, per D4) + composer (native `<textarea maxLength={2000}>`,
      local validation before submit, disabled submit while pending, error preserves
      typed text, per D6) + `LoadingState`/`EmptyState`/`ErrorState` per R4. Component
      test covering loading/empty/error/disabled/validation states. [R1, R4]
- [x] 2.3 New `frontend/features/cleaner/components/detail/cleaner-task-tabs.tsx`:
      two-tab `role="tablist"` component (content/messages) adapted from
      `reviews-tabs.tsx`, **both panels always mounted**, inactive one hidden via the
      `hidden` attribute (not unmounted — D1, required by R3.2); the messages panel's
      query enables only after the messages tab has been opened once
      (`hasOpenedMessagesTab`, sticky true). Component test covering keyboard
      navigation (←/→/Home/End), `aria-selected`, and that switching tabs does not
      unmount the content panel (e.g. a stateful child keeps its state). [R3]
- [x] 2.4 Wire `CleanerTaskTabs` into `cleaner-task-detail-view.tsx`: the existing
      content (context block, checklist, photo requirements, gallery, action bar,
      completion panel) becomes the "content" tab (default active), and
      `CleanerTaskMessagesPanel` becomes the "messages" tab. Update
      `cleaner-task-detail-view.test.tsx` accordingly. [R1, R3]
- [x] 2.5 Add the messages-tab section to `sdd/specs/cleaner-app.md`. [R1]

## 3. Incident messages — data layer (shared `incidents` module)

- [ ] 3.1 Add `IncidentMessage` and `SendIncidentMessageInput` types to
      `frontend/features/incidents/data/dto.ts` (same shape as task 1.1). [R2]
- [ ] 3.2 Add `getIncidentMessages(tenantId, incidentId, page)` and
      `sendIncidentMessage(tenantId, incidentId, content)` to the incidents data
      source interface and `HttpIncidentsSource`
      (`frontend/features/incidents/data/http/http-incidents-source.ts`). Add
      coverage in its existing test file. [R2]
- [ ] 3.3 Add `messages(tenantId, incidentId, page)` and
      `messagesPrefix(tenantId, incidentId)` to `incidentsKeys`
      (`frontend/features/incidents/hooks/query-keys.ts`), same shape as `photos`. [R2]
- [ ] 3.4 Add `"messages"` and `"sendMessage"` kinds and branches to
      `mapIncidentsError` (`frontend/features/incidents/lib/error-mapping.ts`),
      mirroring task 1.4. [R2, R4]
- [ ] 3.5 Add `useIncidentMessages(incidentId, page)` and
      `useSendIncidentMessage(incidentId)` in a new
      `frontend/features/incidents/hooks/use-incident-messages.ts`, same contract as
      task 1.5. **Export only the hooks/types from `features/incidents/index.ts`, do
      not export or wire any UI component from this module** — the manager's
      `IncidentDetailView` must not gain the message tab (D2, proposal Out of
      scope). Unit tests in a sibling `.test.tsx`. [R2]

## 4. Incident messages — Tech UI <!-- hard -->

- [ ] 4.1 Add the `messages.*` i18n keys to `frontend/locales/es/tech.json` and
      `frontend/locales/en/tech.json` (same key set as task 2.1, own namespace). [R5]
- [ ] 4.2 New `frontend/features/tech/components/detail/tech-incident-messages-panel.tsx`,
      consuming the hooks from `features/incidents` (task 3.5) — same behaviour as
      task 2.2. Component test covering loading/empty/error/disabled/validation
      states. [R2, R4]
- [ ] 4.3 New `frontend/features/tech/components/detail/tech-incident-tabs.tsx`,
      same contract as task 2.3 (both panels mounted, `hidden` on the inactive one,
      sticky lazy-enable flag for the messages query). Component test mirroring
      task 2.3's. [R3]
- [ ] 4.4 Wire `TechIncidentTabs` into `tech-incident-detail-view.tsx`: existing
      content becomes the "content" tab, `TechIncidentMessagesPanel` becomes the
      "messages" tab. Update its existing test file accordingly. [R2, R3]
- [ ] 4.5 Add the messages-tab section to `sdd/specs/tech-app.md`. [R2]

## 5. Docs and verification

- [ ] 5.1 Add a scope note to `sdd/specs/staff-messaging.md`: the frontend
      consumption covers only the two field-role screens (`/cleaner/tasks/[id]`,
      `/tech/incidents/[id]`); the manager view is explicitly not built by this
      change (link the proposal's Out of scope). [R1, R2]
- [ ] 5.2 Full frontend test suite passes: `cd frontend && npm test`.
- [ ] 5.3 Lint passes: `cd frontend && npm run lint`.
- [ ] 5.4 Typecheck passes: `cd frontend && npm run typecheck`.
- [ ] 5.5 `make check-rule11-ownership` still passes (no new free-text sink was
      added on the frontend side — verifies the change did not introduce one by
      accident).
- [ ] 5.6 Manual check: open `/cleaner/tasks/[id]` and `/tech/incidents/[id]` in a
      running stack, confirm the Messages tab renders empty state, send a message,
      confirm it appears without a full page reload, confirm the content tab's
      scroll/state survives a round trip through the messages tab, at 360px
      viewport. <!-- manual -->

## Implementation Notes

- Backend envelope for `GET .../messages`: `CleaningTaskMessagePageResponse` = `{data: CleaningTaskMessageResponse[], page, per_page, total, total_pages}` (identical shape to `CleaningTaskPageResponse`); one row = `{id, author_id, author_role, content, created_at}` — `author_role` is the `UserRole` enum, not a free string.
- Backend body for `POST .../messages`: `SendCleaningTaskMessageRequest = {content: string}`; response on `201` is the created `CleaningTaskMessageResponse` (same row shape as the list).
- `PaginatedResponse<T>` mapping used: `mapPage()` in `http-cleaner-source.ts` (already existed) — `{data, total, page, perPage, totalPages}` camelCase, reused unchanged for messages.
- `MESSAGES_PER_PAGE = 20` constant added in `http-cleaner-source.ts`, separate from `TASKS_PER_PAGE` (same value, kept as its own name since design D4 ties it to the list's constant by value, not by identity).
- The `/messages` path has both `GET` and `POST` operations, so `client.request(...)` needs explicit `<Path, "GET">` type args when passing a `query` object (unlike `getTaskPhotos`, which omits `query` and infers fine) — mirror `listTasks`'s explicit-generics pattern for any sibling `incidents` implementation (task 3.2).
- `mapCleanerError` 422 `sendMessage` copy uses i18n key `messages.errors.tooLong` — section 2's `cleaner.json`/`en.json` (task 2.1) must define this exact key.
- Extending `CleanerDataSource` required adding `getTaskMessages`/`sendTaskMessage` mocks to six pre-existing component test fakes (`cleaner-incident-report-panel.test.tsx`, `cleaner-task-action-bar.test.tsx`, `cleaner-task-checklist-item.test.tsx`, `cleaner-task-detail-view.test.tsx`, `cleaner-task-photo-upload-button.test.tsx`, `cleaner-task-list-view.test.tsx`) so `npm run typecheck` stays green — no behavioral change to those tests, just interface conformance.
- `useCleanerTaskMessages(taskId, page, enabled)` takes `enabled` as a plain third parameter (not an options object) — section 2's `CleanerTaskTabs` passes its sticky `hasOpenedMessagesTab` flag there directly.
- `mapCleanerError` has no pre-existing dedicated unit test file (`error-mapping.test.ts` does not exist in this module); its branches are exercised only through component tests today. The new `"messages"`/`"sendMessage"` branches are verified by code review + typecheck here; section 2's `cleaner-task-messages-panel.test.tsx` (task 2.2) should exercise the error/not-found states end to end.

### Section 2 (cleaner UI) — what sections 3-4 must mirror

- **Tab component shape** (`cleaner-task-tabs.tsx`, mirror it literally in `tech-incident-tabs.tsx`): props are `{content: ReactNode, renderMessages: (enabled: boolean) => ReactNode}`. The component owns **both** `activeTab` (uncontrolled, defaults to `"content"` — R3.1) and the sticky `hasOpenedMessagesTab`, so the detail view passes no tab state. `TAB_ORDER = ["content", "messages"]` and a `PANEL_IDS` record keep the ids stable; tab ids are `cleaner-task-tab-<key>`, panel ids `cleaner-task-panel-<key>` (use `tech-incident-*` for tech).
- **Both panels mounted:** every panel is rendered on every render; the inactive one carries `hidden={key !== activeTab}` and `tabIndex={-1}` (the active one `tabIndex={0}`). Do NOT copy `reviews-tabs.tsx`'s `if (key !== activeTab) return null`. `hidden` also drops the inactive panel from the a11y tree, so `getAllByRole("tabpanel")` returns **1**, not 2 — assert the inactive one with `document.getElementById(...)` + `toHaveAttribute("hidden")` instead.
- **Lazy flag:** `selectTab` sets `hasOpenedMessagesTab` to true on every selection of `"messages"` (click *and* keyboard), never back to false; it is passed to `renderMessages(enabled)` and travels straight into the hook's third parameter.
- **React Compiler lint bans the obvious accumulator.** `react-hooks/set-state-in-effect` rejects `setState` inside `useEffect`, and `react-hooks/refs` rejects reading/writing a `useRef` during render — so pages cannot be accumulated in an effect or in a ref cache. The pattern that lints clean: `olderRows` state + the live `query.data`, `const messages = pageData ? [...olderRows, ...pageData.data] : olderRows`, and a single `advancePast(read)` helper (`setOlderRows(rows => [...rows, ...read.data]); setPage(read.page + 1)`) called **only from event handlers** — the «cargar más recientes» click and the send's `onSuccess`. Run `npx eslint <file>` on any new component before declaring it done.
- **Send tail-follow (R1.2):** `onSuccess` is `async`; it clears the textarea, then `await query.refetch()` and, if the sender was at the tail and the refreshed page reports `totalPages > page`, calls `advancePast(latest)` — a send adds at most one page, so advancing by one is always contiguous.
- **i18n keys added to `frontend/locales/{es,en}/cleaner.json`** (same set, own namespace, for `tech.json` in task 4.1): `tabs.label`, `tabs.content` (the tablist's aria-label and the content tab's label) plus `messages.tab`, `messages.title`, `messages.loading`, `messages.loadNewer`, `messages.empty.{title,description}`, `messages.error.description`, `messages.composer.{label,placeholder,counter,send,sending}`, `messages.roles.{SUPER_ADMIN,TENANT_OWNER,PROPERTY_MANAGER,CLEANER,TECHNICIAN}`, `messages.errors.{required,tooLong}`. The counter interpolates `{{current}}/{{max}}` — **not** `{{count}}`, which i18next would treat as a plural selector. There is no `messages.error.title`: the ErrorState title comes from `mapCleanerError(error, "messages").messageKey` (generic → `detail.error.title`, 404 → `detail.unavailable.title`), and only the description is surface-specific.
- **Author role is rendered through `messages.roles.<UserRole>`**, never as the raw enum value.
- **Panel states:** 404 returns early as an `EmptyState` with no composer (the task/incident is gone); otherwise loading/error/empty only swap the *list* region, so a failed or in-flight **later** page never discards the rows already appended, and the composer stays usable.
- **Test gotcha:** the hooks keep `retry: retryPolicy`, which the test QueryClient's `retry: false` does **not** override — a 5xx fixture retries twice and times the test out. Use a 4xx (e.g. `403`) to exercise the generic ErrorState branch.
- The incident-report trigger only renders while the task is `IN_PROGRESS` (it lives inside `cleaner-task-action-bar.tsx`), so the detail-view test that proves the content panel survives a tab round trip has to set that status first.
- `sdd/specs/cleaner-app.md` gained `### R9` plus corrected Key-files counts: `CleanerDataSource` is now **15** methods (7 reads + 8 mutations, was described as "once") and `cleanerKeys` **9** keys (was "siete") — section 3 should expect the same drift in `sdd/specs/tech-app.md`.
