# Tasks: properties-create-web

## 1. Permission mirror and shared field-level libraries <!-- panel: PASS 2026-09-11 receipt:5fd35cc7 -->

- [x] 1.1 Add `"MANAGE_PROPERTIES"` to the `Permission` union in
      `frontend/lib/auth/permissions.ts` and to `ROLE_UI_PERMISSIONS.PROPERTY_MANAGER`
      only (not `TENANT_OWNER`), mirroring backend `policy.py`'s `_PROPERTY_MANAGE`
      (design D12). Extend `frontend/lib/auth/permissions.test.ts` (or its
      equivalent) to assert `useHasPermission("MANAGE_PROPERTIES")` is `true` for
      `PROPERTY_MANAGER` and `false` for `TENANT_OWNER`/`CLEANER`/`TECHNICIAN`. [R1.1, R2.1]
- [x] 1.2 Create `frontend/features/properties/lib/field-limits.ts`: export
      `MAX_NAME`, `MAX_INTERNAL_CODE`, `MAX_PMS_EXTERNAL_ID`, `MAX_ADDRESS`,
      `MAX_CITY`, `MAX_PROVINCE`, `MAX_POSTAL_CODE`, `MAX_WIFI_NAME`, `MAX_NOTES`,
      `MAX_WIFI_PASSWORD`, `MAX_GUESTS`, `MAX_ROOMS`, each matching
      `backend/app/properties/api/schemas.py:41-52` with a comment citing the line
      it mirrors (design D5). [R1.3]
- [x] 1.3 Create `frontend/features/properties/lib/field-validation.ts`:
      `validatePropertyFields(values)` returning `Record<string, string>` —
      required-field emptiness (`name`, `internal_code`), length bounds from 1.2,
      `country` exactly 2 uppercase letters, `max_guests` 1-50, `bedrooms`/
      `bathrooms` 0-50. Unit test every bound (one just-inside, one just-outside
      case each). [R1.3]
- [x] 1.4 Create `frontend/features/properties/lib/field-errors.ts`:
      `mapPropertyFieldErrors(error, fallbackField?)` — `422` reads
      `error.details.errors` by `loc` (same shape as
      `features/platform/lib/field-errors.ts`); `409` attributes to
      `internal_code` or `pms_external_id` by matching the exact substrings
      `"internal_code"` / `"pms_external_id"` in `error.message`, per
      `backend/app/properties/infrastructure/repositories.py:551-558` (design D6).
      Unit tests pin both exact backend message strings so a backend wording
      change fails this test loudly. [R1.5, R2.7]
- [x] 1.5 Run `cd frontend && npm run typecheck && npm test -- field-limits
      field-validation field-errors permissions` to confirm section 1 is
      self-consistent before section 2 depends on it.

## 2. Data layer — full-detail fetch and mutations <!-- panel: PASS 2026-09-11 receipt:3c1acfba -->

- [x] 2.1 Add `PropertyDetailDto` to `frontend/features/properties/data/dto.ts`
      (extends `PropertySummaryDto` with the fields the list omits: notes are
      already absent from `PropertySummaryDto`, so add `accessNotes`,
      `cleaningNotes`, `emergencyNotes`), plus `CreatePropertyInput` and
      `UpdatePropertyInput` camelCase command shapes (design D7, D8). Neither
      input type carries `pmsProvider` (create-only, not offered by this UI —
      R1.2) or `status`/`currentOperationalState` outside the dedicated retire
      path (R2.3, R2.6). [R1.2, R2.2, R2.3]
- [x] 2.2 Add to `HttpPropertiesSource`
      (`frontend/features/properties/data/http/http-properties-source.ts`):
      `getProperty(tenantId, id)` → `GET /api/v1/properties/{id}`, mapping the
      full `PropertyResponse` to `PropertyDetailDto`; `createProperty(tenantId,
      input)` → `POST /api/v1/properties`; `updateProperty(tenantId, id, input)`
      → `PATCH /api/v1/properties/{id}`, sending only the keys present on
      `input` (the caller is responsible for the diffing, D8 — this method does
      not filter). Unit tests for all three: request shape, response mapping,
      that `wifi_password` is never read from any response. [R1.2, R1.4, R2.2, R2.5]
- [x] 2.3 Add `propertiesKeys.detail(tenantId, id)` to
      `frontend/features/properties/hooks/query-keys.ts`, same
      `tenantScopedKey` convention as `propertiesKeys.list`.
- [x] 2.4 Create `frontend/features/properties/hooks/use-property.ts`:
      `useProperty(id)`, mirrors `use-properties.ts` (retry policy, tenant guard).
      [R2.2]
- [x] 2.5 Create `frontend/features/properties/hooks/use-create-property.ts`:
      `useCreateProperty()` — `retry: false`, no optimistic write; `onSettled`
      invalidates `propertiesKeys.list(tenantId)` (prefix) and the hand-reproduced
      `["tenant", tenantId, "dashboard-cards"]` prefix, same pattern as
      `useResolveIncident` (design D10). [R1.4]
