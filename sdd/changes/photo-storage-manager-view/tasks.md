# Tasks: photo-storage-manager-view

## 1. Backend — bootstrap storage gate <!-- panel: PASS 2026-09-18 receipt:9ccd27da -->

- [x] 1.1 In `backend/app/cli/bootstrap.py`, add the environment/storage-type
  check to `build_plan()` (design D6): immediately after the existing
  `missing` required-vars check and before constructing `BootstrapPlan`,
  raise `BootstrapConfigurationError` when `settings.environment != "local"`
  and `settings.bootstrap_storage_type == StorageType.LOCAL.value`, naming
  `BOOTSTRAP_STORAGE_TYPE` in the message. [R3.1, R3.2, R3.3]
- [x] 1.2 In `backend/tests/auth/test_bootstrap.py`, add cases: (a)
  `environment` in `{"dev", "staging", "production"}` with the default
  `bootstrap_storage_type` (`LOCAL`) → `build_plan()` raises
  `BootstrapConfigurationError`; (b) `environment="local"` with `LOCAL` →
  unchanged (plan builds); (c) any non-`local` environment with
  `bootstrap_storage_type=StorageType.S3.value` → unchanged (plan builds,
  mirrors existing cases at lines 339/353/358/373/375). [R3.1, R3.2, R3.4]
- [x] 1.3 Run `docker compose exec backend uv run pytest backend/tests/auth/test_bootstrap.py -q`
  and confirm the new and existing cases pass. [R3]

## 2. Frontend — cleaning task photos data layer <!-- panel: PASS 2026-09-18 receipt:bcd3d01f -->

- [x] 2.1 In `frontend/features/cleaning/data/dto.ts`, add `CleaningPhotoDto`
  (`id`, `cleaningTaskId`, `photoType`, `uploadedBy`, `createdAt`, `url`),
  mapped from the generated `app__cleaning__api__schemas__CleaningPhotoResponse`
  (design D3). [R2.1]
- [x] 2.2 In `frontend/features/cleaning/data/cleaning-source.ts`, add
  `listPhotos(tenantId, taskId): Promise<CleaningPhotoDto[]>` to
  `CleaningDataSource`. In `frontend/features/cleaning/data/http/http-cleaning-source.ts`,
  implement it against `GET /api/v1/cleaning-tasks/{task_id}/photos`,
  returning `response.data` mapped to `CleaningPhotoDto[]`, and cover it in
  `http-cleaning-source.test.ts` (success + tenant-scoped call shape). [R2.1]
- [x] 2.3 In `frontend/features/cleaning/hooks/query-keys.ts`, add
  `cleaningKeys.photos(tenantId, taskId)` and cover it in `query-keys.test.ts`
  (matches `task`'s tenant-scoping shape). [R2.1]
- [x] 2.4 Add `frontend/features/cleaning/hooks/use-cleaning-photos.ts` with
  `useCleaningTaskPhotos(taskId)` (`useQuery` + `retry: retryPolicy`, same
  shape as `useIncidentPhotos`), plus `use-cleaning-photos.test.tsx`
  (pending/success/error). Export both from `frontend/features/cleaning/index.ts`
  where the feature's other public hooks are exported. [R2.1]

## 3. Frontend — cleaning task detail: photo gallery <!-- panel: PASS 2026-09-18 receipt:2907cad9 -->

- [x] 3.1 Add `photos.*` keys to `frontend/locales/es/cleaning.json` and
  `frontend/locales/en/cleaning.json` (title, loading, empty.title/description,
  error.title/description/retry, alt text) — manager-appropriate copy, no
  "photos you upload" language. [R2.6]
- [x] 3.2 Create `frontend/features/cleaning/components/detail/detail-photos-block.tsx`
  (`DetailPhotosBlock`, design D1/D4): consumes `useCleaningTaskPhotos(taskId)`,
  groups photos by `photoType` in first-appearance order (already
  chronological from the API), renders `LoadingState`/`ErrorState`/`EmptyState`
  from `@/components/states`, paints each `url` verbatim in an `<img>`, and
  re-fetches the photo list at most once per photo id on `onError`. No
  upload/delete control. Cover in `detail-photos-block.test.tsx`: loading,
  empty, error+retry, grouped rendering, single re-fetch on image error.
  [R2.1, R2.2, R2.3, R2.4, R2.5]
- [x] 3.3 In `frontend/features/cleaning/components/detail/cleaning-task-detail-view.tsx`,
  compose `<DetailPhotosBlock taskId={task.id} />` after
  `DetailAssignedCleanerBlock` and before the `canManage`-gated
  `DetailManagerActionsBlock` (design D5), unconditional. Update
  `cleaning-task-detail-view.test.tsx` to assert the block renders. [R2.1, R2.5]

## 4. Frontend — incident detail: photo gallery

- [x] 4.1 Add `photos.*` keys to `frontend/locales/es/incidents.json` and
  `frontend/locales/en/incidents.json`, mirroring `tech.json`'s shape (title,
  loading, empty, error, `stage.BEFORE`/`stage.AFTER`, alt) but with
  manager-appropriate empty-state copy (no "photos you upload" language).
  [R1.7]
