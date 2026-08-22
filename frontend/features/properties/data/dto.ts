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
