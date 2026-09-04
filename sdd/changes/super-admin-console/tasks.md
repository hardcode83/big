# Tasks: super-admin-console

## 1. Backend — `TenantRepository.list_page` port <!-- panel: PASS 2026-09-04 -->

- [x] 1.1 Add `list_page(page: int, per_page: int) -> tuple[Sequence[TenantSettings], int]` to
  the `TenantRepository` protocol (`backend/app/tenants/domain/repositories.py`) and its
  SQLAlchemy implementation (`backend/app/tenants/infrastructure/repositories.py`): a single
  query joining `TenantModel`/`TenantConfigModel` on `tenant_id`, ordered `created_at DESC`,
  plus a `SELECT count(*)` for `total` — same two-query shape as
  `ConversationRepository.list`. Add the round-trip tests to
  `backend/tests/tenants/test_repositories.py`: empty table → `([], 0)`; several tenants →
  `created_at DESC` order and correct `total`; `page`/`per_page` slicing. [R2.2, R2.3, R2.4]

  Note: design D2 states the port's return type as `tuple[Sequence[Tenant], int]`. This task
  returns `Sequence[TenantSettings]` (tenant + its config paired) instead — `TenantSettings`
  is the existing dataclass `TenantResponse.from_settings` already maps from
  (`app/tenants/application/use_cases.py`), and the design's own reasoning ("no
  `get_or_create` defaulting needed — a tenant without a config row cannot exist") only
  holds if the query fetches both rows per tenant in the same pass. Flagged for the
  approval gate, not silently deviated.

## 2. Backend — `GET /api/v1/platform/tenants` <!-- panel: PASS 2026-09-04 -->

- [x] 2.1 Add `ListTenantsUseCase` to `backend/app/platform/application/use_cases.py`: a thin
  pass-through calling `tenants.list_page(page, per_page)`, same shape as
  `ListConversationsUseCase`. [R2.1]
- [x] 2.2 Add `TenantPageResponse` to `backend/app/platform/api/schemas.py` — `items:
  list[TenantResponse]`, `total`, `page`, `per_page`, `total_pages`, a `.build(...)`
  classmethod computing `total_pages` and mapping each `TenantSettings` through
  `TenantResponse.from_settings` — plus module-local `MAX_PER_PAGE = 100` /
  `MAX_PAGE = 100_000`, matching `messaging`'s constants. [R2.1, R2.4]
- [x] 2.3 Add `get_list_tenants_use_case` to `backend/app/platform/api/use_case_dependencies.py`,
  building `ListTenantsUseCase(tenants=SqlAlchemyTenantRepository(session))`. [R2.1]
- [x] 2.4 Add `GET /platform/tenants` to `backend/app/platform/api/router.py`: `PlatformDep`
  gated (same `MANAGE_PLATFORM` permission as the two existing routes), `page`/`per_page`
  query params validated against `MAX_PAGE`/`MAX_PER_PAGE`, `response_model=TenantPageResponse`.
  [R2.1, R2.5]
- [x] 2.5 Tests in `backend/tests/platform/test_api.py`: happy path with several tenants
  (order + shape), empty table → `items: [], total: 0` with `200` (not an error),
  out-of-range `page`/`per_page` → `422`. Tests in `backend/tests/platform/
  test_authorization.py`: extend the existing role matrix (`ALL_ROLES`/`PLATFORM_ROLES`,
  including `fenced_super_admin`) to also cover `GET /platform/tenants`. [R2.1, R2.2, R2.3,
  R2.5]

## 3. Backend — API contract artifacts <!-- panel: PASS 2026-09-04 -->

- [x] 3.1 Regenerate and commit `backend/openapi.json` (`make openapi`) and
  `frontend/lib/api/generated/openapi.d.ts` (`cd frontend && npm run api:generate`) — both
  in the same commit as section 2 (`steering/documentation.md`). In a worktree, use the
  `docker compose cp`/`ln -sfn` workaround documented in the project's `Worktree bootstrap`
  section of `sdd/project.md` before running `api:generate`.

## 4. Frontend — routing & auth wiring for `SUPER_ADMIN` <!-- panel: PASS 2026-09-04 -->

