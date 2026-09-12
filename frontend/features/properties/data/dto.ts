import type { components } from "@/lib/api/generated/openapi";

/**
 * UI DTOs for the properties list (proposal R1). camelCase at the boundary,
 * mapped from the snake_case payload by `HttpPropertiesSource`.
 *
 * The unions are **re-exported from the generated OpenAPI** rather than
 * transcribed (design D5): `PropertyOperationalState` has eleven values and
 * `PropertyStatus` two, and a hand-written copy is one more catalog that can
 * drift from `backend/app/properties/domain/enums.py`.
 */

/** Property lifecycle status (PRD §7, re-exported from the generated OpenAPI). */
export type PropertyStatus = components["schemas"]["PropertyStatus"];

/** Canonical operational state (PRD §3.1, re-exported from the generated OpenAPI). */
export type PropertyOperationalState =
  components["schemas"]["PropertyOperationalState"];

/** PMS provider link (PRD §7, re-exported from the generated OpenAPI). */
export type PMSProvider = components["schemas"]["PMSProvider"];

/**
 * One row of the properties list.
 *
 * Mirrors `PropertyListItemResponse`, which is **not** `PropertyResponse`: it
 * omits `access_notes`, `cleaning_notes` and `emergency_notes`, the three
 * free-text sinks that `tech-incident-context` removed from the paginated list
 * (exception 6 of rule 11 in `steering/security.md`). This DTO must never grow
 * them: the list endpoint does not return them, and fetching them per row would
 * rebuild the bulk surface that exception was paid for (proposal R5.1, R5.2).
 *
 * There is no WiFi password in any shape either — `hasWifiPassword` is the only
 * signal the contract offers (R5.3).
 *
 * Nullability comes straight from the contract: `city`, `province`,
 * `postalCode`, both address lines, `wifiName`, `pmsProvider` and
 * `pmsExternalId` are all nullable, so every consumer must render the empty
 * case rather than assume a value.
 */
export interface PropertySummaryDto {
  id: string;
  name: string;
  internalCode: string;
  pmsProvider: PMSProvider | null;
  pmsExternalId: string | null;
  addressLine1: string | null;
  addressLine2: string | null;
  city: string | null;
  province: string | null;
  postalCode: string | null;
  country: string;
  timezone: string;
  maxGuests: number;
  bedrooms: number;
  bathrooms: number;
  currentOperationalState: PropertyOperationalState;
  defaultCheckInTime: string;
  defaultCheckOutTime: string;
  wifiName: string | null;
  hasWifiPassword: boolean;
  status: PropertyStatus;
  createdAt: string;
  updatedAt: string;
}

/**
 * One property in full (proposal R1.2, R2.2, design D7).
 *
 * Same shape as `PropertySummaryDto`, plus the three free-text notes the list
 * response omits: `accessNotes`, `cleaningNotes`, `emergencyNotes`. Mirrors
 * `PropertyResponse`, never `PropertyListItemResponse` — fetched one at a time
 * via `HttpPropertiesSource.getProperty`, never batched into the list response
 * (exception 6 of rule 11 in `steering/security.md`).
 *
 * Structurally without a WiFi password field, same as `PropertySummaryDto`:
 * `PropertyResponse` never carries one, in any form (rule 5.2 of
 * `steering/security.md`) — only `hasWifiPassword` signals whether one is set.
 */
export interface PropertyDetailDto extends PropertySummaryDto {
  accessNotes: string | null;
  cleaningNotes: string | null;
  emergencyNotes: string | null;
}

/**
 * The paginated envelope of PRD §23, verbatim — the same shape reservations
 * uses. It is a flat `{data, page, perPage, total, totalPages}`, **not** a
 * nested `meta` envelope (proposal R1.4); assuming otherwise is the mistake
 * `dto.test.ts` exists to catch.
 */
export interface PropertyList {
  data: PropertySummaryDto[];
  page: number;
  perPage: number;
  total: number;
  totalPages: number;
}

