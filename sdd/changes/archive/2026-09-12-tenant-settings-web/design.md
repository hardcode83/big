# Design: tenant-settings-web

## Context

`frontend/app/(workspace)/settings/page.tsx` and `settings/integrations/page.tsx` are `RoutePlaceholder`s. `(workspace)/layout.tsx` already wraps every workspace route (including both) in `<AuthGuard allow={["TENANT_OWNER", "PROPERTY_MANAGER"]}>` — `CLEANER`/`TECHNICIAN` live under the `cleaner`/`tech` shell profiles and `SUPER_ADMIN` under `platform` (`route-registry.ts`), so none of the three can reach `/settings` today, before or after this change.

The backend (`user-management`) is complete: `GET/POST /api/v1/users`, `GET/PATCH/DELETE /api/v1/users/{id}`, `POST /api/v1/users/{id}/reset-password`, `GET/PATCH /api/v1/tenants/{id}` — eight routes in total. A structurally similar frontend already exists for `SUPER_ADMIN` in `frontend/features/platform/` (`create-user-form.tsx`, `temporary-password-reveal.tsx`, `platform-console.tsx`), but it is wired to the **platform-admin** routes (`/api/v1/platform/tenants/{tenant_id}/users`), which require `SUPER_ADMIN` and take an explicit `tenantId`. A `TENANT_OWNER` cannot call those routes at all (`user-management` §Aislamiento: `WHERE el rol es SUPER_ADMIN … 403` on the tenant-scoped routes, and symmetrically the platform routes require `SUPER_ADMIN`), so this change cannot literally reuse `CreateUserForm`/`useCreatePlatformUser`/`useTenants` — see D1.

`DELETE /api/v1/users/{user_id}` (`users_router.py:180-203`) is its own documented endpoint — "Deactivate a user," idempotent, `204`, refuses self-deactivation and the last active owner, same guards as `PATCH`. Reactivation has no dedicated endpoint: it goes through `PATCH {status: "ACTIVE"}`, the same path `SUSPENDED` uses (`UserStatus` has no dedicated "suspend"/"reactivate" verb, only the enum on `PATCH`). See D7.

Tenant-scoped features already have an established shape to follow: `frontend/features/reservations/` (`data/index.ts` composition point, `tenantScopedKey`-based query keys, a `useTenantId()` helper reading `useAuth().user.tenant_id`, `retryPolicy`). `frontend/lib/auth/permissions.ts` already implements the exact "owner does X, manager reads" split this feature needs, for other capabilities (`MANAGE_CLEANING_TASKS`, `MANAGE_INCIDENTS`, etc.) — see D2.

## Decisions

### D1 — New `frontend/features/tenant-settings` module; reuse only `TemporaryPasswordReveal` and `mapFieldErrors` from `platform`

**Chosen:** a new feature module (`data/http`, `hooks`, `components/{list,detail}`, `locales`, `dto.ts`, `index.ts`) shaped like `features/reservations`, calling the tenant-scoped endpoints (`/api/v1/users*`, `/api/v1/tenants/{id}`) through its own `HttpTenantSettingsSource`. It cross-feature-imports two pieces from `@/features/platform`, which are endpoint-agnostic:
- `TemporaryPasswordReveal` (props are just `temporaryPassword`/`userName` — no platform-specific wiring). It is not currently exported from `features/platform/index.ts`; this change adds that one export line.
- `mapFieldErrors` (already exported; takes `unknown` + `fallbackField`, reads the same `_serialisable_validation_errors` envelope shape every backend endpoint uses).

Rejected: reusing `CreateUserForm`/`useCreatePlatformUser`/`useTenants` as-is — they call `/api/v1/platform/tenants/{tenant_id}/users` and `/api/v1/platform/tenants`, both `SUPER_ADMIN`-only; a `TENANT_OWNER` calling them gets `403`. Rejected: a shared cross-feature "user form" abstracting both endpoints — the two request bodies already differ (`CreateUserRequest` has no `tenant_id`, drawn from the token; the platform one takes `tenantId` from the path) and forcing one component to branch on which endpoint it targets duplicates the platform admin console's own `AuditLog`/D5 reasoning for no real gain.

### D2 — Two new UI permissions in `lib/auth/permissions.ts`, `TENANT_OWNER`-only