- [x] 4.1 Add `SUPER_ADMIN: "/platform"` to `ROLE_HOME`
  (`frontend/features/auth/lib/role-home.ts`). [R1.1, R1.2]
- [x] 4.2 Add the `"platform"` `ShellProfile` value and one descriptor (`id: "platform"`,
  `pattern: "/platform"`, `profile: "platform"`, no `navigationGroup`) to
  `frontend/features/shell/navigation/route-registry.ts`. [R1.3]
- [x] 4.3 Add `"(platform)/platform/page.tsx": "platform"` to `REAL_PAGE_ROUTE_IDS` in
  `frontend/app/route-coverage.test.ts`, inserted before the final `"page.tsx": "landing"`
  entry (which must stay last). [R1.3]
- [x] 4.4 Create `frontend/app/(platform)/layout.tsx`: `AuthGuard allow={["SUPER_ADMIN"]}`
  around a bare `ShellFrame` (topbar only — `Brand` + `UserMenu`, no sidebar/bottom
  nav/footer), same composition `(authenticated)/layout.tsx` uses for `/welcome`. [R1.3,
  R1.4, R1.5]
- [x] 4.5 Create a placeholder `frontend/app/(platform)/platform/page.tsx` so
  `route-coverage.test.ts` and `route-wiring.test.tsx` pass before the real UI lands in
  section 6 (same "placeholder → real page" pattern the registry comment already
  documents). [R1.3]

## 5. Frontend — `features/platform/` data layer <!-- panel: PASS 2026-09-04 -->

- [x] 5.1 `frontend/features/platform/dto.ts`: camelCase DTOs — `TenantSummaryDto`,
  `TenantListDto` (`items`, `total`, `page`, `perPage`, `totalPages`),
  `CreateTenantInput`, `CreatePlatformUserInput`, `CreatedPlatformUserDto` (nested user +
  `temporaryPassword`). [R2.6, R3.1, R4.1]
- [x] 5.2 `frontend/features/platform/hooks/query-keys.ts`: `platformKeys.tenantsList(page,
  per_page) => ["platform", "tenants-list", page, per_page]` — documented inline as
  deliberately NOT built on `tenantScopedKey` (design D4: `SUPER_ADMIN` has no tenant, and
  that helper throws on an empty `tenantId`). [no requirement directly; infra for R2]
- [x] 5.3 `frontend/features/platform/data/http/http-platform-source.ts`:
  `HttpPlatformSource` class mapping `GET /api/v1/platform/tenants`,
  `POST /api/v1/platform/tenants`, `POST /api/v1/platform/tenants/{tenant_id}/users` to the
  DTOs of 5.1, following `HttpConversationsSource`'s snake_case↔camelCase mapping pattern.
  Unit tests mirroring `http-conversations-source.test.ts`. [R2.1, R3.1, R4.1]
- [x] 5.4 `frontend/features/platform/data/index.ts`: the single composition point,
  `getPlatformDataSource()` via `createAuthenticatedClients` — same shape as
  `features/conversations/data/index.ts`. No mock source, no interface (design D3). [R2.1,
  R3.1, R4.1]
- [x] 5.5 `frontend/features/platform/hooks/use-tenants.ts`: `useTenants(page, perPage)`
  TanStack Query hook over `platformKeys.tenantsList` and
  `getPlatformDataSource().listTenants`. [R2.1, R2.6]
- [x] 5.6 `frontend/features/platform/hooks/use-create-tenant.ts`: mutation hook wrapping
  `createTenant`; does **not** invalidate `platformKeys.tenantsList(...)` (design D6 / R3.2's
  explicit "no refetch"). [R3.1]
- [x] 5.7 `frontend/features/platform/hooks/use-create-platform-user.ts`: mutation hook
  wrapping `createUserInTenant(tenantId, input)`. [R4.1]
- [x] 5.8 `frontend/features/platform/lib/field-errors.ts`: `mapFieldErrors(error: unknown,
  fallbackField?: string): Record<string, string>` — on `422`, reads
  `error.details` as `{errors: {loc: string[]; type: string; msg: string}[]}` and keys by
  `loc`'s last segment; on `409`, returns `{[fallbackField]: error.message}` if
  `fallbackField` is given; anything else returns `{}` (caller falls back to a generic
  error). Unit tests covering all three branches. [R3.3, R4.5]

