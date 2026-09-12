# Proposal: properties-create-web

## Why

`POST /api/v1/properties` and `PATCH /api/v1/properties/{id}` have existed since
`properties-crud` (2026-08-08), but `frontend/features/properties` has no `useMutation` at
all — today a property is only born via `make seed-demo` or `curl`. `properties-web`
(2026-08-22) shipped the read-only portfolio index and explicitly left "alta, edición y
retirada desde la web" out of scope. That gap is the last piece of tenant onboarding still
requiring a terminal: `/platform` creates the tenant and its users, `tenant-settings-web`
lets the owner manage staff, but registering the property itself still needs `curl`. This
closes it — roadmap entry `properties-create-web`, hito «MVP operable» 3.

## What changes

`/properties` gains a "new property" flow (form → `POST`) reachable only to
`MANAGE_PROPERTIES`, and the existing property detail view (`PropertyDetailView` in
`features/dashboard`) gains an edit flow (form → `PATCH`) under the same permission,
including retiring a property (`status: INACTIVE`). Both forms cover the fields
`CreatePropertyRequest`/`UpdatePropertyRequest` actually accept, mirror the backend's own
validation bounds so a caller sees the same limit before submitting that the API would
enforce anyway, and surface the `409` conflict on `internal_code`/`pms_external_id`
collision as a field-level error. `pms_provider` is not offered by either form (see R2).

## Requirements

### R1 — Register a property

**As a** manager, **I want** to create a property from `/properties`, **so that** I can
onboard a new listing without a terminal.

Acceptance criteria:

1. WHEN a user with `MANAGE_PROPERTIES` opens `/properties`, THE SYSTEM SHALL offer a
   visible action to create a property; a user without that permission SHALL NOT see it
   (`useHasPermission("MANAGE_PROPERTIES")`, mirroring `blocked-transitions-section.tsx`).
2. THE SYSTEM SHALL collect exactly the fields `CreatePropertyRequest` accepts — `name`,
   `internal_code`, `pms_external_id`, address (`address_line1/2`, `city`, `province`,
   `postal_code`, `country`), `timezone`, `max_guests`, `bedrooms`, `bathrooms`,
   `default_check_in_time`, `default_check_out_time`, `wifi_name`, `wifi_password`,
   `access_notes`, `cleaning_notes`, `emergency_notes` — and SHALL NOT offer `pms_provider`
   or `status` (a new property always starts `ACTIVE`/`VACANT_READY`; see R2 for why
   `pms_provider` is excluded).
3. THE SYSTEM SHALL enforce, client-side before submit, the same bounds
   `backend/app/properties/api/schemas.py` declares: `name` and `internal_code`
   non-empty (max 200 / 50 chars), `country` exactly 2 uppercase letters, `max_guests`
   1-50, `bedrooms`/`bathrooms` 0-50, the three notes and `wifi_password` capped at their
   respective `MAX_NOTES` (5000) / `MAX_WIFI_PASSWORD` (200) lengths. A value outside these
   bounds SHALL be flagged before the request is sent, not only after a `422`.
4. WHEN the form is submitted and the API answers `201`, THE SYSTEM SHALL navigate to the
   new property's detail view.
5. IF the API answers `409` (duplicate `internal_code` or `pms_external_id` within the
   tenant/provider), THEN THE SYSTEM SHALL attach the error to the offending field instead
   of a generic banner, reusing `features/properties/lib/error-mapping.ts`.
6. WHILE the request is in flight, THE SYSTEM SHALL disable the submit control and show a
   pending state, preventing a duplicate submission.

### R2 — Edit a property

**As a** manager, **I want** to edit a property's details from its detail view, **so that**
I can correct or update information without a terminal.

Acceptance criteria:

1. WHEN a user with `MANAGE_PROPERTIES` views a property's detail, THE SYSTEM SHALL offer
   an edit action; a user without that permission SHALL NOT see it.
2. THE SYSTEM SHALL pre-fill the edit form with the property's current values (from the
   detail response already fetched) and SHALL submit only the fields the user actually
   changed, via `PATCH`.
