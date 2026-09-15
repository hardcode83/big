# Tasks: staff-messaging-web

## 1. Cleaning task messages — data layer

- [ ] 1.1 Add `CleaningTaskMessage` and `SendCleaningTaskMessageInput` types to
      `frontend/features/cleaner/data/dto.ts` (`{id, authorId, authorRole, content,
      createdAt}`, camelCase per D3). [R1]
- [ ] 1.2 Add `getTaskMessages(tenantId, taskId, page)` and
      `sendTaskMessage(tenantId, taskId, content)` to `CleanerDataSource`
      (`frontend/features/cleaner/data/cleaner-source.ts`) and implement both in
      `HttpCleanerSource` (`frontend/features/cleaner/data/http-cleaner-source.ts`),
      mapping the backend's snake_case envelope to the camelCase DTO — mirror the
      existing methods' shape (`getTaskPhotos`, `uploadPhoto`). Add coverage in
      `http-cleaner-source.test.ts`. [R1]
- [ ] 1.3 Add `messages(tenantId, taskId, page)` and
      `messagesPrefix(tenantId, taskId)` to `cleanerKeys`
      (`frontend/features/cleaner/hooks/query-keys.ts`), same shape as `photos`. [R1]
- [ ] 1.4 Add `"messages"` and `"sendMessage"` to `CleanerErrorKind` and their
      branches in `mapCleanerError` (`frontend/features/cleaner/lib/error-mapping.ts`):
      404 on `messages` → `not-found` state (same as other reads); 422 on
      `sendMessage` → the length-validation copy. [R1, R4]
- [ ] 1.5 Add `useCleanerTaskMessages(taskId, page)` (read, `retryPolicy`, enabled
      only once a tab-open flag is true — see task 2.3) and
      `useSendCleanerTaskMessage(taskId)` (mutation, invalidates
      `cleanerKeys.messagesPrefix` in `onSettled`, per D5) in a new
      `frontend/features/cleaner/hooks/use-cleaner-task-messages.ts`. Unit tests in
      a sibling `.test.tsx`. [R1]

## 2. Cleaning task messages — UI <!-- hard -->

- [ ] 2.1 Add the `messages.*` i18n keys to `frontend/locales/es/cleaner.json` and
      `frontend/locales/en/cleaner.json`: tab label, empty state, error state,
      composer placeholder/label, character counter, validation errors
      (required/too long), send button (idle/pending), send-error copy. [R5]
- [ ] 2.2 New `frontend/features/cleaner/components/detail/cleaner-task-messages-panel.tsx`:
      message list (oldest-first, "cargar mensajes más recientes" button when
      `totalPages > page`, per D4) + composer (native `<textarea maxLength={2000}>`,
      local validation before submit, disabled submit while pending, error preserves
      typed text, per D6) + `LoadingState`/`EmptyState`/`ErrorState` per R4. Component
      test covering loading/empty/error/disabled/validation states. [R1, R4]
- [ ] 2.3 New `frontend/features/cleaner/components/detail/cleaner-task-tabs.tsx`:
      two-tab `role="tablist"` component (content/messages) adapted from
      `reviews-tabs.tsx`, **both panels always mounted**, inactive one hidden via the
      `hidden` attribute (not unmounted — D1, required by R3.2); the messages panel's
      query enables only after the messages tab has been opened once
      (`hasOpenedMessagesTab`, sticky true). Component test covering keyboard
      navigation (←/→/Home/End), `aria-selected`, and that switching tabs does not
      unmount the content panel (e.g. a stateful child keeps its state). [R3]
- [ ] 2.4 Wire `CleanerTaskTabs` into `cleaner-task-detail-view.tsx`: the existing
      content (context block, checklist, photo requirements, gallery, action bar,
      completion panel) becomes the "content" tab (default active), and
      `CleanerTaskMessagesPanel` becomes the "messages" tab. Update
      `cleaner-task-detail-view.test.tsx` accordingly. [R1, R3]
- [ ] 2.5 Add the messages-tab section to `sdd/specs/cleaner-app.md`. [R1]

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