**Chosen:** add `"MANAGE_USERS"` and `"MANAGE_TENANT_SETTINGS"` to the `Permission` union and to `ROLE_UI_PERMISSIONS.TENANT_OWNER` only — mirroring `backend/app/auth/domain/policy.py`'s `_USER_MANAGE`/`_TENANT_MANAGE` bundles exactly (`PROPERTY_MANAGER` holds the paired `READ_*` permission but not the `MANAGE_*` one). `useHasPermission("MANAGE_USERS")` gates every create/edit/deactivate/reset-password control on the users section; `useHasPermission("MANAGE_TENANT_SETTINGS")` gates the tenant-config submit control. `CLEANER`/`TECHNICIAN`/`SUPER_ADMIN` get `[]` for both, consistent with every other entry in that map — they never reach this screen (D3), so this is documentation, not live gating.

Rejected: a bespoke `useCanManageTenant()` hook local to this feature — every other tenant-owner-vs-manager split in this codebase (`incident-triage-web`'s `MANAGE_INCIDENTS`, `messaging-ai`'s `MANAGE_CONVERSATIONS`) goes through this one shared, partial mirror; a second mechanism would fork the pattern the very next reader has to learn.

### D3 — No new route-level gating; a regression test pins the existing one

**Chosen:** rely on the existing `(workspace)/layout.tsx` `<AuthGuard allow={["TENANT_OWNER", "PROPERTY_MANAGER"]}>` and `route-registry.ts`'s `profile` split to keep `CLEANER`/`TECHNICIAN`/`SUPER_ADMIN` off `/settings` (R1.4, R6). No production code changes here; `/sdd:tasks` adds a test that a `CLEANER`/`TECHNICIAN` session is redirected from `/settings` (mirroring `auth-guard.test.tsx`'s existing cases) so a future change to the `allow` list cannot silently reopen this screen to them.

Rejected: adding a redundant per-page `allow` check inside the new components — the layout already owns this, and a second check that can drift from the first is worse than one source of truth with a test pinning it.

### D4 — `/settings` is one page, two stacked sections; no new Tabs primitive

**Chosen:** `TenantSettingsView` renders two `<section>`s — "Usuarios" then "Tenant" — stacked vertically (mobile-first: two sections stack cleanly at 400px; tabs would need a new `components/ui/tabs` primitive this codebase does not have yet, for a two-item switch that gains nothing over scrolling). The users section is a table/list (same row shape as other list views in this codebase) with an "add user" button that opens a `Sheet` (reusing the `Sheet` primitive `platform-console.tsx` already uses) hosting `CreateUserForm`; a row's actions open the same `Sheet` hosting either `EditUserForm` (profile/role/status) or a reset-password confirmation, each ending in `TemporaryPasswordReveal` where relevant (create, reset). The tenant section is a single always-visible form, not sheeted (no list of items to pick from).

Rejected: two separate routes (`/settings` and `/settings/users/[id]`) mirroring `reservations`' list+detail split — that pattern exists there because a reservation detail is deep-linked and shareable; a user's edit form here is a short, disposable interaction better matched to the `Sheet` pattern `platform-console.tsx` already established for the same kind of form.

### D5 — Read-only rendering for `PROPERTY_MANAGER` is "hide the controls," not "disable them"

**Chosen:** where `useHasPermission(...)` is `false`, the create/edit/deactivate/reset-password/submit controls are not rendered at all (not rendered-and-disabled). `frontend/steering.md`'s "RBAC del backend decide, el frontend solo oculta" already frames hiding as the contract; a disabled button implies "you could, but not now," which is false here — the manager can never do these regardless of state.

Rejected: rendering disabled controls with a tooltip explaining why — adds copy and a hover state for a permission split that is permanent for this role, not situational.

### D6 — `/settings/integrations` stays exactly as it is today (assumed)

**Chosen:** leave the route, its `RoutePlaceholder`, and its `route-registry.ts` entry untouched. The roadmap note (`sdd/roadmap/tenant-settings-web.md`, point 1) frames this as a design decision with no functional requirement forcing either direction, and explicitly names future webhook-endpoint provisioning as a plausible future occupant of that route. Leaving a placeholder in place is the reversible option — retiring the sidebar entry is easy to undo, but doing nothing is easier still and forecloses nothing. This is recorded as an `assumed` decision for the human to veto at PR time, per `/sdd:auto`'s gate-conversion rule.