- [x] 4.2 Create `frontend/features/incidents/components/detail/incident-photos-block.tsx`
  (`IncidentPhotosBlock`, design D1/D2): consumes the existing
  `useIncidentPhotos(incidentId)`, groups by the fixed `STAGES = ["BEFORE", "AFTER"]`
  order (mirrors `TechPhotoGallery`), renders the shared
  `LoadingState`/`ErrorState`/`EmptyState`, paints each `url` verbatim, and
  re-fetches at most once per photo id on `onError`. No upload/delete
  control. Cover in `incident-photos-block.test.tsx`: loading, empty,
  error+retry, grouped-by-stage rendering, single re-fetch on image error.
  [R1.1, R1.2, R1.3, R1.4, R1.5, R1.6]
- [x] 4.3 In `frontend/features/incidents/components/detail/incident-detail-view.tsx`,
  compose `<IncidentPhotosBlock incidentId={d.id} />` after `DetailCostsBlock`
  and before `DetailMetadataBlock` (design D5), unconditional. Update
  `incident-detail-view.test.tsx` to assert the block renders. [R1.1, R1.6]

## 5. Verification

- [ ] 5.1 Backend full test suite passes: `docker compose exec backend uv run pytest`
  (or `docker compose run --rm backend uv run pytest` with the stack down).
  [R3]
- [ ] 5.2 Backend static tooling passes: `uv run pyright .` from `backend`
  (per `sdd/project.md` §Commands). [R3]
- [ ] 5.3 Frontend test suite passes: `cd frontend && npm test` — confirm the
  file/test count is at or above the pre-change baseline (measure, don't
  assume, per `sdd/steering/architecture.md`-adjacent convention in
  `sdd/project.md`). [R1, R2]
- [ ] 5.4 Frontend lint and typecheck pass: `cd frontend && npm run lint` and
  `npm run typecheck`. [R1, R2]
- [ ] 5.5 i18n completeness: every new `photos.*` key exists in both
  `locales/es/` and `locales/en/` for `incidents` and `cleaning` (no
  hardcoded UI string). [R1.7, R2.6]
