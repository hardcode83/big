/**
 * UI DTOs for the incidents feature (design D3).
 *
 * The wire types come from `components["schemas"][...]` (generated from
 * `backend/openapi.json`). This module mirrors the relevant pieces as UI DTOs
 * in `camelCase`, with explicit field enumeration to keep the snake_case /
 * camelCase boundary at the HTTP source.
 */
import type { components } from "@/lib/api/generated/openapi";

export type IncidentStatus = components["schemas"]["IncidentStatus"];
export type IncidentSeverity = components["schemas"]["IncidentSeverity"];
export type IncidentCategory = components["schemas"]["IncidentCategory"];
export type IncidentSource = components["schemas"]["IncidentSource"];

/** One row of the incidents list (D5: six columns, no `propertyId`). */
export interface IncidentSummaryDto {
  id: string;
  status: IncidentStatus;
  severity: IncidentSeverity;
  category: IncidentCategory;
  source: IncidentSource;
  title: string;
  createdAt: string;
}

/** Full detail of a single incident (all 18 fields of `IncidentResponse`). */
export interface IncidentDetailDto {
  id: string;
  propertyId: string;
  reservationId: string | null;
  source: IncidentSource;
  category: IncidentCategory;
  severity: IncidentSeverity;
  status: IncidentStatus;
  title: string;
  description: string;
  aiSummary: string | null;
  assignedTechnicianId: string | null;
  ownerApprovalRequired: boolean;
  estimatedCost: string | null;
  approvedCost: string | null;
  finalCost: string | null;
  resolvedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Wire-shaped list envelope from the backend, renamed to camelCase. */
export interface IncidentList {
  items: IncidentSummaryDto[];
  total: number;
  page: number;
  perPage: number;
}

/**
 * Filter shape for `useIncidents` v1 (D4). No `propertyId` — see proposal R2.2.
 * Keys are emitted in stable order by the source.
 */
export interface IncidentFilters {
  status?: IncidentStatus;
  severity?: IncidentSeverity;
  page?: number;
  perPage?: number;
}

/**
 * Derived in the client — the backend's `IncidentPageResponse` does not include
 * `total_pages`. `lastPage` is `max(1, ceil(total / perPage))`; with
 * `total = 0`, `lastPage = 1`.
 */
export interface IncidentPagination {
  page: number;
  perPage: number;
  total: number;
  lastPage: number;
}