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

/**
 * Why an assignment cannot happen right now. Aliased from the generated union for the
 * same reason as `CleaningTaskStatus` above and never hand-copied: a third member on the
 * backend has to break this build once the contract is regenerated.
 */
export type CleaningAssignmentBlocker =
  components["schemas"]["CleaningAssignmentBlocker"];

/**
 * Alias of the generated union, same discipline as `CleaningTaskStatus` above: a
 * fifth member on the backend has to break this build once the contract is
 * regenerated, never a hand-copied list.
 */
export type CleaningValidationStatus =
  components["schemas"]["CleaningValidationStatus"];

/**
 * The only two verdicts a manager can actually emit (R3.2) — `PENDING` and
 * `WAIVED` are states the backend can be in, never a value this feature's
 * validate control sends.
 */
export type CleaningValidationVerdict = Extract<
  CleaningValidationStatus,
  "PASSED" | "FAILED"
>;

/**
 * Alias of the generated union (design D2): a state renamed on the backend has
 * to break this build once the contract is regenerated, same discipline as
 * `CleaningTaskStatus` above.
 */
export type PropertyOperationalState =
  components["schemas"]["PropertyOperationalState"];

/**
 * One cleaning task (PRD §11, §24) — what every single-task endpoint returns.
 *
 * `completedAt`, `validationStatus` and `validatedAt` live here and not only on
 * `CleaningTaskListItem` (design D3): both `CleaningTaskResponse` (create,
 * validate, cancel) and `CleaningTaskListItemResponse` (the listing) publish
 * all three identically.
 */
export interface CleaningTask {
  id: string;
  propertyId: string;
  assignedCleanerId: string | null;
  status: CleaningTaskStatus;
  scheduledStart: IsoDateTime | null;
  scheduledEnd: IsoDateTime | null;
  createdAt: IsoDateTime;
  completedAt: IsoDateTime | null;
  validationStatus: CleaningValidationStatus;
  validatedAt: IsoDateTime | null;
}

/**
 * One **row of the listing**: a task plus the backend's pre-flight verdict.
 *
 * Split from `CleaningTask` exactly as the backend splits `CleaningTaskListItemResponse`
 * from `CleaningTaskResponse` (design D5/D7). `assignTask` returns the base shape, because
 * the `PATCH` does not answer this question — and it does not need to: the mutation
 * invalidates the whole task-key prefix, so the refetch brings fresh verdicts for the
 * entire page.
 *
 * `null` means "nothing known to be blocking", which also covers a flat whose state the
 * page read could not resolve. It is a courtesy, never a permission: the backend refuses
 * again on the mutation and that refusal is the authority (R3.3).
 */
export interface CleaningTaskListItem extends CleaningTask {
  assignmentBlockedBy: CleaningAssignmentBlocker | null;
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

/**
 * A property from the tenant's catalog, identified as R2.1 requires.
 *
 * `currentOperationalState` already travels in `PropertyListItemResponse` at no
 * extra request cost (design D2); it is what the non-assignability notice (R2.1)
 * derives from.
 */
export interface PropertySummary {
  id: string;
  name: string;
  internalCode: string;
  currentOperationalState: PropertyOperationalState;
}

/** Server-side filters for the task list (R3.1–R3.3); never applied in the client. */
export interface CleaningTaskFilters {
  propertyId?: string;
  status?: CleaningTaskStatus;
}

/**
 * The only three fields R1.2 allows the create control to send. `propertyId` is
 * mandatory; the scheduled window is optional and, unlike the rest of this
 * feature's inputs, still camelCase to ISO strings — `reservation_id` is never
 * part of this shape (ASSUMPTION 2).
 */
export interface CreateCleaningTaskInput {
  propertyId: string;
  scheduledStart?: string;
  scheduledEnd?: string;
}