- [ ] 5.6 Manual check of both galleries against a running stack: log in as
  `TECHNICIAN`, upload a `BEFORE` photo to an in-progress incident; log in as
  `CLEANER`, upload a photo to an in-progress cleaning task; then log in as
  `PROPERTY_MANAGER` (and once as `TENANT_OWNER`) and confirm both photos
  render on `/incidents/[id]` and `/cleaning/[id]` respectively, with no
  upload/delete control visible, and that the empty state shows on an
  incident/task with no photos. `make up PORT_OFFSET=<n>` per
  `sdd/project.md` §Worktree bootstrap. <!-- manual -->

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
- Section 1 (backend bootstrap storage gate) is fully isolated from sections 2-4 (frontend photo galleries) — nothing here changes any name, type, or contract the frontend sections depend on. No handoff needed.
- Section 2 (cleaning photos data layer) is done. Names section 3 builds against:
  - `CleaningPhotoDto` (`frontend/features/cleaning/data/dto.ts`): `{ id, cleaningTaskId, photoType, uploadedBy, createdAt, url }`. `photoType` is a plain `string` (free-form, template-defined — no closed union, unlike incidents' `IncidentPhotoStage`).
  - `CleaningDataSource.listPhotos(tenantId, taskId): Promise<CleaningPhotoDto[]>`, implemented in `HttpCleaningSource.listPhotos` against `GET /api/v1/cleaning-tasks/{task_id}/photos`, unwrapping `CleaningPhotoListResponse.data`.
  - `cleaningKeys.photos(tenantId, taskId)` → `['tenant', tenantId, 'cleaning-photos', taskId]`.
  - `useCleaningTaskPhotos(taskId): UseQueryResult<CleaningPhotoDto[]>` in new file `frontend/features/cleaning/hooks/use-cleaning-photos.ts`, exported from `frontend/features/cleaning/index.ts`. Same shape as `useIncidentPhotos`: `useQuery` + `retry: retryPolicy`, tenant id resolved via a local `useTenantId()` (copied from `use-cleaning-task.ts`, that file itself untouched). No `enabled` guard — unlike `useCleaningTask`, `taskId` is required (not optional) since the detail page always has one by the time it mounts.
  - Adding `listPhotos` to `CleaningDataSource` is a breaking interface change: 5 pre-existing test files that construct a full mock object (not a partial cast) needed a `listPhotos: vi.fn()` added to compile — `cleaning-view.test.tsx`, `use-assign-cleaning-task.test.tsx`, `use-cleaning-data.test.tsx`, `use-cleaning-task.test.tsx`, `use-create-cleaning-task.test.tsx`, `use-validate-cleaning-task.test.tsx`. No behavior in those tests changed. Section 3's `detail-photos-block.test.tsx` and section 4's incident equivalent are new files and won't hit this.
  - Verified: `docker compose exec frontend npm test -- features/cleaning` → 30 files / 542 tests pass; `npm run typecheck` and `npm run lint` both clean.
- Section 3 (cleaning detail photo gallery) is done. `DetailPhotosBlock` (`frontend/features/cleaning/components/detail/detail-photos-block.tsx`) mirrors `TechPhotoGallery` closely — same `LoadingState`/`ErrorState`/`EmptyState` usage, same `useRef<Set<string>>` re-fetch-once-per-photo-id pattern on `onError` — with two changes: grouping by a dynamic `photoType` (first-appearance order, via a small `groupByPhotoType` helper, not a fixed `STAGES` array) and no upload copy at all.
  - i18n JSON convention section 4 should mirror for consistency: the `photos.*` block lives as a **top-level** key in the namespace file (sibling to `detail`), not nested under `detail`, matching `tech.json`'s existing shape — `photos.title`, `photos.loading`, `photos.empty.title/description`, `photos.error.title/description/retry`, `photos.alt`. Since `photoType` here is a free-form string (not a closed enum), there is **no `photos.stage.*` translation table** — the raw `photoType` string is painted directly as the group heading. Section 4's incidents gallery *does* need `photos.stage.BEFORE`/`AFTER` since that stage set is closed and translatable — keep that key only there.
  - Manager-appropriate empty-state copy settled on: EN "No one has uploaded photos for this task yet.", ES "Nadie ha subido fotos de esta tarea todavía." — no "photos you upload" language, since this view never uploads.
  - Test-mocking pattern for a component that calls both `useAuth` and a feature query hook: mock `@/lib/auth`'s `useAuth` to return `{ user: { tenant_id: "tenant-1" } }`, mock `@tanstack/react-query`'s `useQueryClient` to return a stub with a spy-able `invalidateQueries`, and assert the exact `queryKey` array shape (`["tenant", tenantId, "<resource>", id]`) rather than reaching into `cleaningKeys`/`incidentsKeys` — keeps the test decoupled from the key-builder's internals while still proving the single re-fetch and its target.
  - `CleaningTaskDetailView`'s existing test file fully replaces the `@/lib/auth` module mock (`vi.mock("@/lib/auth", () => ({...}))`), so composing any child that calls `useAuth` requires adding `useAuth` to that same mock object — a partial mock without it makes `useAuth()` undefined at runtime. Section 4's `incident-detail-view.test.tsx` likely has the same shape and will need the same addition when it mocks `IncidentPhotosBlock`'s hook usage.
  - Verified: `docker compose exec frontend npm test -- features/cleaning` → 31 files / 549 tests pass (up from section 2's 30/542, i.e. +1 new test file and +7 new tests: 6 in `detail-photos-block.test.tsx` + 1 new assertion in `cleaning-task-detail-view.test.tsx`); `npm run typecheck` and `npm run lint` both clean.
- Section 4 (incidents detail photo gallery) is done. `IncidentPhotosBlock` (`frontend/features/incidents/components/detail/incident-photos-block.tsx`) mirrors `TechPhotoGallery` almost verbatim — same fixed `STAGES = ["BEFORE", "AFTER"]` grouping, same `LoadingState`/`ErrorState`/`EmptyState` usage, same `useRef<Set<string>>` re-fetch-once-per-photo-id pattern on `onError` — with only the translation namespace (`incidents`, not `tech`) and no upload copy. Imports `useIncidentPhotos` from `../../hooks/use-incidents` and `incidentsKeys` from `../../hooks/query-keys` (the same local-module pattern `IncidentDetailView` itself already uses, not the `@/features/incidents` barrel `TechPhotoGallery` uses cross-feature). `photos.*` added as a top-level key in `incidents.json` (both locales), with `photos.stage.BEFORE`/`AFTER` (EN "Before"/"After", ES "Antes"/"Después") since the incident stage set is closed — settled empty-state copy: EN "No one has uploaded photos for this incident yet.", ES "Nadie ha subido fotos de esta incidencia todavía."
  - The predicted gotcha in `incident-detail-view.test.tsx` was real and needed two fixes, not one: (1) its `@/lib/auth` mock only had `useHasPermission`, so `useAuth` was added to it (`{ user: { tenant_id: "tenant-1" } }`), matching section 3's note; (2) `../../hooks/use-incidents` mock only stubbed `useIncident`, so `useIncidentPhotos` was added there too, defaulted in `beforeEach` to a settled empty-array query so every pre-existing test keeps rendering the gallery's empty state untouched. A third issue not flagged by section 3 (because `CleaningTaskDetailView`'s test already wrapped in a real `QueryClientProvider`, but this file's `renderDetail` did not): `IncidentPhotosBlock` calls the real `useQueryClient()` (unlike `DetailPhotosBlock`'s own unit test, which mocks `@tanstack/react-query` directly), so `renderDetail` needed a real `QueryClient`/`QueryClientProvider` wrapper — without it every test failed with "No QueryClient set, use QueryClientProvider to set one," not just the new one.
  - `incident-photos-block.test.tsx` is a new file mirroring `detail-photos-block.test.tsx`'s structure exactly (mocks `@tanstack/react-query`'s `useQueryClient` locally instead of relying on a real provider): 6 tests — loading, empty, error+retry, grouped-by-stage + verbatim url, no upload/delete control, single re-fetch on image error.
  - Verified: `docker compose exec frontend npm test -- features/incidents` → 19 files / 262 tests pass; `docker compose exec frontend npm test` (full suite) → 3687/3688 tests pass across 330/332 files, the one failure (`lib/config/build-identity-contract.test.ts` + its own failed-to-collect sibling `features/provenance/workflow-contract.test.ts`) is a pre-existing, unrelated-to-this-change environment artifact: both read `.github/workflows/deploy-dev.yml` via `join(process.cwd(), "..", ...)`, but the `frontend` docker-compose service only mounts the `frontend/` subtree, not the monorepo root, so `..` from the container's `/app` never reaches a `.github` directory — confirmed the file exists on the host at the repo root and is unrelated to any file this change (sections 1-4) touches. `npm run lint` and `npm run typecheck` both clean on the full project.
  - Cumulative frontend count for the orchestrator's section 5 verification pass: full `npm test` → 330/332 files, 3687/3688 tests pass, with the one pre-existing failure above (not introduced by sections 2-4). `npm run lint` and `npm run typecheck` clean.
