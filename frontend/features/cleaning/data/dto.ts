import type { components } from "@/lib/api/generated/openapi";

/**
 * DTOs for the manager's cleaning view (PRD §6, §24). They model success shapes
 * only: failures travel as the §23 error envelope, which `lib/api` turns into a
 * thrown `ApiError`. Dates are ISO-8601 UTC strings. Types only — no runtime code.
 *
 * `CleaningTask` carries the raw `propertyId`/`assignedCleanerId` the backend
 * returns, because `CleaningTaskResponse` has no denormalized names and this
 * change does not touch the backend (proposal "What changes"). Resolving them to
 * an identity is the feature's job (`lib/directory.ts`, design D5).
 */

/** ISO-8601 timestamp with UTC timezone (PRD §23 date convention). */
export type IsoDateTime = string;

/** Pagination envelope — PRD §23: `{ data, total, page, per_page, total_pages }`. */
export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/**
 * Alias of the generated union, never a hand-written copy (design D12): a tenth
 * status in the backend must break the build here as soon as the contract is
 * regenerated. That guarantee is compile-time only — see `lib/task-status.ts`
 * for the runtime fallback that covers the deploy-skew window.
 */
export type CleaningTaskStatus = components["schemas"]["CleaningTaskStatus"];

/** One cleaning task row (PRD §11, §24). */
export interface CleaningTask {
  id: string;
  propertyId: string;
  assignedCleanerId: string | null;
  status: CleaningTaskStatus;
  scheduledStart: IsoDateTime | null;
  scheduledEnd: IsoDateTime | null;
  createdAt: IsoDateTime;
}

/**
 * A cleaner from the tenant's `role=CLEANER` catalog. `isActive` is carried
 * rather than filtered away at the boundary: an inactive cleaner still has to
 * resolve her name on an old task (R2.2), and only the assignment control's
 * candidate list narrows to the active ones (R4.2, design D4).
 */
export interface CleanerSummary {
  id: string;
  name: string;
  isActive: boolean;
}

/** A property from the tenant's catalog, identified as R2.1 requires. */
export interface PropertySummary {
  id: string;
  name: string;
  internalCode: string;
}

/** Server-side filters for the task list (R3.1–R3.3); never applied in the client. */
export interface CleaningTaskFilters {
  propertyId?: string;
  status?: CleaningTaskStatus;
}