## 6. Frontend — `features/platform/` UI and the `/platform` console <!-- panel: PASS 2026-09-04 -->

- [x] 6.1 `frontend/features/platform/components/platform-pagination.tsx`: a third
  near-copy of `CleaningPagination`, hardcoding the `"platform"` i18n namespace (design D10
  — no shared generalization in this change). Test mirroring
  `cleaning-pagination.test.tsx`. [R2.6]
- [x] 6.2 `frontend/features/platform/components/tenant-list.tsx`: renders `useTenants`'
  data — name, status, `created_at` per row, `PlatformPagination` when `total` exceeds one
  page, an "add staff" action per row, loading/empty/error states. [R2.6]
- [x] 6.3 `frontend/features/platform/components/create-tenant-form.tsx`: the five
  `CreateTenantRequest` fields as plain controlled inputs (no form library, per design D8),
  calling `useCreateTenant`; on `201` shows the created tenant and a "add staff" button;
  on `422`/`409` shows `mapFieldErrors` output per field. [R3.1, R3.2, R3.3, R3.4]
- [x] 6.4 `frontend/features/platform/components/create-user-form.tsx`: `full_name`,
  `email`, `phone`, and a native `<select>` restricted to `TENANT_OWNER`,
  `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN` (never `SUPER_ADMIN`), pre-scoped to a given
  `tenantId`, calling `useCreatePlatformUser`; `422`/`409` errors via `mapFieldErrors`.
  [R4.1, R4.2, R4.5]
- [x] 6.5 `frontend/features/platform/components/temporary-password-reveal.tsx`: read-only
  monospace field, copy-to-clipboard button (`navigator.clipboard.writeText`), persistent
  warning it will not be shown again; state lives only in the caller's `useState`, never
  written to `localStorage`/query string/history. [R4.3, R4.4]
- [x] 6.6 Wire `frontend/app/(platform)/platform/page.tsx` (replacing the 4.5 placeholder):
  `TenantList` plus a "new tenant" action opening a `Sheet` (reusing `components/ui/
  sheet.tsx`, design D8) that hosts `CreateTenantForm`, then in place switches to
  `CreateUserForm` pre-scoped to the created tenant's id, then to
  `TemporaryPasswordReveal` — one continuous flow, no navigation, no list refetch (D6).
  Each tenant row's "add staff" action opens the same `Sheet` pre-scoped to that row's id.
  [R2.6, R3.2, R4.1]

## 7. Frontend — i18n namespace `platform` <!-- panel: PASS 2026-09-04 -->

- [x] 7.1 `frontend/locales/{es,en}/platform.json`: list column headers, both forms'
  labels/field-errors, the password-reveal copy, the console's own deny/landing copy (no
  hardcoded string anywhere in sections 4-6). Register the `platform` namespace next to
  the others in `frontend/lib/i18n/resources.ts`. [R5.1]

## 8. Verification

- [x] 8.1 Backend suite passes: `docker compose exec backend uv run pytest`
- [x] 8.2 Backend static typing passes: `uv run pyright .` (from `backend`, after `uv sync
  --frozen`)
- [x] 8.3 Frontend suite passes: `cd frontend && npm test` (mind the two pre-existing
  worktree `ENOENT` files documented in `sdd/project.md`'s Worktree bootstrap section —
  they are not this change's regression)
- [x] 8.4 `cd frontend && npm run api:check` confirms no drift between the committed
  `openapi.d.ts` and the regenerated contract
- [x] 8.5 Manual end-to-end check in a browser (`sdd/project.md`'s `PORT_OFFSET` /
  `next start` guidance for a worktree): log in as `SUPER_ADMIN`, land on `/platform`
  (not `/dashboard`), see the tenant list, create a tenant, continue to create its first
  `PROPERTY_MANAGER` without leaving the sheet, see and copy the one-time password, confirm
  a non-`SUPER_ADMIN` role is bounced from `/platform`
