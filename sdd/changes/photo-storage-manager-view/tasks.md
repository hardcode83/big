# Tasks: photo-storage-manager-view

## 1. Backend — bootstrap storage gate

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

## 2. Frontend — cleaning task photos data layer

- [ ] 2.1 In `frontend/features/cleaning/data/dto.ts`, add `CleaningPhotoDto`
  (`id`, `cleaningTaskId`, `photoType`, `uploadedBy`, `createdAt`, `url`),
  mapped from the generated `app__cleaning__api__schemas__CleaningPhotoResponse`
  (design D3). [R2.1]
- [ ] 2.2 In `frontend/features/cleaning/data/cleaning-source.ts`, add
  `listPhotos(tenantId, taskId): Promise<CleaningPhotoDto[]>` to
  `CleaningDataSource`. In `frontend/features/cleaning/data/http/http-cleaning-source.ts`,
  implement it against `GET /api/v1/cleaning-tasks/{task_id}/photos`,
  returning `response.data` mapped to `CleaningPhotoDto[]`, and cover it in
  `http-cleaning-source.test.ts` (success + tenant-scoped call shape). [R2.1]
- [ ] 2.3 In `frontend/features/cleaning/hooks/query-keys.ts`, add
  `cleaningKeys.photos(tenantId, taskId)` and cover it in `query-keys.test.ts`
  (matches `task`'s tenant-scoping shape). [R2.1]
- [ ] 2.4 Add `frontend/features/cleaning/hooks/use-cleaning-photos.ts` with
  `useCleaningTaskPhotos(taskId)` (`useQuery` + `retry: retryPolicy`, same
  shape as `useIncidentPhotos`), plus `use-cleaning-photos.test.tsx`
  (pending/success/error). Export both from `frontend/features/cleaning/index.ts`
  where the feature's other public hooks are exported. [R2.1]

## 3. Frontend — cleaning task detail: photo gallery

- [ ] 3.1 Add `photos.*` keys to `frontend/locales/es/cleaning.json` and
  `frontend/locales/en/cleaning.json` (title, loading, empty.title/description,
  error.title/description/retry, alt text) — manager-appropriate copy, no
  "photos you upload" language. [R2.6]
- [ ] 3.2 Create `frontend/features/cleaning/components/detail/detail-photos-block.tsx`
  (`DetailPhotosBlock`, design D1/D4): consumes `useCleaningTaskPhotos(taskId)`,
  groups photos by `photoType` in first-appearance order (already
  chronological from the API), renders `LoadingState`/`ErrorState`/`EmptyState`
  from `@/components/states`, paints each `url` verbatim in an `<img>`, and
  re-fetches the photo list at most once per photo id on `onError`. No
  upload/delete control. Cover in `detail-photos-block.test.tsx`: loading,
  empty, error+retry, grouped rendering, single re-fetch on image error.
  [R2.1, R2.2, R2.3, R2.4, R2.5]
- [ ] 3.3 In `frontend/features/cleaning/components/detail/cleaning-task-detail-view.tsx`,
  compose `<DetailPhotosBlock taskId={task.id} />` after
  `DetailAssignedCleanerBlock` and before the `canManage`-gated
  `DetailManagerActionsBlock` (design D5), unconditional. Update
  `cleaning-task-detail-view.test.tsx` to assert the block renders. [R2.1, R2.5]

## 4. Frontend — incident detail: photo gallery

- [ ] 4.1 Add `photos.*` keys to `frontend/locales/es/incidents.json` and
  `frontend/locales/en/incidents.json`, mirroring `tech.json`'s shape (title,
  loading, empty, error, `stage.BEFORE`/`stage.AFTER`, alt) but with
  manager-appropriate empty-state copy (no "photos you upload" language).
  [R1.7]
- [ ] 4.2 Create `frontend/features/incidents/components/detail/incident-photos-block.tsx`
  (`IncidentPhotosBlock`, design D1/D2): consumes the existing
  `useIncidentPhotos(incidentId)`, groups by the fixed `STAGES = ["BEFORE", "AFTER"]`
  order (mirrors `TechPhotoGallery`), renders the shared
  `LoadingState`/`ErrorState`/`EmptyState`, paints each `url` verbatim, and
  re-fetches at most once per photo id on `onError`. No upload/delete
  control. Cover in `incident-photos-block.test.tsx`: loading, empty,
  error+retry, grouped-by-stage rendering, single re-fetch on image error.
  [R1.1, R1.2, R1.3, R1.4, R1.5, R1.6]
- [ ] 4.3 In `frontend/features/incidents/components/detail/incident-detail-view.tsx`,
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
