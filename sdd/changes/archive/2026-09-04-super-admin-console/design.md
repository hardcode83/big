# Design: super-admin-console

## Context

`SUPER_ADMIN` is authenticated end-to-end (`super-admin-identity`) and has exactly two
backend routes to call (`platform-admin-api`): `POST /api/v1/platform/tenants` and
`POST /api/v1/platform/tenants/{tenant_id}/users`, both gated by `Permission.MANAGE_PLATFORM`
and declared in `backend/app/platform/api/{router,schemas,dependencies,errors}.py`. Neither
route has a frontend caller. `frontend/features/auth/lib/role-home.ts` maps four roles to a
shell and falls back to `/dashboard` for anything else; `frontend/features/auth/components/
auth-guard.tsx` is a UX-only role gate already generic over `allow?: readonly UserRole[]`;
`(workspace)`, `(field)/cleaner`, `(field)/tech` and `(authenticated)` are the four existing
route groups, each pairing a layout (`AuthGuard` + a shell) with real pages. No frontend
"list tenants" endpoint exists yet — `TenantRepository` (`backend/app/tenants/domain/
repositories.py`) has `get`/`apply_changes`/`add` and explicitly no `list`, by a comment
that says listing was out of scope until now.

## Decisions

### D1 — A new route group and shell profile, not a repurposed one

**Chosen:** a new route group `app/(platform)/`, with `app/(platform)/layout.tsx` mounting
`AuthGuard allow={["SUPER_ADMIN"]}` around a bare `ShellFrame` (topbar only: `Brand` +
`UserMenu`, no sidebar, no bottom navigation, no footer — same composition
`(authenticated)/layout.tsx` uses for `/welcome`), and `app/(platform)/platform/page.tsx` for
the single console screen at `/platform`. `route-registry.ts` gets a new `ShellProfile`
value `"platform"` and one descriptor (`id: "platform"`, `pattern: "/platform"`, `profile:
"platform"`, no `navigationGroup` — nothing else links to it, the same treatment `welcome`
gets). `route-coverage.test.ts`'s `REAL_PAGE_ROUTE_IDS` map gets
`"(platform)/platform/page.tsx": "platform"`. `role-home.ts` gets `SUPER_ADMIN: "/platform"`
in `ROLE_HOME` — R1.2 (redirect after login with no `?returnTo=`) is then free: `LoginForm`
already resolves any non-`CLEANER`/`TECHNICIAN` role straight through `roleHome(role)`
(`frontend/features/auth/components/login-form.tsx:66`), no change needed there.

Why a new group and not `(authenticated)`: `(authenticated)/layout.tsx` wraps its `AuthGuard`
with **no** `allow` (any authenticated role passes, by design — it exists so a `CLEANER`/
`TECHNICIAN` mid-transition keeps a working `UserMenu`). Mounting `/platform` under it would
let every other role open the URL and see `RoutePlaceholder`-free real content before the
guard's redirect effect fires. R1.5 ("deny it to any other role with the same bounce
criterion as other protected groups") requires an explicit `allow={["SUPER_ADMIN"]}`, which
means its own group.

Rejected: reusing `(workspace)/layout.tsx` and adding `SUPER_ADMIN` to its `allow` array —
mounts `WorkspaceShell` (tenant selector, tenant-scoped nav) for a role with no tenant,
directly violating R1.4.

### D2 — `GET /api/v1/platform/tenants`: new repository method, new use case, shared response shape

**Chosen:** add `TenantRepository.list_page(page: int, per_page: int) -> tuple[Sequence[tuple[Tenant, TenantConfig]], int]`
to the port (`backend/app/tenants/domain/repositories.py`) and its SQLAlchemy implementation
(`backend/app/tenants/infrastructure/repositories.py`), ordered by `created_at DESC` with no
filter (R2.2 — there is exactly one tenant scope here: none, every tenant is platform-visible
to `SUPER_ADMIN`). The pair (not a bare `Tenant`) is what makes the very next paragraph's "no
`get_or_create` defaulting needed" true — a domain port cannot return the application layer's
`TenantSettings` (`tests/test_layering.py` forbids `domain/` importing `application/`), so the
pairing is a plain tuple; `ListTenantsUseCase` (below) is what wraps each pair into one.
`SqlAlchemyTenantRepository.list_page` also guards the join with `require_unmarked_session`
(`app/core/db.py`): `tenant_configs` carries a `tenant_id` column, unlike `tenants` itself, so
a marked session would otherwise silently narrow that side of the join instead of raising
(corrected 2026-09-04, section-1 review panel). A new `ListTenantsUseCase` in `backend/app/platform/application/
use_cases.py` calls it directly — no business rule to enforce, so the use case is a thin
pass-through like `ListConversationsUseCase` (`app/messaging/application/use_cases.py:836`).
The route lives in `backend/app/platform/api/router.py` (third route on the existing
`PlatformDep`-gated router), wired through a new `get_list_tenants_use_case` in
`use_case_dependencies.py`.