Rejected: retiring the route/sidebar entry now — it is not requested by any R# here, and PMS-by-UI is explicitly out of scope (rule 3(a)); removing it is a separate, avoidable decision this change does not need to make.

### D7 — Deactivate calls `DELETE`, reactivate calls `PATCH {status}`; a separate `use-deactivate-user.ts` hook

**Chosen:** the "deactivate" row action calls `DELETE /api/v1/users/{id}` (the endpoint the backend documents for exactly this, with its own audit action) through a dedicated `use-deactivate-user.ts` mutation hook — not folded into `use-update-user.ts`, since it takes no body and its success (`204`) has no updated resource to merge into cache, unlike a `PATCH`. "Reactivate" (shown only on an `INACTIVE`/`SUSPENDED` row) goes through the existing `use-update-user.ts` with `{status: "ACTIVE"}`, the same hook R3.1's profile/role edits use — there is no separate backend verb for it, so no separate frontend one either. Both invalidate the same `tenantSettingsKeys.usersList(tenantId)` key on success.

Rejected: routing deactivation through `PATCH {status: "INACTIVE"}` instead of `DELETE` — the backend gives deactivation its own documented, idempotent endpoint distinct from the generic partial update; calling `PATCH` for it would work (the use case accepts `status` there too) but would abandon the endpoint the backend author evidently intended as the deactivation entry point, and would need its own justification for diverging from `users_router.py`'s own shape.

### D8 — R3.4's "only active cleaner" check reuses the existing list-filter/count, no new endpoint