- [x] 2.6 Create `frontend/features/properties/hooks/use-update-property.ts`:
      `useUpdateProperty()` — same skeleton; `onSettled` invalidates
      `propertiesKeys.list(tenantId)`, `propertiesKeys.detail(tenantId, id)`, and
      the hand-reproduced `["tenant", tenantId, "dashboard-cards"]` and
      `["tenant", tenantId, "property-detail", id]` prefixes (design D10). Test
      that both hooks fire exactly the documented invalidations (mock
      `queryClient.invalidateQueries`). [R2.2]
- [x] 2.7 Export `PropertyDetailDto`, `CreatePropertyInput`, `UpdatePropertyInput`
      and the new hooks from `frontend/features/properties/index.ts` so
      `features/dashboard` can import them (design D3's cross-feature import,
      mirroring how `dashboard` already imports from `@/features/incidents`).
- [x] 2.8 Run `cd frontend && npm run typecheck && npm test -- properties` to
      confirm the data layer compiles and its own tests pass before any UI
      depends on it.

## 3. Create flow <!-- panel: PASS 2026-09-11 receipt:baf66912 -->

- [x] 3.1 Add locale keys to `frontend/locales/{es,en}/properties.json`: field
      labels, placeholders, the `access_notes` inline guidance (design D14),
      validation messages, `newProperty` button label, create success/generic
      error copy. [R1, R4.1]
- [x] 3.2 Create `frontend/features/properties/components/form/property-fieldset.tsx`:
      the shared ~15-field presentational list (name, internal_code,
      pms_external_id, address block, country, timezone, capacity trio,
      check-in/out times, wifi name/password, three notes), receiving `values`/
      `onChange`/`fieldErrors` as props, `maxLength` wired from
      `field-limits.ts`, one programmatically associated label per field,
      required fields marked. Never renders `pms_provider` or `status`. [R1.2, R3.1, R3.2, R3.3, R4.2]
- [x] 3.3 Create
      `frontend/features/properties/components/form/create-property-form.tsx`:
      controlled state per field (design D1), `validatePropertyFields` on
      submit, `useCreateProperty`, submit disabled + pending copy while in
      flight (R1.6), `mapPropertyFieldErrors` on error, `router.push` to
      `/properties/{id}` on `201` (design D11). Component test covering: happy
      path navigation, client-side validation blocking submit, `409` on each of
      `internal_code`/`pms_external_id` attributing to the right field,
      double-submit prevention. [R1.1, R1.3, R1.4, R1.5, R1.6]
- [x] 3.4 Wire `PropertiesView`
      (`frontend/features/properties/components/list/properties-view.tsx`):
      "New property" button gated by `useHasPermission("MANAGE_PROPERTIES")`,
      opening a `Sheet` hosting `CreatePropertyForm` (mirrors `PlatformConsole`,
      design D2). Component test: button hidden without permission, `Sheet`
      opens/closes. [R1.1]

## 4. Edit flow <!-- hard --> <!-- panel: PASS 2026-09-11 receipt:c0382627 -->

- [x] 4.1 Add locale keys to `frontend/locales/{es,en}/properties.json`: the
      "clear stored password" checkbox copy (shared fieldset context), and to
      `frontend/locales/{es,en}/dashboard.json`: edit button label, save/cancel,
      edit success/generic error copy. [R2, R4.1]
- [x] 4.2 Create
      `frontend/features/properties/components/form/edit-property-form.tsx`:
      `useProperty(id)` to fetch and pre-fill (design D7); keeps the initial
      snapshot alongside live values; on submit, builds the `PATCH` body with
      only changed fields (design D8) — a nullable field cleared from
      non-empty sends `null`, an already-empty nullable field left alone is
      omitted, a non-nullable field can never produce `null` (validation blocks
      it first). `wifi_password` starts blank (never pre-filled, R2.5), a typed
      value is sent as a change, and a separate "clear stored password"
      checkbox is the only way to send `wifi_password: null` — unchecked and
      blank omits the field entirely. Does not render `pms_provider` or
      `current_operational_state`/`status` (R2.3). Submit disabled + pending
      copy while in flight (R2.8), `mapPropertyFieldErrors` on error (R2.7).
      [R2.1, R2.2, R2.3, R2.4, R2.5, R2.7, R2.8]
- [x] 4.3 Component tests for 4.2: pre-fill from fetched data; saving with no
      changes sends an empty/no-op body; clearing a nullable text field sends
      `null` for exactly that field and omits untouched ones; typing a wifi
      password sends it; checking "clear password" with the field left blank
      sends `wifi_password: null`; leaving both untouched omits
      `wifi_password`; `409` on either conflicting field attributes correctly;
      double-submit prevention. [R2.2, R2.4, R2.5, R2.7, R2.8]
- [x] 4.4 Wire `PropertyDetailView`
      (`frontend/features/dashboard/components/detail/property-detail-view.tsx`):
      "Edit" button gated by `useHasPermission("MANAGE_PROPERTIES")`, opening a
      `Sheet` hosting `EditPropertyForm` (imported from `@/features/properties`,
      design D3/D13). Component test: button hidden without permission, `Sheet`
      opens/closes, edit-form copy reads from the right namespaces. [R2.1]

