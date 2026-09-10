/**
 * UI DTOs for the approvals feature (design D9, D10; `incidents/data/dto.ts`'s
 * conventions).
 *
 * The wire types come from `components["schemas"][...]` (generated from
 * `backend/openapi.json`). This module mirrors the relevant pieces as UI DTOs
 * in `camelCase`, with explicit field enumeration to keep the snake_case /
 * camelCase boundary at the HTTP source.
 */
import type { components } from "@/lib/api/generated/openapi";

export type OwnerApprovalStatus = components["schemas"]["OwnerApprovalStatus"];
export type OwnerApprovalRelatedType =
  components["schemas"]["OwnerApprovalRelatedType"];

/**
 * The two answers the owner may give (`RespondOwnerApprovalRequest`'s own
 * docstring: "the entity refuses anything but APPROVED/REJECTED — the two an
 * owner can give"). Narrower than `OwnerApprovalStatus` on purpose: `PENDING`
 * and `EXPIRED` are never a decision this client sends.
 */
export type OwnerApprovalDecision = "APPROVED" | "REJECTED";

/** The originating incident, in the row's own reduced form (R1.3). */
export interface OwnerApprovalIncidentRefDto {
  id: string;
  title: string;
  category: components["schemas"]["IncidentCategory"];
  severity: components["schemas"]["IncidentSeverity"];
}

/** The vivienda in the form a person reads, never a bare UUID (R1.3). */
export interface OwnerApprovalPropertyRefDto {
  id: string;
  name: string;
  internalCode: string;
}

/**
 * One row of the approvals queue/history (camelCase mirror of
 * `OwnerApprovalListItemResponse`, R1.3). `incident` is `null` exactly when
 * `relatedType === "OTHER"` — never a same-shaped object with blank fields.
 */
export interface OwnerApprovalListItemDto {
  id: string;
  relatedType: OwnerApprovalRelatedType;
  status: OwnerApprovalStatus;
  amount: string;
  currency: string;
  requestedAt: string;
  respondedAt: string | null;
  incident: OwnerApprovalIncidentRefDto | null;
  property: OwnerApprovalPropertyRefDto;
}

/** Wire-shaped list envelope from the backend, renamed to camelCase. */
export interface OwnerApprovalPage {
  items: OwnerApprovalListItemDto[];
  total: number;
  page: number;
  perPage: number;
}

/**
 * Filter shape for `useApprovals`/`useApprovalsHistory` (D5, D9). `status` is
 * single-valued — the backend admits no repeatable `status` parameter (D5) —
 * which is why the history needs two requests, one per answered status.
 */
export interface OwnerApprovalFilters {
  status?: OwnerApprovalStatus;
  page?: number;
  perPage?: number;
}

/** Input of the owner's decision form (R3.1, R3.3, R3.6). */
export interface RespondOwnerApprovalInput {
  approvalId: string;
  status: OwnerApprovalDecision;
  responseNotes?: string;
}
