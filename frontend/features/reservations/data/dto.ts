/**
 * DTOs for the reservations read-only list + detail (proposal R2 / R3).
 *
 * They replicate the real API contract (PRD §23): the list endpoint uses the
 * `ReservationPageResponse` envelope (`{data, page, per_page, total, total_pages}`)
 * with full `ReservationResponse` items; the detail endpoint returns a
 * `ReservationDetailResponse` (same shape plus a `guest` block). Errors travel
 * as the §23 error envelope, which `lib/api` turns into a thrown `ApiError`, so
 * these DTOs model success shapes only.
 *
 * Dates are ISO-8601 civil `YYYY-MM-DD` for check-in/out (per design D4 — no
 * timezone conversion in either direction). All money fields are decimal
 * strings (PRD §23) until a downstream component formats them. Types only — no
 * business logic, no runtime code.
 *
 * These shapes are the feature contract that `HttpReservationsSource` maps
 * from the two responses consumed by this change: the list and the detail.
 * Fields not present in those responses are not synthesized or fetched from
 * another endpoint.
 */

import type { components } from "@/lib/api/generated/openapi";

/** Reservation lifecycle status (PRD §7, re-exported from the generated OpenAPI). */
export type ReservationStatus = components["schemas"]["ReservationStatus"];

/** Reservation channel (PRD §23, re-exported from the generated OpenAPI). */
export type ReservationChannel = components["schemas"]["ReservationChannel"];

/** Reservation access status (PRD §23, re-exported from the generated OpenAPI). */
export type ReservationAccessStatus =
  components["schemas"]["ReservationAccessStatus"];

/** Payment status (PRD §23, re-exported from the generated OpenAPI). */
export type PaymentStatus = components["schemas"]["PaymentStatus"];

/** Legal registration status (PRD §23, re-exported from the generated OpenAPI). */
export type LegalRegistrationStatus =
  components["schemas"]["LegalRegistrationStatus"];

/** Guest document status (PRD §23, re-exported from the generated OpenAPI). */
export type GuestDocumentStatus =
  components["schemas"]["GuestDocumentStatus"];

/** Civil `YYYY-MM-DD` date — the format check-in/out travel in (design D4). */
export type CivilDate = string;

/** ISO-8601 timestamp with UTC timezone (PRD §23 date-time convention). */
export type IsoDateTime = string;

/**
 * The reservation guest as the UI is allowed to show it (security.md rule 4:
 * never the document number; only `document_status` / `legal_registration_status`
 * indicators). The PII fields `document_number`, `date_of_birth`,
 * `document_expiry_date`, and `nationality` are NOT in this DTO — the detail
 * endpoint does not return them, and the UI does not go looking for them.
 */
export interface GuestSummaryDto {
  id: string;
  fullName: string;
  email: string | null;
  phone: string | null;
  preferredLanguage: string;
  documentStatus: GuestDocumentStatus;
  legalRegistrationStatus: LegalRegistrationStatus;
}

/**
 * One row of the `/reservations` list (proposal R2, design D5). The list
 * endpoint returns the full `ReservationResponse` payload, but the UI only
 * surfaces a subset of fields per row. The detail endpoint returns the same
 * fields with a few extras (see `ReservationDetailDto`).
 */
export interface ReservationSummaryDto {
  id: string;
  propertyId: string;
  status: ReservationStatus;
  checkInDate: CivilDate;
  checkOutDate: CivilDate;
  nights: number;
  totalGuests: number;
  guestId: string | null;
  channel: ReservationChannel;
  currency: string;
  grossAmount: string | null;
  paymentStatus: PaymentStatus;
}

/**
 * Full reservation for `/reservations/[id]` (proposal R3). Extends the summary
 * with the detail-only fields the API returns and the UI must show:
 * - Times of day for check-in / check-out (separate from the dates).
 * - Party breakdown (`adults`, `children`).
 * - Financial breakdown (`otaCommission`, `netAmount`).
 * - Operational flags (`cleaningRequired`, `accessStatus`).
 * - External identifiers and traceability (`externalChannelId`, `externalPmsId`).
 * - Free-text fields rendered as plain text (R3.3).
 * - Audit timestamps (`createdAt`, `updatedAt`).
 * - The guest block (null when no guest is linked).
 */
export interface ReservationDetailDto extends ReservationSummaryDto {
  checkInTime: string | null;
  checkOutTime: string | null;
  adults: number;
  children: number;
  otaCommission: string | null;
  netAmount: string | null;
  cleaningRequired: boolean;
  accessStatus: ReservationAccessStatus | null;
  externalChannelId: string | null;
  externalPmsId: string | null;
  internalNotes: string | null;
  specialRequests: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  guest: GuestSummaryDto | null;
}

/**
 * Pagination envelope for the list (PRD §23: `{ data, page, per_page, total, total_pages }`).
 * Keys are camelCase in the UI boundary; the mapper does the rename.
 */
export interface ReservationList {
  data: ReservationSummaryDto[];
  page: number;
  perPage: number;
  total: number;
  totalPages: number;
}

/**
 * Filters accepted by `useReservations` in v1 (design D4):
 * - `propertyId` is NOT exposed in v1 (a property picker would require fetching
 *   `/api/v1/properties` and is out of scope for this `size: S` change).
 * - Dates are civil `YYYY-MM-DD` strings; the hook does not convert zones and
 *   passes the value as-is to the API.
 * - The query key receives the whole filters object (order-stable, no
 *   `JSON.stringify`) so two equivalent renders produce the same key.
 */
export interface ReservationFilters {
  status?: ReservationStatus;
  dateFrom?: CivilDate;
  dateTo?: CivilDate;
  page?: number;
  perPage?: number;
}