## 5. Retire flow <!-- panel: PASS 2026-09-11 receipt:14f91bb4 -->

- [x] 5.1 Add locale keys to `frontend/locales/{es,en}/dashboard.json`: retire
      button label, `AlertDialog` confirmation title/description/confirm/cancel
      copy. [R2.6, R4.1]
- [x] 5.2 Add a "Retire property" button to `PropertyDetailView`, gated by
      `useHasPermission("MANAGE_PROPERTIES")` AND the property's current
      `status !== "INACTIVE"` (hidden once already retired), opening an
      `AlertDialog` (design D9). On confirm, calls `useUpdateProperty` with
      exactly `{ status: "INACTIVE" }` — never merged with any pending edit-form
      changes. [R2.6]
- [x] 5.3 Component test: button hidden without permission and when already
      `INACTIVE`; confirming calls the mutation with exactly that body and
      nothing else; cancelling the dialog makes no request. [R2.6]

## 6. Accessibility and responsive verification <!-- hard --> <!-- panel: PASS 2026-09-12 receipt:3b0f9aaf -->

- [x] 6.1 For both `CreatePropertyForm` and `EditPropertyForm`: verify (with
      Testing Library, `jest-axe`/existing a11y test convention if present in
      the tree, otherwise explicit assertions) that every field has a
      programmatic label, required fields are marked, validation errors are
      associated with their field, focus order follows visual order, and no
      `:focus-visible` is suppressed. [R4.2, R4.3]
- [x] 6.2 Verify keyboard-only operability of both forms and the retire
      `AlertDialog` (tab order reaches every control, Enter/Space activate
      buttons, Escape closes the `Sheet`/`AlertDialog`). [R4.3]
- [x] 6.3 Verify both `Sheet`s and the fieldset render without overflow or
      clipping at this project's minimum supported width (mobile-first,
      `steering/frontend.md`). [R4.4]

## 7. Verification

