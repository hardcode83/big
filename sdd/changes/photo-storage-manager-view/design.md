# Design: photo-storage-manager-view

## Context

`/incidents/[id]` (`frontend/features/incidents/components/detail/incident-detail-view.tsx`,
composing sections from `incident-detail-sections.tsx`) and `/cleaning/[id]`
(`frontend/features/cleaning/components/detail/cleaning-task-detail-view.tsx`,
composing block components from the same directory) are both read-only manager
detail pages already in production; neither renders photos today (verified
against the current tree, R1/R2). The precedent for the UI already exists:
`frontend/features/tech/components/detail/tech-photo-gallery.tsx`
(`TechPhotoGallery`) renders `useIncidentPhotos(incidentId)` — from
`frontend/features/incidents/hooks/use-incidents.ts:216`, already exported by
`features/incidents/index.ts` — grouped by the fixed two-value `stage` enum,
with shared `LoadingState`/`ErrorState`/`EmptyState` primitives
(`@/components/states`) and a single-retry-per-photo recovery from an expired
signed URL (`onError` invalidates `incidentsKeys.photos(tenantId, incidentId)`
at most once per mounted photo id).

The cleaning side has no equivalent manager-facing plumbing: `CleaningDataSource`
(`frontend/features/cleaning/data/cleaning-source.ts`) has no `listPhotos`
method, `dto.ts` has no photo type, and `cleaningKeys`
(`frontend/features/cleaning/hooks/query-keys.ts`) has no photo key. The
backend endpoint (`GET /api/v1/cleaning-tasks/{id}/photos`, [`cleaning`
§Fotos de la limpieza](../../specs/cleaning.md)) and its generated contract
(`CleaningPhotoListResponse` / `app__cleaning__api__schemas__CleaningPhotoResponse`
in `frontend/lib/api/generated/openapi.d.ts`) already exist — this is a
consumption gap, not a contract gap.

On the backend, `app/cli/bootstrap.py:build_plan()` already validates the
eleven `BOOTSTRAP_*` variables before opening any transaction and raises
`BootstrapConfigurationError` when one is missing. `bootstrap_storage_type`
(`backend/app/core/config.py:445`) defaults to `LOCAL` regardless of
`settings.environment` (`Literal["local","dev","staging","production"]`,
default `"local"`, `alias="APP_ENVIRONMENT"`) — there is no cross-check
between the two today. A precedent for an environment-gated CLI refusal
exists (`app/cli/sim_advance.py:_env_guard()`), but it refuses the whole
command outside `{local, dev}`; this feature's gate is narrower — bootstrap
stays legal everywhere, only the `LOCAL` **default** becomes illegal outside
`local`.

## Decisions

### D1 — Two feature-local gallery blocks, not a shared cross-feature component

**Chosen:** a new `IncidentPhotosBlock` in
`frontend/features/incidents/components/detail/` and a new
`DetailPhotosBlock` in `frontend/features/cleaning/components/detail/`, each
following `TechPhotoGallery`'s shape (shared `LoadingState`/`ErrorState`/`EmptyState`,
single re-fetch on image `onError`) but manager-appropriate copy (no "the
photos you upload" language — these viewers never upload) and no upload
control. Matches this codebase's existing precedent: `cleaning`'s detail page
already composes six small, feature-local block files rather than a shared
"detail block" abstraction, and `incidents` mirrors that with its own
sections file.

Rejected: extract one shared `frontend/components/media/photo-gallery.tsx`
used by tech, incidents and cleaning — rejected because the grouping
differs in kind, not just in labels: incidents group by a **fixed** two-member
enum (`BEFORE`/`AFTER`) while cleaning groups by a **dynamic** set of
`photo_type` strings the task's checklist template declares (design of
`cleaning` §Fotos de la limpieza), so the shared component would need a
grouping strategy prop from day one for two consumers — the premature
abstraction this project's conventions avoid for a two-use case that is ~40
lines each.

### D2 — Incident gallery reuses the existing hook and query key, zero new incident-side plumbing

**Chosen:** `IncidentPhotosBlock` calls the existing `useIncidentPhotos(incidentId)`
(`use-incidents.ts:216`) directly — no new hook, DTO or query key on the
incidents side. It groups the returned `IncidentPhotoDto[]` by the same
`STAGES = ["BEFORE", "AFTER"]` order `TechPhotoGallery` uses, for the same
reason: a fixed, closed enum reads better as two named sections than as a
flat list.

Rejected: a manager-specific hook wrapping `useIncidentPhotos` — rejected,
there is nothing to wrap; the existing hook already scopes by tenant and
carries no tech-specific behavior.

### D3 — New cleaning-side data/hook layer, mirroring the incidents precedent exactly

**Chosen:** add to the cleaning feature, in the same files the existing
methods already live in:

- `dto.ts` — `CleaningPhotoDto { id, cleaningTaskId, photoType, uploadedBy, createdAt, url }`,
  mapped from `app__cleaning__api__schemas__CleaningPhotoResponse` fields
  (`cleaning_task_id`, `created_at`, `id`, `photo_type`, `uploaded_by`, `url`).