**Chosen:** when the deactivate action targets a row with `role: "CLEANER"` and `status: "ACTIVE"`, the confirmation flow fires `GET /api/v1/users?role=CLEANER&status=ACTIVE&per_page=1` (a `useQuery` fired on-demand, not on every row render) and reads `total` from the `UserPageResponse` envelope — `per_page=1` keeps the payload to one row since only the count matters. `total === 1` means the target is the tenant's only active cleaner, and the confirmation dialog shows the non-blocking warning from R3.4 before calling `DELETE`. No new backend endpoint: `user-management`'s existing `GET /api/v1/users` filter contract (role + status, AND'd) already answers this question; the frontend has not needed an aggregate count before, so this is the first caller of `total` as a value rather than pagination metadata, and design.md's `Changes by area` gets a dedicated hook for it (`use-active-cleaner-count.ts`) rather than folding it into `use-users.ts`, since its query key and purpose (a scalar check, not a list to render) differ from the main directory list.

Rejected: deriving the count from the already-fetched `user-list` page client-side — the visible page may be filtered/sorted differently (R1.2) or not include every cleaner (pagination), so counting rows already in memory would under- or over-count; a dedicated, minimal query is the only way to get the true tenant-wide count. Rejected: adding a backend aggregate endpoint — the existing filter+`total` already answers this without a new contract.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Permissions | `frontend/lib/auth/permissions.ts` | Add `MANAGE_USERS`, `MANAGE_TENANT_SETTINGS` to `Permission` and to `ROLE_UI_PERMISSIONS.TENANT_OWNER` |
| Platform (existing) | `frontend/features/platform/index.ts` | Export `TemporaryPasswordReveal` |
| New feature | `frontend/features/tenant-settings/dto.ts` | `UserDto`, `UserListDto`, `CreatedUserDto`, `TenantConfigDto`, `TenantDto`, `CreateUserInput`, `UpdateUserInput`, `UpdateTenantInput` |
| New feature | `frontend/features/tenant-settings/data/http/http-tenant-settings-source.ts` | Maps `UserResponse`/`UserPageResponse`/`TenantResponse`/`CreatedUserResponse` ↔ DTOs; calls the 8 endpoints from R1–R5 |
| New feature | `frontend/features/tenant-settings/data/index.ts` | Composition point: `getTenantSettingsDataSource()` |
| New feature | `frontend/features/tenant-settings/hooks/query-keys.ts` | `tenantSettingsKeys` on `tenantScopedKey` (`users-list`, `user-detail`, `tenant-detail`) |
| New feature | `frontend/features/tenant-settings/hooks/use-users.ts`, `use-user.ts`, `use-create-user.ts`, `use-update-user.ts`, `use-deactivate-user.ts`, `use-reset-password.ts`, `use-active-cleaner-count.ts` | R1–R4: query/mutation hooks, `useTenantId()` local helper (mirrors `reservations`); `use-deactivate-user.ts` calls `DELETE` (D7), `use-active-cleaner-count.ts` backs the R3.4 warning (D8) |
| New feature | `frontend/features/tenant-settings/hooks/use-tenant.ts`, `use-update-tenant.ts` | R5 |
| New feature | `frontend/features/tenant-settings/components/list/user-list.tsx`, `user-row-actions.tsx` | R1, R3, R4 |
| New feature | `frontend/features/tenant-settings/components/detail/create-user-form.tsx`, `edit-user-form.tsx`, `reset-password-confirm.tsx` | R2, R3, R4 |
| New feature | `frontend/features/tenant-settings/components/tenant-config-form.tsx` | R5 |
| New feature | `frontend/features/tenant-settings/components/tenant-settings-view.tsx` | D4 composition (two sections, `Sheet` host) |
| New feature | `frontend/features/tenant-settings/lib/validate-tenant-config.ts` | R5.3 client-side range validation mirroring backend ranges |
| New feature | `frontend/features/tenant-settings/index.ts` | Barrel |
| Locales | `frontend/locales/{es,en}/tenant-settings.json`, registered in `frontend/lib/i18n/resources.ts` | New `tenant-settings` i18n namespace; `UserRole`/`UserStatus` label coverage test (mirrors `reservations-locale.test.ts`) |
| Route wiring | `frontend/app/(workspace)/settings/page.tsx` | Replace `RoutePlaceholder` with `TenantSettingsView` |
| Spec | `sdd/specs/tenant-settings-web.md` | New, written at archive |
| Spec | `sdd/specs/user-management.md` | Update the "no frontend yet" lines (18-19, 287) |

## Data & interfaces

No backend/schema changes. Existing OpenAPI schemas consumed as-is: `UserPageResponse`, `UserResponse`, `CreatedUserResponse`, `CreateUserRequest`, `UpdateUserRequest`, `TenantResponse`, `UpdateTenantRequest`, `TenantConfigPatch`, plus `DELETE /api/v1/users/{user_id}` (no request/response body beyond `204`) for deactivation (D7). `GET /api/v1/users?role=CLEANER&status=ACTIVE&per_page=1` (D8) uses the existing `UserPageResponse.total` field as a count, not its usual pagination role.

Note for R5.3: `owner_approval_threshold_eur`/`ai_confidence_threshold` are typed `number | string` in the generated types (`Numeric` serialized as a decimal string is legal JSON on the wire) — the form must send a string with the exact decimal precision the backend expects rather than a JS `number`, the same way any other `Numeric` field in this codebase is handled; there is no code implementing that yet, so the implementer confirms the convention wherever a `Numeric` currently round-trips through the frontend (e.g. `properties`/`reservations` if either handles a `Numeric`, else this is the first such field and sets the pattern with a comment explaining why).

## Risks & mitigations

- **Concurrent edits to the same user/tenant** (two admins in two tabs): the backend's optimistic behavior (per-field `PATCH`, only-if-present) already prevents a full-object clobber; the UI mitigates further by invalidating the relevant query key on every successful mutation (React Query's normal contract), so a stale list is refreshed on next focus rather than requiring a new mechanism.
- **Client-side range validation drifting from the backend's** (R5.3): the ranges are duplicated by necessity (client validates before round-trip); `mapFieldErrors` remains the source of truth for what the backend actually rejected, so a drifted client check fails softer (an extra round trip with a clear `422` message) rather than silently accepting something the backend would refuse.
- **The last-owner / self-demotion 422s (R3.2) reaching the user as a raw error**: `mapFieldErrors`'s existing `fallbackField`-less path already surfaces the backend's message text for non-loc'd 4xxs; this change confirms (via test) that message is legible rather than a generic "something went wrong."

## Open questions

None — `/settings/integrations`'s disposition is closed as D6 (assumed, flagged for the human to veto at PR per the roadmap note's own framing).
