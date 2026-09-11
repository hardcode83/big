# Design: properties-create-web

## Context

`frontend/features/properties` today only lists (`HttpPropertiesSource.listProperties`,
`useProperties`, `PropertiesView`); it has no `POST`/`PATCH` call, no mutation hook, and no
DTO beyond the trimmed `PropertySummaryDto` (`PropertyListItemResponse`, which structurally
omits the three notes and the wifi password, per exception 6 of rule 11).

The property **detail** screen at `/properties/[id]` is not owned by this feature at all —
`frontend/app/(workspace)/properties/[id]/page.tsx` renders `PropertyDetailView` from
`@/features/dashboard`, which fetches `usePropertyDetail` →
`GET /api/v1/properties/{id}/dashboard` (a cross-domain aggregate: `PropertyDetail`,
`dashboard/data/dto.ts`) — a different endpoint and a different, narrower shape than
`PropertyResponse` (no address, timezone, notes, or wifi fields). This matters directly:
editing needs the full resource, which nothing in the tree fetches today.

Backend (`properties-crud`, archived, unchanged by this proposal):
`backend/app/properties/api/router.py` serves `POST /api/v1/properties` (`ManageDep` →
`MANAGE_PROPERTIES`) and `PATCH /api/v1/properties/{id}` (same permission), both against
`CreatePropertyRequest`/`UpdatePropertyRequest` (`schemas.py`). Two duplicate-key conditions
answer `409` with a plain message and no `loc`
(`backend/app/properties/infrastructure/repositories.py:551-558`): `"A property with that
internal_code already exists for this tenant"` and `"Another property of this tenant already
claims that pms_external_id"`.

Two existing precedents this design leans on directly: `CreateTenantForm` /
`PlatformConsole` (`features/platform`) for the no-form-library, `Sheet`-hosted creation
pattern, and `useResolveIncident` (`features/incidents/hooks/use-resolve-incident.ts`) for
invalidating another feature's cache keys **by reproducing their shape**, never by importing
the other feature's key factory (an established rule, not new here).

## Decisions

### D1 — No form library; hand-rolled controlled inputs

**Chosen:** Plain `useState` per field + a local validation function, matching
`CreateTenantForm`/`ConversationReplyForm`. Neither `react-hook-form` nor `zod` is a
dependency of `frontend/package.json`, and every existing form in this tree (platform,
conversations) already uses this convention.

Rejected: introducing `react-hook-form`/`zod` — a new pattern and a new dependency for a
project that has solved this problem twice already without one.

### D2 — Two entry points, both `Sheet` overlays, no dedicated `/properties/new` route

**Chosen:** "New property" on `/properties` and "Edit"/"Retire" on the detail view each open
a `Sheet` (shadcn, already used by `PlatformConsole`), not a new route. `/properties/[id]`
already exists and is the destination after creation (R1.4); a full-page `/properties/new`
would need its own route, layout metadata and back-navigation for a single form, none of
which the proposal asks for.

Rejected: a dedicated `/properties/new` page — more wiring for no requirement it satisfies;
the field count (~18) doesn't change that, the `Sheet` scrolls internally like the rest of
this tree's overlays already do on narrow viewports.

### D3 — Two separate form components, not one parameterized by mode

**Chosen:** `CreatePropertyForm` and `EditPropertyForm`, both in
`features/properties/components/form/`, sharing a presentational `PropertyFieldset` for the
~15 fields both forms collect. Mirrors `CreateTenantForm`/`CreateUserForm` (platform): two
components, not one switched by a `mode` prop — the two flows differ enough (pre-fill +
dirty-tracking + PATCH diffing in edit, none of that in create; a retire action only in edit)
that a shared component would carry more branching than the two field-list definitions it
would save.