- `data/cleaning-source.ts` — `listPhotos(tenantId, taskId): Promise<CleaningPhotoDto[]>`
  on `CleaningDataSource`.
- `data/http/http-cleaning-source.ts` — `HttpCleaningSource.listPhotos`, calling
  `GET /api/v1/cleaning-tasks/{task_id}/photos` and unwrapping the response's
  `data` array (`CleaningPhotoListResponse.data`), same shape `getTask`
  already follows for its endpoint.
- `hooks/query-keys.ts` — `cleaningKeys.photos(tenantId, taskId)`.
- `hooks/use-cleaning-photos.ts` (new file) — `useCleaningTaskPhotos(taskId)`,
  same `useQuery` + `retry: retryPolicy` shape as `useIncidentPhotos`.

New file for the hook rather than adding to `use-cleaning-task.ts`: that file
is one hook (`useCleaningTask`) with one job (detail-error mapping
downstream), matching the codebase's pattern of one hook-purpose per file in
this feature (`use-assign-cleaning-task.ts`, `use-cancel-cleaning-task.ts`,
`use-validate-cleaning-task.ts` are each their own file).

Rejected: fold photos into `useCleaningTask`'s response — rejected, the
backend serves them as a separate endpoint and resource, and `useQueries`-combining
them would couple two independent loading/error states into one.

### D4 — Grouping order for cleaning photos: template order, not alphabetical

**Chosen:** `DetailPhotosBlock` groups by `photoType` in **first-appearance
order** within the API's own chronological ordering (`created_at, id` —
[`cleaning`](../../specs/cleaning.md) §Fotos de la limpieza), never sorted
alphabetically: the set of valid `photo_type` values is per-template and
this feature does not fetch `GET /api/v1/cleaning-tasks/{id}/photo-requirements`
to learn a canonical order (that stays this feature's out-of-scope — no new
backend call beyond the one endpoint R2 lists).

Rejected: fetch `photo-requirements` to group in the template's declared
order — rejected as scope creep: proposal R2 names exactly one new endpoint
consumer, and the requirements list exists to gate the cleaner's **upload**
button (`cleaner-photo-requirements.md`), a manager-read screen has no
comparable use for it.

### D5 — Composition placement in both detail views

**Chosen:**
- `IncidentDetailView` (`incident-detail-view.tsx`): `<IncidentPhotosBlock incidentId={d.id} />`
  after `DetailCostsBlock`, before `DetailMetadataBlock` — unconditional
  (every viewer who can open the page has `READ_INCIDENTS`, which is what the
  photos endpoint requires too; not gated behind `canManage`).
- `CleaningTaskDetailView` (`cleaning-task-detail-view.tsx`):
  `<DetailPhotosBlock taskId={task.id} />` after `DetailAssignedCleanerBlock`,
  before the `canManage`-gated `DetailManagerActionsBlock` — same
  unconditional rule (`READ_CLEANING_TASKS` is what opened the page).

Rejected: gate the block behind a new permission check — rejected, both
[`incident-photos`](../../specs/incident-photos.md) and
[`cleaning`](../../specs/cleaning.md) already grant the list endpoints to
whoever holds `READ_INCIDENTS`/`READ_CLEANING_TASKS` (verified against
`incidents_router.py` and `tasks_router.py`), and R1.5/R2.4 of the proposal
already commit to no new permission — the roadmap entry that seeded this
change is explicit that both endpoints exist "sin permiso nuevo."

### D6 — The bootstrap storage gate lives in `build_plan()`, not in `Settings`

**Chosen:** add the check as a plain `if` inside `build_plan()`
(`app/cli/bootstrap.py`), immediately after the existing `missing` check and
before constructing `BootstrapPlan`:

```python
if settings.environment != "local" and settings.bootstrap_storage_type == StorageType.LOCAL.value:
    raise BootstrapConfigurationError(
        "BOOTSTRAP_STORAGE_TYPE must be set to 'S3' explicitly when "
        f"APP_ENVIRONMENT={settings.environment!r}; LOCAL is only the safe "
        "default for APP_ENVIRONMENT=local."
    )
```