/**
 * The filters the v1 contract accepts, and only those (proposal R2.4).
 *
 * There is no text search, no selectable ordering and no city filter: the
 * endpoint does not accept them, so offering them would need new backend. The
 * two filters combine with AND and the ordering is fixed (`name`, with `id` as
 * the tie-break) so paging neither repeats nor skips rows.
 *
 * An `undefined` value means "all" and is omitted from the query string, never
 * sent as an empty string.
 */
export interface PropertyFilters {
  status?: PropertyStatus;
  currentOperationalState?: PropertyOperationalState;
  page?: number;
  perPage?: number;
}

/**
 * The `CreatePropertyRequest` command, camelCase (proposal R1.2, design D7/D8).
 *
 * Exactly the fields R1.2 names — `name`/`internalCode` are the only required
 * ones, matching the backend's own required pair; every other field is
 * optional and left out entirely lets the backend apply its own default
 * (`country`, `timezone`, `maxGuests`, `bedrooms`, `bathrooms`, the two
 * check-in/out times), same as an unset key in `CreatePropertyRequest`.
 *
 * Deliberately absent, and must stay absent:
 *  - `pmsProvider` — create-only in the backend contract, but not offered by
 *    this UI (R1.2).
 *  - `status`/`currentOperationalState` — a new property always starts
 *    `VACANT_READY`/`ACTIVE`; this UI never chooses it (R1.2).
 */
export interface CreatePropertyInput {
  name: string;
  internalCode: string;
  pmsExternalId?: string | null;
  addressLine1?: string | null;
  addressLine2?: string | null;
  city?: string | null;
  province?: string | null;
  postalCode?: string | null;
  country?: string;
  timezone?: string;
  maxGuests?: number;
  bedrooms?: number;
  bathrooms?: number;
  defaultCheckInTime?: string;
  defaultCheckOutTime?: string;
  wifiName?: string | null;
  wifiPassword?: string | null;
  accessNotes?: string | null;
  cleaningNotes?: string | null;
  emergencyNotes?: string | null;
}

/**
 * The `UpdatePropertyRequest` command, camelCase (proposal R2.2, R2.3, R2.6,
 * design D8, D9).
 *
 * Every field optional: only the keys the caller sets are meant to travel
 * (the diffing itself is `EditPropertyForm`'s job, D8 — `HttpPropertiesSource
 * .updateProperty` sends `input` through as given, it does not filter). A
 * value of `null` on a nullable field (`pmsExternalId`, the address fields,
 * `wifiName`, `wifiPassword`, the three notes) is a deliberate "clear this
 * field"; omitting the key entirely means "leave it alone".
 *
 * Deliberately absent, and must stay absent:
 *  - `pmsProvider` — create-only, never patchable (R2.3).
 *  - `currentOperationalState` — not patchable by this endpoint at all;
 *    `PropertyStateMachine` is the only thing that moves it.
 *
 * `status` IS present, but only for the dedicated retire path (D9, R2.6):
 * `EditPropertyForm` itself never renders or sets it (R2.3) — only the
 * "Retire property" confirmation calls `useUpdateProperty` with exactly
 * `{ status: "INACTIVE" }`.
 */
export interface UpdatePropertyInput {
  name?: string;
  internalCode?: string;
  pmsExternalId?: string | null;
  addressLine1?: string | null;
  addressLine2?: string | null;
  city?: string | null;
  province?: string | null;
  postalCode?: string | null;
  country?: string;
  timezone?: string;
  maxGuests?: number;
  bedrooms?: number;
  bathrooms?: number;
  defaultCheckInTime?: string;
  defaultCheckOutTime?: string;
  wifiName?: string | null;
  wifiPassword?: string | null;
  accessNotes?: string | null;
  cleaningNotes?: string | null;
  emergencyNotes?: string | null;
  status?: PropertyStatus;
}