Response shape: `TenantPageResponse` in `backend/app/platform/api/schemas.py` — `items:
list[TenantResponse]`, `total`, `page`, `per_page`, `total_pages`, a `.build(...)` classmethod
computing `total_pages` — the same shape `IncidentPageResponse`, `ConversationPageResponse`,
`CleaningTaskPageResponse` etc. already use (proposal's explicit ask: "misma forma que el
resto de listados"), and **not** the older `{data, total, page, per_page, total_pages}`
envelope `user-management`'s `GET /api/v1/users` uses — that shape predates the `items`
convention and is not what newer modules follow. `items` reuses `TenantResponse` verbatim
(R2.4) via the existing `TenantResponse.from_settings`-adjacent per-row mapping (a tenant with
no `TenantConfig` row cannot exist by construction — `TenantRepository.add` always writes
both — so no `get_or_create` defaulting is needed for the listing). Pagination bounds are
declared locally in `app/platform/api/schemas.py` as `MAX_PER_PAGE = 100` / `MAX_PAGE =
100_000`, matching the per-module (not centralized) constant that `messaging`, `cleaning` and
`maintenance` each already redeclare — there is no shared constant to import.

Rejected: reusing `user-management`'s `{data, ...}` envelope for consistency with the other
tenant-adjacent endpoint — the proposal explicitly asks for the `items` shape, and it is the
majority convention across modules shipped after `user-management`.

Rejected: filtering/sorting parameters on the route — out of scope (proposal's "Out of
scope": no filter/search beyond simple pagination).

### D3 — Frontend feature module `features/platform/`, following the hexagonal precedent

**Chosen:** `features/platform/{dto.ts, data/http/http-platform-source.ts, data/index.ts,
hooks/{query-keys.ts, use-tenants.ts, use-create-tenant.ts, use-create-platform-user.ts},
components/, lib/field-errors.ts, index.ts}` — the same shape `features/conversations` and
`features/properties` use: a DTO layer in camelCase, one HTTP source class constructed with
the typed `ApiClient`, one composition point (`getPlatformDataSource()`) via
`createAuthenticatedClients`, TanStack Query hooks that depend only on the composition point.
No mock source and no `PlatformDataSource` interface — same reasoning `conversations` D1
gives: nothing pre-existing depended on a mock, and the backend already exists.

### D4 — Query keys: a platform-scoped convention, deliberately not `tenantScopedKey`

**Chosen:** `features/platform/hooks/query-keys.ts` exports `platformKeys.tenantsList(page,
per_page) => ["platform", "tenants-list", page, per_page]` — a small, separate convention,
**not** built on `lib/query/query-keys.ts`'s `tenantScopedKey`. That helper's own contract
throws on an empty `tenantId`, and `SUPER_ADMIN` has none (`super-admin-identity`) — the
platform surface is the first caller for whom "no tenant" is the correct, not an error,
state. Documented inline so a future reader does not "fix" the omission by threading a fake
tenant id through it.

Rejected: extending `tenantScopedKey` to accept `tenantId: string | null` — would relax the
non-empty invariant for every existing tenant-scoped caller to accommodate one exception.

### D5 — Field-level errors from `422`/`409`: a new mapping, scoped to this feature

**Chosen:** every other feature's error mapper (`mapConversationsError`, `mapPropertiesError`,
`replyErrorKey`) deliberately never reads the backend's `422` envelope body — R3.3/R4.5 ask
for exactly that here ("mostrar el error por campo que la API devuelve, sin inventar un
mensaje genérico"), so this is a genuinely new pattern, not a reuse of an existing one.
`features/platform/lib/field-errors.ts` exports `mapFieldErrors(error: unknown):
Record<string, string>`:

- `422`: reads `error.details.errors` (the shape `_serialisable_validation_errors` in
  `backend/app/core/errors.py` produces: `{loc: string[], type, msg}[]`), keys the result by
  `loc`'s last segment (the field name — `loc` is `["body", "<field>"]` for a body validator),
  value is `msg`.
- `409`: the envelope carries one message with no `loc` at all (`TenantAlreadyExistsError`,
  `EmailAlreadyExistsError`) — the field it concerns is hardcoded per call site, because nothing
  in the response names it: the create-tenant form attributes it to `name`, the create-user
  form to `email`. This is the only place a field is inferred rather than read.
- Anything else (`403`, `5xx`, network): not a field error — the caller falls back to the
  existing generic-error copy pattern (a single localized string, same as `replyErrorKey`).

Both forms (D6) call this one function; it is not duplicated per form.

**On i18n (resolved at the section-5 gate, 2026-09-04):** the field-error `msg`/`message`
strings this function surfaces are the backend's own text, verbatim, in English
(`steering/backend.md`: "Mensajes de sistema, logs y errores técnicos en inglés") — not routed
through `locales/`. This is a deliberate, narrower exception to `steering/frontend.md`'s general
i18n rule, not an oversight: R3.3/R4.5 explicitly ask for "el error por campo que la API
devuelve, sin inventar un mensaje genérico" (the API's own per-field message, not an invented
generic one), which is incompatible with translating it — a translation would BE the invented
generic message the requirement rejects. Every other feature's mapper stays on the general rule
by showing a single localized string precisely because it never reads the field-specific
message; this feature's whole point, per R3.3/R4.5, is to show that message. Localizing the
backend's own error catalogue (so `msg` arrives pre-translated) is the only way to close this
gap, and it is out of scope for this change — it would touch every 422/409 raiser in the
backend, not just the platform surface.

### D6 — Create-tenant → create-user is one screen, chained through component state, no navigation

**Chosen:** `/platform` renders a tenant list (D2's endpoint) plus a "new tenant" action that
opens a `Sheet` (see D8) with the create-tenant form. On `201`, the `Sheet`'s content switches
in place to a success view showing the created tenant and a "add staff" button; that button
switches the same `Sheet` to the create-user form pre-scoped to the just-created tenant's
`id` — R3.2's exact ask ("en la misma vista y sin recargar ni volver a pedir la lista de R2").
The created tenant lives in the mutation caller's local `useState`, not in the TanStack Query
cache: `useCreateTenant`'s mutation does **not** invalidate or refetch `platformKeys
.tenantsList(...)` — R3.2 explicitly forbids re-fetching the list as part of this flow. The
list shows the new tenant only on its next natural refetch (revisit, refocus, or the operator
manually reopening `/platform`), which is an accepted staleness window given the requirement.

From the tenant list itself, each row also carries an "add staff" action opening the same
create-user form pre-scoped to that row's `id` — R4 doesn't say the staff form is reachable
only right after creation, and gating it to that one path would make an existing tenant's
first hire impossible without recreating the tenant.

Rejected: separate routes (`/platform/tenants/new`, `/platform/tenants/[id]/users/new`) —
adds two more `route-registry` entries and two more `route-coverage` rows for a flow the
proposal describes as one continuous screen; a `Sheet` matches "same view" literally.

### D7 — One-time temporary password: new component, in-memory only

**Chosen:** no existing frontend code displays a one-time secret (`user-management`'s spec
says explicitly "Sin frontend"), so `features/platform/components/temporary-password-reveal.tsx`
is new: a read-only monospace field with the password, a copy-to-clipboard button
(`navigator.clipboard.writeText`, no fallback — the same capability every modern
evergreen browser this app targets already has), and a persistent visible warning that it
will not be shown again. The password lives only in the mutation's own response, held in the
form's local `useState` for the duration of the `Sheet`'s open lifetime; it is never written
to `localStorage`, a query string, or router history (R4.4), and the mutation hook itself
never logs it. Closing the `Sheet` drops the state — there is no "show it again" path,
matching the backend's own "exactly once" contract.

### D8 — Reuse `Sheet`, not a new `Dialog` primitive

**Chosen:** `components/ui/sheet.tsx` (Radix `Dialog` under a `side` variant, already used for
the mobile navigation drawer) hosts both forms. The project has no `dialog.tsx`, `input.tsx`,
`label.tsx`, or `select.tsx` shadcn primitives yet — forms elsewhere (`ConversationReplyForm`)
are hand-rolled `<input>`/`<textarea>`/`<button>` with Tailwind classes, no form-library
dependency (no `react-hook-form`, no `zod` in `package.json`). This design follows the same
hand-rolled convention for the two new forms' fields (plain controlled inputs, a native
`<select>` for the R4.2 role picker restricted to the four grantable roles) rather than
introducing a form library or a new component family for one change's two forms.

Rejected: `AlertDialog` (already present) — its semantics are confirm/cancel, not an
arbitrary form host; using it for a multi-field form would be the wrong primitive advertising
the wrong interaction model.

### D9 — i18n namespace `platform`

**Chosen:** `locales/{es,en}/platform.json`, registered in `lib/i18n/resources.ts` next to the
other per-feature namespaces (`conversations`, `properties`, ...). All console strings — list
column headers, both forms' labels/errors, the password-reveal copy, the deny/landing copy —
live there; `auth.json`'s existing keys (`deniedRole`, etc.) are untouched and reused as-is
from `AuthGuard`/`LoginForm` for the redirect path, since D1 does not touch that logic.

### D10 — Pagination: a third `PlatformPagination`, not the generalization

**Chosen (resolved at the gate, 2026-09-04):** `features/platform/components/platform-pagination.tsx`
as a third near-copy of `CleaningPagination`/`PricingPagination`, hardcoding the `"platform"`
i18n namespace exactly as the other two hardcode theirs. `PricingPagination`'s own docstring
flags this as the moment its own comment reserved for generalizing into a namespace-
parameterized shared component — the user chose to keep this change scoped to its own files
instead of also touching `features/cleaning` and `features/pricing`. The extraction remains
available as a future, separately-scoped cleanup once a fourth consumer (or this decision)
makes it worth doing.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Backend — tenants port | `app/tenants/domain/repositories.py`, `app/tenants/infrastructure/repositories.py` | New `TenantRepository.list_page(page, per_page)` + SQL impl, ordered `created_at DESC` |
| Backend — platform use case | `app/platform/application/use_cases.py` | New `ListTenantsUseCase` |
| Backend — platform API | `app/platform/api/router.py`, `app/platform/api/schemas.py`, `app/platform/api/use_case_dependencies.py` | New `GET /platform/tenants`, `TenantPageResponse`, `MAX_PER_PAGE`/`MAX_PAGE`, new dependency builder |
| Backend — tests | `backend/tests/platform/test_api.py`, `test_authorization.py`, `test_isolation.py`, `test_use_cases.py` | New route's happy path, empty-page, pagination bounds, `403` for the other five roles, structural guard reuse |
| Backend — artifacts | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerated (`make openapi` + `npm run api:generate`), committed together |
| Frontend — auth | `features/auth/lib/role-home.ts` | `SUPER_ADMIN: "/platform"` row |
| Frontend — routing | `features/shell/navigation/route-registry.ts`, `app/route-coverage.test.ts` | New `"platform"` `ShellProfile` + descriptor; new `REAL_PAGE_ROUTE_IDS` row |
| Frontend — new route group | `app/(platform)/layout.tsx`, `app/(platform)/platform/page.tsx` | `AuthGuard allow={["SUPER_ADMIN"]}` + bare `ShellFrame`; the console page |
| Frontend — feature module | `features/platform/**` (new) | dto, http source, composition point, hooks, components (incl. `platform-pagination.tsx`), field-error mapper |
| Frontend — i18n | `locales/{es,en}/platform.json`, `lib/i18n/resources.ts` | New namespace, registered |

## Data & interfaces

- New backend route: `GET /api/v1/platform/tenants?page=&per_page=` → `TenantPageResponse`
  (`items: TenantResponse[]`, `total`, `page`, `per_page`, `total_pages`), gated by
  `PlatformDep` (`Permission.MANAGE_PLATFORM`, `SUPER_ADMIN` only), same as the two existing
  platform routes.
- New port method: `TenantRepository.list_page(page: int, per_page: int) -> tuple[Sequence[tuple[Tenant, TenantConfig]], int]`.
- No new database columns, migrations, or events. No new permission — `MANAGE_PLATFORM`
  already exists and already gates this router.
- Frontend: no new env vars; the feature reuses `createAuthenticatedClients` with the
  existing same-origin proxy, same as every other feature module.

## Risks & mitigations

- **`route-coverage.test.ts` and `route-wiring.test.tsx` are structural guards that fail
  loudly on a missed registration** — both need their new row added in the same commit as the
  new page, or the suite catches it immediately (that is their job).
- **Staleness window (D6):** the tenant list can be one create-tenant operation behind until
  the operator revisits `/platform`. Accepted per R3.2's explicit "no refetch" ask; if this
  turns out to surprise operators in practice, the fix is a follow-up (manual refresh button,
  or an invalidate-on-close-without-navigation), not a silent change to this design.
- **`list_page` with no tenant filter is a new kind of query for `TenantRepository`** — every
  existing method is single-row by `tenant_id`. The isolation guard suite
  (`sdd-review-tenancy`) will look at this file; the design's answer is that `tenants` has no
  `tenant_id` column (it IS the tenant, per the port's own existing docstring) and this method
  is authorized exclusively through `PlatformDep`/`MANAGE_PLATFORM`, the same authorization
  boundary the other two platform routes already rely on — no new isolation surface, the
  existing one extended by one read.

## Open questions

None outstanding — the one open question (pagination component generalization vs. a third
copy) was resolved at the gate; see D10.