Reuses the existing `BootstrapConfigurationError` (same class the missing-vars
check raises) rather than a new exception type — same class of refusal
("something the operator's `.env`/inline flags must fix before this command
can run"), and every caller of `build_plan()` already handles that one type.

Rejected: a `model_validator(mode="after")` on `Settings` that cross-checks
`environment` and `bootstrap_storage_type` — rejected for the reason
`config.py`'s own comments give for keeping the two existing secret checks as
**field** validators: a model validator that raises reports the whole
settings object as the offending value, which is a bigger blast radius than
this bootstrap-only rule needs, and `Settings` is imported by `alembic/env.py`
and every entry point — a rule that only matters to `bootstrap.py` does not
belong in the module every process boots through. `build_plan()`'s own
docstring already commits to being "everything, validated before any
transaction" for exactly this class of check.

Rejected: widen `sim_advance.py`'s `_env_guard()` pattern (refuse the whole
command outside an allowlist) — rejected, bootstrap must keep running in
`staging`/`production`; only the silent `LOCAL` default is the problem, not
the command itself.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Backend — bootstrap gate | `backend/app/cli/bootstrap.py` | `build_plan()` raises `BootstrapConfigurationError` when `environment != "local"` and `bootstrap_storage_type == LOCAL` (D6). No new file. |
| Backend — tests | `backend/tests/auth/test_bootstrap.py` | New cases: `environment="dev"`/`"staging"`/`"production"` + default `LOCAL` → raises; `environment="local"` + `LOCAL` → unchanged; any non-local + `S3` → unchanged (mirrors the existing `bootstrap_storage_type` test cases at lines 339/353/358/373/375). |
| Frontend — cleaning data layer | `frontend/features/cleaning/data/dto.ts`, `data/cleaning-source.ts`, `data/http/http-cleaning-source.ts`, `hooks/query-keys.ts` | New `CleaningPhotoDto`, `listPhotos` on the interface + HTTP implementation, `cleaningKeys.photos` (D3). |
| Frontend — cleaning hook | `frontend/features/cleaning/hooks/use-cleaning-photos.ts` (new) | `useCleaningTaskPhotos(taskId)` (D3). |
| Frontend — cleaning UI | `frontend/features/cleaning/components/detail/detail-photos-block.tsx` (new) + `.test.tsx` | `DetailPhotosBlock`, composed into `cleaning-task-detail-view.tsx` (D1, D4, D5). |
| Frontend — incidents UI | `frontend/features/incidents/components/detail/incident-photos-block.tsx` (new) + `.test.tsx` | `IncidentPhotosBlock`, composed into `incident-detail-view.tsx` (D1, D2, D5). |
| Frontend — i18n | `frontend/locales/{es,en}/incidents.json`, `frontend/locales/{es,en}/cleaning.json` | New `photos.*` keys (title, loading, empty.title/description, error.title/description/retry, stage labels for incidents / no fixed labels for cleaning — the `photoType` string itself is the group heading, already free text from the template). |
| Docs | `sdd/specs/incident-photos.md`, `sdd/specs/cleaning.md`, `sdd/specs/auth-tenancy.md`, `sdd/specs/frontend-foundation.md`, `sdd/specs/photo-storage-manager-view.md` (new) | Updated at archive per proposal §Affected specs. |

## Data & interfaces

No new backend endpoint, schema, migration or environment variable. No
`openapi.json` regeneration — both consumed contracts
(`IncidentPhotoListResponse`, `CleaningPhotoListResponse`) are already
published and already in `frontend/lib/api/generated/openapi.d.ts`.

New frontend-only types: `CleaningPhotoDto` (D3), mapped from the existing
generated `app__cleaning__api__schemas__CleaningPhotoResponse`.

Backend behavior change only (no new schema): `build_plan()` raises
`BootstrapConfigurationError` under the condition in D6. No new environment
variable — `BOOTSTRAP_STORAGE_TYPE` already exists in `.env.example` and in
`infra/environments/dev/RUNBOOK.md`.

## Risks & mitigations

- **`.github/workflows/demo-reset.yml` already passes `BOOTSTRAP_STORAGE_TYPE=S3`
  inline** (line 138), so D6 is inert for the one automated flow that runs
  bootstrap against a non-`local` environment today. Mitigation: covered by
  R3.4 and the new test cases; no manual verification needed beyond the
  suite, since the workflow's behavior does not change.
- **A future local developer who sets `APP_ENVIRONMENT=dev` in a personal
  `.env` without meaning to target real dev infra** would now see bootstrap
  refuse rather than silently create a `LOCAL` tenant. This is the intended
  behavior (R3), and the error message names the exact variable to set.
- **Expired signed URL on first paint** (photo list fetched before the URL's
  3600s window elapses is not a realistic race, but a stale cached list
  could be): both new blocks copy `TechPhotoGallery`'s at-most-once-per-photo
  re-fetch, so this is already mitigated by the pattern being reused, not a
  new risk.
- **No backend changes to either photo list endpoint**: both already reject
  cross-tenant access and enforce `READ_INCIDENTS`/`READ_CLEANING_TASKS`
  ([`incident-photos`](../../specs/incident-photos.md),
  [`cleaning`](../../specs/cleaning.md)), so this change inherits that
  isolation rather than introducing a new surface for `sdd-review-tenancy`
  to check — the two new frontend blocks are read-only consumers of an
  already-scoped response.

## Open questions

None. Every proposal requirement maps to a decision above (R1→D1/D2/D5, R2→D1/D3/D4/D5,
R3→D6), and no option here touches a requirement, security posture or an
irreversible action — each choice above is the direct application of an
existing pattern already in the codebase (`TechPhotoGallery`, `build_plan()`,
per-hook-per-file), not a new tradeoff to weigh.