- [x] 7.1 Full frontend test suite passes: `cd frontend && npm test`
      (2819/2819, 247 files) plus `cd frontend && npm run test:layout`
      (95/95, 2 files — this feature added `.browser.test.tsx` files that
      `npm test` alone does not run, per Section 6's Implementation Notes).
- [x] 7.2 Lint and typecheck pass: `cd frontend && npm run lint && npm run typecheck`
      — both clean.
- [x] 7.3 Backend suite unaffected (no backend files touched by this change):
      confirmed via `git diff --stat main...HEAD -- backend/` (empty output —
      zero backend files touched across the entire branch), so the suite
      cannot have regressed. Did not bring up the Docker stack to run it live:
      this worktree has no bootstrapped `.env` and the change touches no
      backend code, so running it would verify nothing this change could
      have broken.
- [x] 7.4 Manual end-to-end pass with the stack up (`make up`): as a
      `PROPERTY_MANAGER`, create a property with all fields including a wifi
      password and the three notes, confirm redirect to its detail page and
      the new values there; edit it — clear one nullable field, change the wifi
      password, verify the "clear password" checkbox path separately; retire
      it and confirm the button disappears afterward; repeat the visibility
      checks as `TENANT_OWNER` (no create/edit/retire affordance visible).
      <!-- manual --> Verified 2026-09-12 post-merge on `main` via browser
      automation against `make up`: created `QAARCH01` as manager (redirect to
      detail, all fields incl. wifi password and three notes persisted per
      edit-form reopen); edited it (cleared city, changed wifi password);
      verified "Borrar la contraseña guardada" checkbox path separately
      (confirmed `wifi_password_encrypted IS NULL` in Postgres afterward);
      retired it and confirmed "Retirar propiedad" disappears, leaving only
      "Editar propiedad"; as `TENANT_OWNER`, confirmed no "Nueva propiedad",
      "Editar propiedad" or "Retirar propiedad" affordance on either the list
      or detail page.

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one. -->

### Section 1 (permission mirror and field-level libraries)

- `frontend/lib/auth/permissions.ts`: `Permission` union now includes `"MANAGE_PROPERTIES"`; `ROLE_UI_PERMISSIONS.PROPERTY_MANAGER` includes it, `TENANT_OWNER` does not.
- `frontend/features/properties/lib/field-limits.ts`: exports `MAX_NAME`, `MAX_INTERNAL_CODE`, `MAX_PMS_EXTERNAL_ID`, `MAX_ADDRESS`, `MAX_CITY`, `MAX_PROVINCE`, `MAX_POSTAL_CODE`, `MAX_WIFI_NAME`, `MAX_NOTES`, `MAX_WIFI_PASSWORD`, `MAX_GUESTS`, `MAX_ROOMS` (all `number` constants).
- `frontend/features/properties/lib/field-validation.ts`: exports `interface PropertyFieldValues { name: string; internal_code: string; country: string; max_guests: number; bedrooms: number; bathrooms: number; wifi_password?: string | null; access_notes?: string | null; cleaning_notes?: string | null; emergency_notes?: string | null; }` (snake_case, mirrors backend request fields directly — no dependency on `data/dto.ts`) and `function validatePropertyFields(values: PropertyFieldValues): Record<string, string>`.
- `validatePropertyFields` return values are error **keys**, not final copy: `"required"`, `"tooLong"`, `"invalidCountry"`, `"outOfRange"` — Section 3/4 must translate these via `properties.json` locale keys, not render them directly.
- `validatePropertyFields` only checks the fields R1.3 names (name/internal_code required+length, country format, max_guests/bedrooms/bathrooms range, wifi_password/three notes length). `pms_external_id`, address fields, `city`, `province`, `postal_code`, `wifi_name` are NOT length-checked here — Section 3/4 must rely on `maxLength` on the `<input>`/`<textarea>` itself for those (design D5).
- `frontend/features/properties/lib/field-errors.ts`: exports `function mapPropertyFieldErrors(error: unknown, fallbackField?: string): Record<string, string>`. `422` reads `error.details.errors` by `loc` (last segment as key, `msg` as value). `409` matches the exact substrings `"internal_code"` / `"pms_external_id"` in `error.message` and attributes to that field name; if neither substring matches, falls back to `{ [fallbackField]: error.message }` when `fallbackField` is given, else `{}`.
- `frontend/features/properties/lib/error-mapping.ts` was NOT touched — `field-errors.ts` is a separate sibling file (design D6).

### Section 2 (data layer — full-detail fetch and mutations)

- `frontend/features/properties/data/dto.ts` exports `PropertyDetailDto extends PropertySummaryDto { accessNotes: string | null; cleaningNotes: string | null; emergencyNotes: string | null; }` — camelCase, no `wifiPassword` field (none in the contract).
- `dto.ts` also exports `CreatePropertyInput { name: string; internalCode: string; pmsExternalId?, addressLine1?, addressLine2?, city?, province?, postalCode?: string | null; country?, timezone?: string; maxGuests?, bedrooms?, bathrooms?: number; defaultCheckInTime?, defaultCheckOutTime?: string; wifiName?, wifiPassword?, accessNotes?, cleaningNotes?, emergencyNotes?: string | null; }` — no `pmsProvider`, no `status`.
- `dto.ts` also exports `UpdatePropertyInput` — same field set as `CreatePropertyInput` but every field optional (including `name`/`internalCode`), plus one extra field: `status?: PropertyStatus`. `status` exists ONLY for the retire path (D9) — `EditPropertyForm` (section 4) must never set it; only the "Retire property" action may, and only as exactly `{ status: "INACTIVE" }`. No `pmsProvider`, no `currentOperationalState` field at all.
- `HttpPropertiesSource.getProperty(tenantId, id)`, `.createProperty(tenantId, input)`, `.updateProperty(tenantId, id, input)` all return `Promise<PropertyDetailDto>`. `updateProperty` sends `input`'s keys through as-is (including explicit `null`) — it does not diff or filter; the caller (section 4's `EditPropertyForm`, or the retire button) owns that decision.
- `frontend/features/properties/hooks/query-keys.ts`: `propertiesKeys.detail(tenantId, id)` and `propertiesKeys.listPrefix(tenantId)` (the latter is new, not in the original task text — needed because `propertiesKeys.list(tenantId, filters)` always bakes in `normalizePropertyFilters`'s `{page: 1}` default and is NOT a bare prefix; `listPrefix` is the one to invalidate by, precedent `incidentsKeys.listPrefix`).
- `frontend/features/properties/hooks/use-property.ts`: `useProperty(id): UseQueryResult<PropertyDetailDto>`.
- `frontend/features/properties/hooks/use-create-property.ts`: `useCreateProperty(): UseMutationResult<PropertyDetailDto, Error, CreatePropertyInput>`.
- `frontend/features/properties/hooks/use-update-property.ts`: `useUpdateProperty(): UseMutationResult<PropertyDetailDto, Error, UpdatePropertyMutationInput>` where `UpdatePropertyMutationInput = { id: string; input: UpdatePropertyInput }` — mutate with `{ id, input: { status: "INACTIVE" } }` for retire (D9), or `{ id, input: <diffed fields> }` for a save.
- Hand-reproduced dashboard invalidation keys used by both mutation hooks' `onSettled` (verbatim, copy these into section 4/5 code rather than re-deriving): `["tenant", tenantId, "dashboard-cards"]` (both hooks) and `["tenant", tenantId, "property-detail", id]` (update only). `features/properties` still does not import `dashboardKeys`.
- `frontend/features/properties/index.ts` now re-exports `useProperty`, `useCreateProperty`, `useUpdateProperty` (+ `UpdatePropertyMutationInput`), and the types `PropertyDetailDto`/`CreatePropertyInput`/`UpdatePropertyInput` (via `export type {...} from "./data"`), alongside the pre-existing `PropertiesView`.
- `cd frontend && npm run typecheck && npm test -- properties`: typecheck clean, 149/149 tests passed (12 test files).

### Section 3 (create flow)

- `frontend/features/properties/components/form/property-fieldset.tsx` exports `PropertyFormFields` (the flat, snake_case, ~20-field superset of `PropertyFieldValues` — includes every field `PropertyFieldValues` omits: `pms_external_id`, the address block, `wifi_name`, `timezone`, the two check-in/out times) and `PropertyFieldset({ values: PropertyFormFields, onChange: (field: keyof PropertyFormFields, value: string | number) => void, fieldErrors: Record<string, string>, disabled?: boolean })`. Section 4's `EditPropertyForm` should reuse this component and this exact prop shape verbatim — `onChange` is NOT generic (plain `(field, value) => void`), so a caller with a numeric field does its own `Number(...)` conversion before calling it (see `property-fieldset.tsx`'s own numeric `<input>`s for the pattern). `PropertyFieldset` never translates `fieldErrors` itself — callers must pass already-localized strings (translated validation keys or raw backend 422/409 messages, see `create-property-form.tsx`). Ids are `property-<field with _ replaced by ->` (e.g. `property-internal-code`, `property-default-check-in-time`); `#property-access-notes-hint` is the D14 hint's id, referenced via that `<textarea>`'s `aria-describedby` — reuse it if Section 4 needs to point at the same hint. `wifi_password` renders as `type="password"` with `autoComplete="new-password"`; the three notes and `wifi_password` are plain `<textarea>`/`<input>`, never parsed (R3.3).
- `frontend/features/properties/components/form/create-property-form.tsx` exports `CreatePropertyForm()` (no props). It owns `useState<PropertyFormFields>`, calls `validatePropertyFields` (which accepts `PropertyFormFields` directly — it's a structural superset of `PropertyFieldValues`) on submit, translates the returned error **keys** via `t(\`createForm.errors.${key}\`)` before handing them to `PropertyFieldset`, and merges in `mapPropertyFieldErrors(mutation.error)` (raw, untranslated backend text) only when there are no live client-validation errors. The `<form>` has `noValidate` (mirrors `login-form.tsx`): `name`/`internal_code` still carry the HTML `required` attribute for a11y (R4.2), but browser-native constraint validation is disabled so `validatePropertyFields` is the single, consistent path that blocks submit and renders errors — without `noValidate`, jsdom (and real browsers) silently block the `submit` event before `onSubmit` ever runs when a `required` field is empty, which is also why any Section 4 form reusing native `required` attributes needs the same `noValidate`. Navigation is via `mutation.mutate(input, { onSuccess: (created) => router.push(...) })` — the callback form of `mutate`, not a `useEffect` watching `mutation.isSuccess`. Double-submit guard is `if (mutation.isPending) return;` at the top of `handleSubmit`, on top of the disabled submit button.
- `PropertiesView` (`frontend/features/properties/components/list/properties-view.tsx`) now calls `useHasPermission("MANAGE_PROPERTIES")` unconditionally at the top (rules-of-hooks) and owns one `useState<boolean>` for the create `Sheet`'s open state. `properties-view.test.tsx` now mocks `@/lib/auth`'s `useHasPermission` (default `true`) and stubs `../form/create-property-form`'s `CreatePropertyForm` — any Section 4/5 test touching `PropertiesView` or `PropertyDetailView` should mock `@/lib/auth` the same way rather than relying on a real `AuthProvider`.
- Locale keys added to `properties.json` (both languages), all under the `properties` namespace (no new namespace, unlike `dashboard`'s cross-namespace precedent for operational states): top-level `newProperty` (the list's button) and `sheet.close`/`sheet.newPropertyTitle` (mirrors `platform.json`'s `sheet.*` shape), plus `createForm.fields.*` (one key per of the 20 fields, camelCase field name), `createForm.placeholders.{country,timezone}`, `createForm.accessNotesHint` (D14), `createForm.errors.{required,tooLong,invalidCountry,outOfRange}` (translates `validatePropertyFields`'s error keys verbatim — Section 4 reuses these same four, do not add a second copy), and `createForm.{submit,submitting,genericError}`. Section 4 adds its own `edit`-scoped keys to `properties.json` (per the task list: the "clear stored password" checkbox copy) plus new keys to `dashboard.json` (edit button, save/cancel, edit success/error, retire copy) — `properties-locale.test.ts` was not touched (it only pins the `PropertyStatus`/`PropertyOperationalState` catalogs and the six list columns; it does not enumerate `createForm.*` and does not need to for this section).
- `cd frontend && npm run typecheck && npm test -- properties`: typecheck clean, 166/166 tests passed (14 test files, up from 149/12 after Section 2 — added `create-property-form.test.tsx` and `property-fieldset.test.tsx`, and extended `properties-view.test.tsx`).

### Section 4 (edit flow)

- **`property-detail-view.tsx`, exact structure left for Section 5's retire button.** Two hooks now run at the top of `PropertyDetailView`, before every early return (rules of hooks): `const canManageProperties = useHasPermission("MANAGE_PROPERTIES")` and `const [isEditOpen, setIsEditOpen] = useState(false)`. The success branch's first child is now a header row — `<div className="flex flex-wrap items-center justify-between gap-3">` holding the `<h1>` plus, when `canManageProperties`, a **button group** `<div className="flex items-center gap-2">` whose only child today is the Edit `<Button>`. **Section 5's "Retire property" button goes inside that same group, right after Edit** (a comment in the file says so), reusing `canManageProperties` — do not add a second `useHasPermission` call. The edit `Sheet` is the last child of the outer `div`, after `<PropertyTimeline>`; the retire `AlertDialog` can be its sibling there. Section 5's extra gate (`status !== "INACTIVE"`) is **not** available from this view's own query: `usePropertyDetail` is the dashboard aggregate (`PropertyDetail`) and it carries `operationalState`, **not** `status` — Section 5 has to source `status` itself (e.g. `useProperty(propertyId)` from `@/features/properties`, the same hook `EditPropertyForm` uses, which is already cached under `propertiesKeys.detail`).
- `frontend/features/properties/components/form/edit-property-form.tsx` exports `EditPropertyForm({ propertyId: string; onCancel?: () => void; onSaved?: (property: PropertyDetailDto) => void })` and `EditPropertyFormProps`; both are re-exported from `frontend/features/properties/index.ts`. `onCancel` is optional and the Cancel button renders **only when it is passed** (the detail view passes `() => setIsEditOpen(false)`). Saving does **not** close the `Sheet`: on success the form re-seeds its snapshot from the server's returned `PropertyDetailDto` and shows `detail.edit.success` inline (`role="status"`), so a second save diffs against the saved values instead of replaying them.
- Diffing (D8) lives in a module-private `buildUpdateInput(initial, values, clearWifiPassword)`, driven by four `[UpdatePropertyInput key, PropertyFormFields key]` tables: `NULLABLE_TEXT_FIELDS` (the only fields that may ever be `null`), `REQUIRED_TEXT_FIELDS`, `TIME_FIELDS` (re-adds `:00`), `NUMBER_FIELDS`. Rule: unchanged → omitted; nullable emptied (trim) from a non-empty value → `null`; nullable empty-to-empty (whitespace included) → omitted. **`status` is never written by this function** — the retire path is the only writer (D9).
- `wifi_password` and the "clear stored password" checkbox are **mutually exclusive by construction**: typing a non-empty password unchecks the box, checking the box blanks the password input. So the body carries at most one of `wifiPassword: <value>` / `wifiPassword: null`, never an ambiguous pair.
- The checkbox and its hint are rendered by `EditPropertyForm` **after** `<PropertyFieldset>`, not inside it — `PropertyFieldset`'s prop signature is untouched (the create form has no stored password to keep or clear). Ids: `#property-clear-wifi-password`.
- Namespaces (D13): `EditPropertyForm` calls `useTranslation("properties")` for `editForm.*` and for translating `validatePropertyFields`'s error keys via the **existing** `createForm.errors.*` (no second copy), `useTranslation("dashboard")` for `detail.edit.{submit,submitting,cancel,success,genericError}`, and `useTranslation("states")` for its own fetch loading/error states (`LoadingState`/`ErrorState`, reusing `states.error.*` rather than adding new keys).
- Locale keys added: `properties.json` → `editForm.{wifiPasswordHint,clearWifiPassword}`; `dashboard.json` → `detail.edit.{button,title,close,submit,submitting,cancel,success,genericError}`. **Section 5's retire copy belongs under `detail.retire.*` in `dashboard.json`**, alongside `detail.edit.*`, both locales (`lib/i18n/catalog-parity.test.ts` enforces es/en symmetry).
- `property-detail-view.test.tsx` now mocks `@/lib/auth`'s `useHasPermission` (`useHasPermissionMock`, reset to `true` in `beforeEach`) and stubs `@/features/properties` with `{ EditPropertyForm }` only — **Section 5 must extend that stub if it imports anything else from that barrel**, or the module mock will make it `undefined`.
- `cd frontend && npm run typecheck && npm run lint && npm test -- properties dashboard`: typecheck and lint clean, 429/429 tests passed (41 test files) — added `edit-property-form.test.tsx` (27 tests) and 3 tests to `property-detail-view.test.tsx`.

### Section 5 (retire flow)

- `property-detail-view.tsx` now also calls `useProperty(propertyId)` (module-level, unconditional, right after the pre-existing hooks — before any early return) **purely to read `status`** for the retire gate; it renders no loading/error state of its own for this query — if `propertyQuery.data` is `undefined` (still loading or errored) the retire button just stays hidden (`canRetire = canManageProperties && propertyQuery.data !== undefined && propertyQuery.data.status !== "INACTIVE"`). It also calls `useUpdateProperty()` once, at the same top level, for the retire confirm only — a **second, independent mutation instance** from whatever `EditPropertyForm` holds inside the `Sheet`; the two never share state, so an open edit form with unsaved changes cannot leak into the retire body.
- The "Retire property" `<Button variant="destructive">` renders inside the **same** button group as Edit (`<div className="flex items-center gap-2">`), immediately after it, only when `canRetire`. It opens `isRetireOpen` state driving an `AlertDialog` (shadcn) that is a **sibling of the edit `Sheet`**, last child of the outer `div`.
- The retire `AlertDialog`'s confirm handler (`handleRetireConfirm`) mirrors `ManagerIncidentActions`' `CancelDialog` pattern exactly (`frontend/features/incidents/components/detail/manager-incident-actions.tsx`): `AlertDialogAction` is Radix's `Dialog.Close` under the hood and closes unconditionally unless the click handler calls `event.preventDefault()`; a `retireSubmittingRef` (not `mutation.isPending`, which only flips on the next commit) guards against two clicks in the same frame; `onSuccess` is the only path that calls `setIsRetireOpen(false)` — a failed retire (`mutation.isError`) keeps the dialog open with `detail.retire.genericError` shown as `role="alert"` beneath the description, no field-level/409-specific mapping (the body is a fixed `{ status: "INACTIVE" }`, nothing to disambiguate by field).
- `retireMutation.mutate({ id: propertyId, input: { status: "INACTIVE" } }, { onSuccess, onError, onSettled })` — exactly that body, built inline, never derived from or merged with `EditPropertyForm`'s diffed `buildUpdateInput` output (they are different component instances entirely and neither observes the other). **That is structural independence, not simultaneous operability**: the edit `Sheet` is a modal Radix dialog, so while it is open the Retire trigger behind it is neither clickable (the overlay takes the pointer events) nor keyboard-reachable (outside the focus trap, `aria-hidden` in the accessibility tree) — the two overlays are mutually exclusive and the user closes the Sheet before reaching Retire. What the separation buys is that a retire body can never pick up `EditPropertyForm`'s pending diff, whatever the form is holding when it closes.
- Neither the "Retire property" trigger `Button` nor `AlertDialogAction`/`AlertDialogCancel` carry a `tap-target` class (44×44 floor) — same as the pre-existing "Edit" button, which also lacks it. Note for Section 6: `AlertDialogAction`/`AlertDialogCancel` (`frontend/components/ui/alert-dialog.tsx`) destructure `className` in their props but never apply it to the wrapped `Button` — passing `className="tap-target"` to either is silently dropped as-is today; any 44×44 fix for the retire dialog's buttons needs a change to `alert-dialog.tsx` itself (or a wrapper), not just a prop at the call site. This is pre-existing (the incidents `CancelDialog` has the same gap) — Section 6 should treat Edit + Retire buttons and the retire dialog's two buttons as one 44×44 sweep, not three separate fixes.
- Locale keys added: `dashboard.json` (both locales) → `detail.retire.{button,title,description,cancel,confirm,confirming,genericError}`, alongside `detail.edit.*`. No new namespace, no keys added to `properties.json` for this section.
- `property-detail-view.test.tsx`: extended the `@/features/properties` module mock (previously `{ EditPropertyForm }` only) with `useProperty` and `useUpdateProperty` (both `vi.hoisted` mocks), defaulted in `beforeEach` to `{ data: { status: "ACTIVE" } }` and a mocked `mutate`/`isPending: false`/`isError: false` respectively — **any Section 6 test touching this view must keep both mocked** or the real hooks resolve `undefined`/throw (no `AuthProvider`/react-query context in this suite).
- `cd frontend && npm run typecheck && npm run lint && npm test -- properties dashboard`: typecheck and lint clean, 437/437 tests passed (41 test files, up from 429/41 after Section 4) — added 7 tests to `property-detail-view.test.tsx` (offer/hide by permission, hide when `INACTIVE`, hide while `status` not yet loaded, confirm calls the mutation with exactly `{ status: "INACTIVE" }`, cancel makes no request, error stays visible with the dialog open).

### Section 6 (accessibility and responsive verification)

- **Section 7 must run a FOURTH command: `cd frontend && npm run test:layout`.** This section adds `frontend/features/properties/components/form/property-forms-layout.browser.test.tsx`, which matches `**/*.browser.test.{ts,tsx}` and therefore runs in vitest's **`browser`** project (real Chromium via Playwright), not the `node`/jsdom one. `npm test` is `vitest run --project node` and **silently skips it** — a green 7.1 says nothing about task 6.3. `test:layout` first runs `build:layout-css` (Tailwind CLI → `test/artifacts/globals.css`, gitignored) and then `vitest run --project browser`, so it also re-runs the pre-existing `features/shell/components/topbar-overflow.browser.test.tsx`. It needs a Chromium binary: `npx playwright install chromium` (this session had to install it — `chromium_headless_shell` was missing even though `npx playwright --version` worked).
- **`npm test` fails in a worktree where Next has never been run.** `test/color-tokens.test.ts` asserts the exact list of loose files at `frontend/`, and that list includes `next-env.d.ts` — a gitignored file Next generates. On a fresh worktree the full suite reports `1 failed | 2818 passed` on that one test and nothing else. Generate it (`npx next dev`, kill once the file appears) before reading 7.1 as red. With it present: **2819/2819 passed, 247 test files**.
- **Focus return on close was broken on all three overlays and is now fixed at the call sites.** Radix restores focus after a modal `Dialog`/`AlertDialog` closes only through its own `DialogTrigger` ref: `DialogContentModal` installs an `onCloseAutoFocus` that calls `event.preventDefault()` and then `triggerRef.current?.focus()`. This feature's create `Sheet`, edit `Sheet` and retire `AlertDialog` are all opened from a **detached, state-controlled `Button`**, not a `SheetTrigger`/`AlertDialogTrigger` (the tree's other three sheets wrap theirs — `more-menu.tsx` records focus return as the reason), so `triggerRef.current` was `null`, the `preventDefault()` had already suppressed `FocusScope`'s own restore, and Escape dumped focus on `<body>`. Fix: a `useRef<HTMLButtonElement>` on each trigger plus an `onCloseAutoFocus` on `SheetContent`/`AlertDialogContent` that `preventDefault()`s and focuses it — skipped when the ref is null (the ordinary post-retire case, where the trigger has unmounted). **Any future overlay in this feature opened from a detached button needs the same three lines**, or it silently regresses; the guards are in `properties-view.test.tsx` and `property-detail-view.test.tsx`.
- `components/ui/alert-dialog.tsx` is the one **shared primitive** this section touched: `AlertDialogAction`/`AlertDialogCancel` now forward `className` to the wrapped `Button` instead of destructuring and dropping it (`Button` merges it through `cn(buttonVariants({…, className}))`, so variant colours are untouched). Every other `AlertDialog` call site in the tree is unaffected — confirmed by the full 2819-test suite, not just `properties dashboard`.
- **`tap-target` sweep** (`app/globals.css`: `min-height/min-width: 44px`): added to the fieldset's `inputClass` (so all 20 controls), both forms' submit/cancel buttons, the list's "New property" trigger, the detail view's Edit and Retire triggers, and the retire dialog's two buttons. **One documented exception**: the `#property-clear-wifi-password` checkbox keeps its native 13×13 glyph and its `<label for>` carries `tap-target` instead — a `<label for>` IS a pointer target, and the browser test measures the label's box for checkboxes only (`pointerTarget()`), never for any other control.
- **Error→field wiring (R4.2)**: `property-fieldset.tsx` now gives each error paragraph the id `property-<field>-error` and each control `aria-invalid` + `aria-describedby`. A field's static hint id comes **first** in `aria-describedby` and the error is **appended**, never swapped in (see the `access_notes` case). New helpers in that file: `fieldId()`, `errorId()`, `describedBy()`, `a11yProps(field, hintId?)`; `textFieldProps(field, hintId?)` takes the hint as its second argument now — callers no longer pass `aria-describedby` by hand.
- **The two-guard split, and which half answers what.** jsdom performs no layout, so `property-forms-a11y.test.tsx` / `properties-view.test.tsx` / `property-detail-view.test.tsx` assert the DOM (roles, names, `aria-*`, element order, `tabindex`, the *class* `tap-target`), and `property-forms-layout.browser.test.tsx` measures the *pixels* in Chromium (horizontal overflow, vertical reachability after scrolling, real 44×44 boxes) at **360px** — the minimum this tree fixes, set by `shell-topbar-overflow-360` and named in `vitest.config.ts`; `steering/frontend.md` states no number — and at **640px** (`sm`). Neither half alone is the proof: the class guard misses a control squeezed by a flex parent, the pixel guard misses a refactor that drops the class on an unmeasured surface.
- **The browser guard was falsified in reverse before being trusted**, the way `topbar-overflow.browser.test.tsx` requires. (a) Removing `import "@/test/artifacts/globals.css"` → 7 failures, so the stylesheet is genuinely load-bearing. (b) Breaking one call site's `overflow-y-auto` → the reachability test reports `CLIPPED — «Crear propiedad» still hangs 1218px below the panel`. Falsification (b) caught a real bug in the guard's first draft: it measured the **last control in DOM order**, which is `SheetPrimitive.Close` (`absolute right-4 top-4`, nearest the TOP), so it passed green against a panel with no scrolling at all. It now measures the control whose rendered `bottom` is lowest. **Keep that property if this file is edited.**
- **Harness for the browser project**: mock the individual hook modules (`@/features/properties/hooks/use-*`, `@/features/dashboard/hooks/use-dashboard-data`), never the `@/features/properties` barrel — the barrel has to stay real so `EditPropertyForm` renders. Spread `importOriginal()` over any module that exports names you do not override (a real ES module linker rejects an import of a missing name; `use-dashboard-data.ts` exports four). No `QueryProvider` is needed once every data hook is mocked.
- Commands run for this section: `npm run typecheck` clean · `npm run lint` **0 errors, 0 warnings** · `npm test -- properties dashboard` **474/474, 42 files** (up from 437/41 after section 5) · `npm test` **2819/2819, 247 files** · `npm run test:layout` **95/95, 2 files** (18 of them new here).