Rejected: one `PropertyForm` component switched by `mode: "create" | "edit"` — the
create/edit branching (D8's diffing, R2.4's clear-on-nullable, R2.5's write-only password)
would live inside one component instead of being visible in `EditPropertyForm`'s own logic.

### D4 — `PropertyFieldset`: shared presentational field list, no shared submit logic

**Chosen:** One component rendering the ~15 labeled inputs (name, internal_code,
pms_external_id, address block, country, timezone, capacity trio, check-in/out times, wifi
name/password, three notes), receiving `values`, `onChange` and `fieldErrors` as props. Owns
none of the submit/validation/mutation wiring — that stays in each form component, per D3.
`pms_provider` and `status`/`current_operational_state` are never in this fieldset (R1.2,
R2.3): the create flow doesn't offer them and the edit flow can't.

### D5 — Client-side bounds mirror the backend's, declared once, locally

**Chosen:** `features/properties/lib/field-limits.ts` exports the same constants
`backend/app/properties/api/schemas.py:41-52` declares (`MAX_NAME=200`,
`MAX_INTERNAL_CODE=50`, `MAX_PMS_EXTERNAL_ID=200`, `MAX_ADDRESS=200`, `MAX_CITY=100`,
`MAX_PROVINCE=100`, `MAX_POSTAL_CODE=20`, `MAX_WIFI_NAME=200`, `MAX_NOTES=5000`,
`MAX_WIFI_PASSWORD=200`, `MAX_GUESTS=50`, `MAX_ROOMS=50`), each with a comment pointing at the
schema line it mirrors, plus a `validatePropertyFields` function `PropertyFieldset`'s two
callers run before calling their mutation (R1.3). `maxLength` is also set on each `<input>`/
`<textarea>` directly, same as `CreateTenantForm`'s `maxLength={2}` on `country`.

Rejected: deriving bounds from the generated OpenAPI types at runtime — the JSON Schema
constraints (`maxLength`, `minimum`/`maximum`) exist in `backend/openapi.json`, but
`openapi-typescript` erases them into plain TS types (`string`, `number`) with no runtime
value to read; consuming them would mean fetching and parsing the raw JSON Schema
client-side, a much bigger change for a handful of integer constants. This introduces the
same "two copies" risk `rule11-ownership.py` exists to guard against for the backend's own
prose — accepted here, flagged in Risks, because the numbers are stable (unchanged since
`properties-crud`, 2026-08-08) and a mismatch fails safe: a stale, too-generous frontend bound
still gets caught by the backend's real `422`, it just skips the earlier, friendlier check.

### D6 — 409 field attribution by message substring, not `loc`

**Chosen:** `mapPropertyFieldErrors(error)` in `features/properties/lib/field-errors.ts`
(new file, sibling to the existing `error-mapping.ts`, which maps query results and is not
touched): for a `422`, same `loc`-keyed reading `platform`'s `mapFieldErrors` already does;
for a `409`, inspect `error.message` for the substring `"internal_code"` vs.
`"pms_external_id"` and attribute to that field. This is necessary, not a shortcut: verified
against `backend/app/properties/infrastructure/repositories.py:551-558`, both duplicate
paths raise with a plain string and `error_envelope(code, message)` is called with no
`details` (`app/properties/api/errors.py:59-63`), so `error.details` is always `{}` for these
— there is no `loc` to read, unlike platform's `422` branch.

Rejected: a single hardcoded `fallbackField` per call site (platform's `409` convention) —
platform only ever has one possible conflicting field (`name`); this endpoint has two, and a
fixed fallback would blame the wrong one half the time.

Risk (see Risks & mitigations): coupled to exact backend wording. Mitigated with a unit test
pinning both exact strings, so a backend wording change breaks this test loudly instead of
silently misrouting the error.

### D7 — A new full-detail fetch, independent of the dashboard aggregate

**Chosen:** `HttpPropertiesSource.getProperty(tenantId, id)` calls
`GET /api/v1/properties/{property_id}` and maps the full `PropertyResponse` (never
`PropertyListItemResponse`) to a new `PropertyDetailDto` in `features/properties/data/dto.ts`
— the same shape `PropertySummaryDto` has, minus the fields the list omits, plus the three
notes, `hasWifiPassword`, `pmsProvider`/`pmsExternalId`, wifi name. A new hook,
`useProperty(id)`, keyed `propertiesKeys.detail(tenantId, id)`. `EditPropertyForm` calls this
hook itself (it needs the fields `dashboard`'s aggregate doesn't carry) rather than receiving
data as a prop from `PropertyDetailView` — the two queries target different endpoints and
must not be conflated into one shape.

Rejected: reusing/extending `dashboard`'s `PropertyDetail`/`usePropertyDetail` — that DTO and
endpoint belong to `dashboard-api` (a cross-domain read aggregate: cards, timeline,
stalls-adjacent data), and widening it to also carry every writable field of `Property` would
turn a purpose-built read model into a second, informal copy of `PropertyResponse`.

### D8 — `PATCH` sends only touched fields; explicit-clear is a distinct action from "left blank"

**Chosen:** `EditPropertyForm` seeds local state from `useProperty(id)`'s result and keeps
the initial snapshot alongside the live values. On submit it builds the body by comparing
each field's current value to its initial value and including only the ones that changed —
mirroring the discipline `UpdatePropertyRequest._reject_explicit_nulls` enforces server-side
(`model_fields_set` vs. `None`). For a nullable field (`pms_external_id`, address fields,
`wifi_name`, the three notes): if the user clears a previously non-empty value, the body gets
`field: null`; if it was already empty and stays empty, the field is omitted entirely — never
sent as `null` for "untouched" (R2.4). Non-nullable fields (`name`, `internal_code`,
`country`, `timezone`, guest/room counts, check-in/out times) can never produce a `null` in
the body; `validatePropertyFields` (D5) rejects an emptied required field before submit
rather than letting the backend's `422` on an unmapped `null` be the first signal.

`wifi_password` gets its own rule (R2.5, R3.2): the input never receives the stored value
(the API never returns it) and starts blank meaning "unchanged". A second, explicit "clear
stored password" checkbox is the only way to send `wifi_password: null` — required because
`wifi_password` IS in `NULLABLE_FIELDS`, so "blank" is ambiguous between "leave as is" and
"remove it" and the UI must not guess. Typing a new value sends that value; leaving both the
field and the checkbox untouched omits `wifi_password` from the body entirely.

Rejected: sending the full form state on every save and letting the backend's allowlist
(`PATCHABLE_PROPERTY_FIELDS`) silently drop what it doesn't recognize — `changes()`
(`schemas.py`) already treats "sent" vs. "not sent" as meaningful via `model_fields_set`, so a
client that always sends everything would turn every save into an unconditional overwrite of
every nullable field, defeating that distinction and risking clobbering a value another
session set concurrently (however unlikely for this resource).

### D9 — Retiring a property is a separate, confirmed action, not a checkbox in the edit form

**Chosen:** A "Retire property" button on the detail view (visible only to
`MANAGE_PROPERTIES`, and only for a property whose `status` is not already `INACTIVE`) opens
`AlertDialog` (shadcn, already in `components/ui/alert-dialog.tsx`) with an explicit confirm
step, then calls the same `useUpdateProperty` mutation with a body of exactly
`{ status: "INACTIVE" }` — nothing else, even if the edit form has unsaved changes. This
matches R2.6 ("acción distinta y explícitamente confirmada, separada del guardado general")
and the irreversibility called out there (no `DELETE`, no un-retire path in scope).

Rejected: a `status` select inside the general edit form — the proposal explicitly asks for
retirement to be its own confirmed step, not a value silently included in a broader save.

### D10 — Cache invalidation reproduces `dashboard`'s key shape by hand, same as `useResolveIncident`

**Chosen:** Both `useCreateProperty` and `useUpdateProperty` (`retry: false`, no optimistic
writes, same skeleton as `useCreateCleaningTask`) invalidate, in `onSettled`:

- `propertiesKeys.list(tenantId)` prefix (this feature's own list cache) — a create changes
  `total`/`total_pages`; an update changes any of the six columns the list table renders.
- `propertiesKeys.detail(tenantId, id)` (update only) — so a re-opened edit form or a
  revisited detail-adjacent read sees the just-saved values.
- The `dashboard` feature's tenant-scoped prefixes `["tenant", tenantId, "dashboard-cards"]`
  and, for update, `["tenant", tenantId, "property-detail", id]` — reproduced by hand, exactly
  as `useResolveIncident` already does for the same two prefixes, and for the same reason:
  `features/properties` cannot import `dashboardKeys` (design boundary these two files already
  established), and a create adds a card while an edit can change what that card and the
  aggregate detail show (name, city, status).

Rejected: leaving the dashboard's caches alone and letting them go stale until their own
natural refetch — unlike the platform tenant-creation flow (which explicitly defers to a
later natural refresh, R3.2 of that change), nothing in this proposal asks for that
staleness window, and the property name/status is exactly what the dashboard card exists to
show.

### D11 — Navigation on create success uses Next.js `useRouter`

**Chosen:** `CreatePropertyForm` calls `router.push(\`/properties/${created.id}\`)` from
`next/navigation` on `201`, closing the Sheet as part of the navigation (the Sheet is scoped
to `/properties`, so leaving the route unmounts it). Matches R1.4 and the existing
`Link href={\`/properties/${property.id}\`}\`` pattern in `PropertyRow`/`NameLink`.

### D12 — Permission gating with the existing `useHasPermission` hook, extending its permission mirror

**Chosen:** `useHasPermission("MANAGE_PROPERTIES")` (`@/lib/auth`) gates: the "New property"
button in `PropertiesView`, and the "Edit"/"Retire" buttons added to the detail view. Same
hook, same pattern as `blocked-transitions-section.tsx` (`useHasPermission("MANAGE_CLEANING_TASKS")`)
and `guest-portal-link-card.tsx`. RBAC itself is enforced by the backend
(`ManageDep`); this only hides the affordance (R1.1, R2.1 — `steering/frontend.md`: "RBAC del
backend decide, el frontend solo oculta").

`frontend/lib/auth/permissions.ts` declares `Permission` as a **closed union** — today
`"MANAGE_CLEANING_TASKS" | "MANAGE_PRICE_RECOMMENDATIONS" | "EXECUTE_INCIDENTS" |
"MANAGE_CONVERSATIONS" | "MANAGE_INCIDENTS" | "RESPOND_OWNER_APPROVALS" |
"MANAGE_GUEST_ACCESS_TOKENS"` — and does not carry `MANAGE_PROPERTIES` yet, so this change
must extend it, the same way every permission-gated feature before it did (its own docstring
records `blocked-transitions-web`, `messaging-ai`, `incident-triage-web`, `approvals-web` and
`guest-link-delivery` each adding their own entry). This change adds `"MANAGE_PROPERTIES"` to
the union and to `ROLE_UI_PERMISSIONS.PROPERTY_MANAGER` only — mirroring the backend's
`_PROPERTY_MANAGE` (`policy.py:214`, granted only inside `PROPERTY_MANAGER`'s bundle,
`policy.py:398`); `TENANT_OWNER` keeps `_PROPERTY_READ` only (read-only, matching the roadmap
note and R1/R2's "Para `MANAGE_PROPERTIES` (manager; el owner es lectura)") and is correctly
absent from this entry, same split already used for `MANAGE_CONVERSATIONS` and
`MANAGE_INCIDENTS`.

### D13 — Locale keys land in the existing `properties` namespace; `Edit`/`Retire` copy lives with `dashboard`

**Chosen:** `CreatePropertyForm`/`PropertyFieldset`/the "new property" action's copy goes in
`frontend/locales/{es,en}/properties.json` (existing namespace). The "Edit"/"Retire" button
copy and confirmation dialog on the detail view goes in `frontend/locales/{es,en}/dashboard.json`,
since that view already reads the `dashboard` namespace exclusively
(`property-detail-view.tsx`, `property-detail-sections.tsx`) and mixing two `useTranslation`
namespaces into one screen for two new buttons isn't worth it. `EditPropertyForm`, even
though it lives in `features/properties`, reads `useTranslation("properties")` for its field
labels (shared with `PropertyFieldset`) and the *hosting* detail view supplies the
dialog/button copy from `dashboard` — same split `properties-view.tsx` already uses today
(`useTranslation("properties")` plus a second `useTranslation("dashboard")` for the state
badge label).

### D14 — `access_notes` inline guidance text (R3.1)

**Chosen:** A short helper string under the `access_notes` field in `PropertyFieldset`
(both forms), sourced from `properties.json`, stating it is guest-facing and is not where a
door/lock code goes. Presentational only — no behavior change, and it does not touch
`AccessRecord` or any other entity.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Data / DTOs | `features/properties/data/dto.ts` | Add `PropertyDetailDto`, `CreatePropertyInput`, `UpdatePropertyInput` (camelCase command shapes) |
| Data / HTTP source | `features/properties/data/http/http-properties-source.ts` | Add `getProperty`, `createProperty`, `updateProperty` methods and their request/response mapping |
| Hooks | `features/properties/hooks/use-property.ts` (new) | `useProperty(id)` query, mirrors `use-properties.ts` |
| Hooks | `features/properties/hooks/use-create-property.ts` (new) | `useCreateProperty` mutation (D10) |
| Hooks | `features/properties/hooks/use-update-property.ts` (new) | `useUpdateProperty` mutation (D10) |
| Hooks | `features/properties/hooks/query-keys.ts` | Add `propertiesKeys.detail(tenantId, id)` |
| Lib | `features/properties/lib/field-limits.ts` (new) | Bound constants mirroring `schemas.py` (D5) |
| Lib | `features/properties/lib/field-validation.ts` (new) | `validatePropertyFields` (D5) |
| Lib | `features/properties/lib/field-errors.ts` (new) | `mapPropertyFieldErrors` (D6) |
| Components | `features/properties/components/form/property-fieldset.tsx` (new) | Shared field list (D4) |
| Components | `features/properties/components/form/create-property-form.tsx` (new) | Create flow (D3, D11) |
| Components | `features/properties/components/form/edit-property-form.tsx` (new) | Edit flow, diffing (D3, D8) |
| Components | `features/properties/components/list/properties-view.tsx` | Add "New property" button + `Sheet` hosting `CreatePropertyForm`, gated by D12 |
| Components | `features/properties/index.ts` | Export `EditPropertyForm` (and its input type) for cross-feature import (D3, mirrors how `dashboard` already imports from `incidents`/`cleaning`) |
| Components (dashboard) | `features/dashboard/components/detail/property-detail-view.tsx` | Add "Edit"/"Retire" buttons (gated, D12), `Sheet` hosting `EditPropertyForm`, `AlertDialog` for retire (D9) |
| Auth | `frontend/lib/auth/permissions.ts` | Add `"MANAGE_PROPERTIES"` to the `Permission` union and to `ROLE_UI_PERMISSIONS.PROPERTY_MANAGER` only (D12) |
| Locales | `frontend/locales/{es,en}/properties.json` | New keys: form fields, validation messages, create success/errors, access-notes guidance (D14) |
| Locales | `frontend/locales/{es,en}/dashboard.json` | New keys: edit/retire buttons, retire confirmation copy |

## Data & interfaces

No backend or schema changes — `POST`/`PATCH /api/v1/properties[/{id}]` and their request/
response contracts are unchanged, already archived under `properties-crud`. New frontend-only
types:

```ts
// features/properties/data/dto.ts
export interface PropertyDetailDto extends PropertySummaryDto {
  addressLine1: string | null;
  // ...address_line2, notes fields, already partly on PropertySummaryDto — see D7
}

export interface CreatePropertyInput { /* camelCase mirror of CreatePropertyRequest, minus pms_provider/status */ }
export interface UpdatePropertyInput { /* Partial<...>, only the touched subset (D8) */ }
```

`Env`/config: none.

## Risks & mitigations

- **D5's duplicated bounds constants can drift from `schemas.py`.** Mitigated: each constant
  comments the exact backend line it mirrors, and a mismatch fails safe (a stale, larger
  client bound still gets the real `422`). No test can catch a silent backend bound *decrease*
  short of contract testing, which is out of scope for a UI-only change.
- **D6's `409` field attribution reads a message string, not a structured field.** Mitigated
  with a unit test pinning both exact backend strings (`"internal_code already exists"` /
  `"claims that pms_external_id"`); if `repositories.py:551-558` ever rewords either message,
  this test fails loudly instead of the UI silently blaming the wrong field.
- **A second writer of `access_notes`/`cleaning_notes`/`emergency_notes` (this form) inherits
  the audit-redaction gap `security.md`'s sink-census row for `access_notes` already documents**
  ("un segundo escritor de esta columna que construya su propio `ChangeSet` se salta la
  redacción sin que nada se ponga rojo"). This form does not construct its own `ChangeSet` — it
  only calls the existing `PATCH`/`POST` endpoints, whose one `ChangeSet` call site is
  unchanged — so it does not add a second *backend* writer and does not widen that gap. Noted
  here so the next reader doesn't have to re-derive it.
- **Cross-feature invalidation (D10) duplicates key-shape knowledge in two files.** Accepted:
  same tradeoff `useResolveIncident`/`useCancelCleaningTask` already made, for the same reason
  (no import path between the two features' key factories).

## Open questions

None. Every choice above is either dictated by an existing, singular precedent in this
codebase (D1, D3, D6's shape, D9, D10, D12) or has no requirement-level alternative worth
raising to the human (D2, D4, D5, D7, D8, D11, D13, D14) — none of it touches a requirement,
security posture, or irreversible action beyond what R2.6 already specifies.
