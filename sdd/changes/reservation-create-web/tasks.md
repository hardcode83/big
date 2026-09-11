# Tasks: reservation-create-web

## 1. API source and DTO contracts <!-- panel: PASS 2026-09-11 receipt:60c1bb55 -->

- [x] 1.1 Extend `frontend/features/reservations/data/dto.ts` with typed mutation inputs and `ReservationSummaryDto` response usage, keeping civil dates, nullable fields and guest input separate from read DTOs [R1, R2, R3]
- [x] 1.2 Add `createReservation`, `updateReservation` and `cancelReservation` to `frontend/features/reservations/data/http/http-reservations-source.ts`, using only generated OpenAPI request schemas, mapping POST/PATCH to summary DTOs and DELETE to `void` [R1, R3, R5]
- [x] 1.3 Add source tests for exact POST/PATCH/DELETE paths, methods, payload omission of empty optionals and no `guest_id` generation [R1, R2, R3]

## 2. Query mutations and authorization <!-- panel: PASS 2026-09-11 receipt:42d7d883 -->

- [x] 2.1 Add `MANAGE_RESERVATIONS` to `frontend/lib/auth/permissions.ts` for `PROPERTY_MANAGER` only and test owner/manager/field-role visibility [R4]
- [x] 2.2 Add create/update/cancel mutation hooks in `frontend/features/reservations/hooks/use-reservations.ts` with `retry: false`, tenant-scoped invalidation of list/detail keys, and awaited invalidation tests [R3, R4]
- [x] 2.3 Add `frontend/features/reservations/lib/mutation-error-mapping.ts` and tests covering `ApiError` 401/403/404/409/422, 5xx and network errors without exposing server PII [R1, R3, R4]

## 3. Manual creation flow <!-- hard --> <!-- panel: PASS 2026-09-11 receipt:3288399d -->

- [x] 3.1 Add the create form component under `frontend/features/reservations/components/create/`, with required property/date fields, optional times/amounts/notes, adults/children and `DIRECT`/`MANUAL` channel only [R1, R2, R5]
- [x] 3.2 Load all active properties through the existing properties source/hooks, expose loading/error/empty states and show selected property's timezone/default times [R1, R2, R4]
- [x] 3.3 Build the create payload with an optional `guest` block (`full_name`, email, phone, preferred language), omit blank optional fields and never expose or send `guest_id`; keep form values after mutation errors [R1, R2, R4]
- [x] 3.4 Wire the form into `frontend/features/reservations/components/list/reservations-view.tsx`, guard it with `MANAGE_RESERVATIONS`, refresh the list after success, and test no duplicate submits, localized success/errors, `preventDefault`, no GET action and no URL/storage PII [R1, R4, R5]

## 4. Detail edit and cancellation flow <!-- hard --> <!-- panel: PASS 2026-09-11 receipt:05cecd0a -->

- [x] 4.1 Add an edit form under `frontend/features/reservations/components/edit/` that initializes from detail data, computes a field-only PATCH diff including explicit nullable clears, and disables `INGEST_OWNED_FIELDS` for non-manual channels [R3, R4]
- [x] 4.2 Add localized cancel confirmation/action using DELETE as cancellation, reflect `CANCELLED` from refreshed detail and timeline, and keep 404/409/422 failures visible [R3, R4, R5]
- [x] 4.3 Wire edit/cancel actions into `frontend/features/reservations/components/detail/reservation-detail-view.tsx`; test backend recalculation refreshes nights/total guests and controls stay hidden/disabled without permission [R3, R4]

## 5. Localization and feature integration

- [ ] 5.1 Add matching ES/EN keys in `frontend/locales/es/reservations.json` and `frontend/locales/en/reservations.json` for labels, help, timezone context, progress, success and mutation error states [R5]
- [ ] 5.2 Update reservations exports and colocated locale/component tests so every visible new string is translated, nullable values use the em dash fallback, and zero remains distinct from empty [R2, R5]

## 6. Verification

- [ ] 6.1 Run the focused reservations tests and confirm they pass: `cd frontend && npm test -- --run frontend/features/reservations` [R1, R2, R3, R4, R5]
- [ ] 6.2 Run the full frontend suite: `cd frontend && npm test` [R1, R2, R3, R4, R5]
- [ ] 6.3 Run frontend lint: `cd frontend && npm run lint` [R4, R5]
- [ ] 6.4 Run the API contract guard without changing generated contract files: `cd frontend && npm run api:check` [R5]
- [ ] 6.5 Perform the browser flow for create, edit and cancel with manager and owner accounts, including ES/EN and a mutation error path <!-- manual --> [R1, R2, R3, R4, R5]

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
- `HttpReservationsSource` mutation responses map to `ReservationSummaryDto`; detail refresh remains query-owned.
- `CreateReservationInput` and `UpdateReservationInput` omit `guest_id` at the type boundary.
- `npm install --ignore-scripts` was required locally because locked Vitest browser dependency was absent from node_modules.
- Section 2 uses `useCreateReservation`, `useUpdateReservation` and `useCancelReservation`; all settle through awaited tenant-scoped list/detail invalidation, without cache writes or retries.
- `reservationMutationErrorKey` returns only localized keys; 401 maps to session handling and server/network error payloads are discarded.
- Section 3 uses `CreateReservationForm` with controlled local state; `useActiveProperties` follows all ACTIVE pages at 100 rows per page and aggregates them for the selector.
- Section 3 payload construction sends only civil dates, permitted manual channels, guest contact fields and nonblank optionals; successful mutation resets the form and errors leave values untouched.
- Section 3 list integration renders the form only for `MANAGE_RESERVATIONS` and explicitly refetches the current list after the mutation hook settles successfully.
- Section 3 focused verification: `npm test -- features/reservations` · 11 files / 106 tests passed; `npm run lint` passed; `git diff --check` passed. `npm test -- --run frontend/features/reservations` is incompatible with the package root and matches no files. `npx tsc --noEmit` remains blocked by pre-existing `.next` validator references to missing `app/(workspace)/page.js`.
- Section 4 uses `EditReservationForm` with `buildReservationPatch` for camelCase detail-to-snake_case field diffs; decimal strings are normalized before comparison and blank nullable values emit `null`.
- Section 4 invalidates `['tenant', tenantId, 'property-timeline']` alongside reservation list/detail after update/cancel, then explicitly refetches the visible detail on success.
- Section 4 focused verification: `npm test -- features/reservations` · 12 files / 138 tests passed; `npm run lint` passed; `git diff --check` passed.