3. THE SYSTEM SHALL NOT offer `pms_provider` for editing: it is create-only by design
   (`schemas.py:134-144`, the partial unique index keys on
   `coalesce(pms_provider, 'MOCK')`), and connecting/reassigning a PMS provider stays a CLI
   operation. THE SYSTEM SHALL NOT offer `current_operational_state` either — it is never
   part of `UpdatePropertyRequest` and only `PropertyStateMachine` moves it.
4. THE SYSTEM SHALL let a nullable field (`pms_external_id`, address fields, `wifi_name`,
   `wifi_password`, the three notes) be explicitly cleared, sending `null` only for a field
   the user actively cleared — never for a field merely left untouched.
5. WHEN the wifi password field is shown, THE SYSTEM SHALL NEVER pre-fill it with the
   stored value (the API never returns it, only `has_wifi_password`); the field starts
   empty and a blank submission SHALL NOT be sent as a change.
6. THE SYSTEM SHALL let the user retire the property (`status: INACTIVE`) as a distinct,
   explicitly-confirmed action separate from the general edit save — retiring is
   irreversible from this screen (no `DELETE`, no un-retire path specified here).
7. IF the API answers `409` on `internal_code`/`pms_external_id` collision, THEN THE SYSTEM
   SHALL attach the error to the offending field, same as R1.5.
8. WHILE a save is in flight, THE SYSTEM SHALL disable the submit control and show a
   pending state.

### R3 — Sensitive-field handling in both forms

**As a** manager, **I want** the notes and wifi-password fields to behave safely, **so
that** I don't mistake them for something they're not.

Acceptance criteria:

1. WHERE the `access_notes` field is rendered, THE SYSTEM SHALL show inline guidance that
   it is guest-facing free text for access instructions (it is echoed verbatim to the guest
   portal as `arrival_notes` and, since `tech-incident-context`, to the assigned
   technician) — not a place for a door/lock code (an `AccessRecord` is), and it entering a
   value here is deliberate, not a slip.
2. WHERE the `wifi_password` field is rendered, THE SYSTEM SHALL treat it as write-only:
   never pre-filled with a stored value (R2.5), and never echoed back in any success
   confirmation.
3. THE SYSTEM SHALL treat all four sensitive fields (`access_notes`, `cleaning_notes`,
   `emergency_notes`, `wifi_password`) as plain, unstructured text inputs — no attempt to
   parse or structure their content, matching how the backend stores them.

### R4 — i18n and accessible form baseline

**As a** user of either locale, **I want** the forms to be fully translated and usable by
keyboard and assistive tech, **so that** the feature meets this project's frontend
baseline.

Acceptance criteria:

1. THE SYSTEM SHALL route every visible string (labels, placeholders, validation messages,
   button text, confirmation copy) through `locales/es/` and `locales/en/` — nothing
   hardcoded, per `steering/frontend.md`.
2. THE SYSTEM SHALL give every field a programmatically associated label, mark required
   fields explicitly, and show validation errors adjacent to their field.
3. THE SYSTEM SHALL keep every interactive control keyboard-reachable and operable, with a
   visible focus state and a focus order matching the visual order.
4. THE SYSTEM SHALL remain usable without overflow or clipping at the project's minimum
   supported width (mobile-first), per `steering/frontend.md`'s responsive baseline.

## Out of scope

- Connecting or reassigning a PMS provider (`pms_provider`, `pms_credentials`) — stays a
  CLI operation (`docs/pms-credentials.md`); candidate future entry
  `pms-provider-assign-cli`.
- Physical deletion of a property — there is no `DELETE`; only retirement
  (`status: INACTIVE`) via R2.6.
- Property photos — no such entity exists yet.
- The photo grid restyle of `/properties` that `visual-restyle-workspace` left out —
  unrelated to this change.
- Encryption-at-rest of the three notes columns — tracked separately by roadmap entry
  `plaintext-sink-encryption-at-rest`; this change does not alter the rule-11 sink census,
  it only becomes their first UI writer.
- Any backend change: `POST`/`PATCH` and their validation, encryption and audit behavior
  are already implemented and archived (`properties-crud`).

## Affected specs

- `sdd/specs/properties-crud.md` — "La pantalla del portfolio" section currently states
  "el alta, la edición y la retirada siguen siendo sólo API"; this change makes that
  sentence false and the spec needs updating to describe the write screens.
