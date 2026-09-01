import type { components } from "@/lib/api/generated/openapi";

/**
 * UI DTOs for the cleaner's task app (design D3).
 *
 * Every type here is an alias of a generated schema — never a hand-written copy
 * of its shape — so that adding a tenth `CleaningTaskStatus` member in the
 * backend breaks this build the moment the contract is regenerated (D6).
 *
 * DTO names use camelCase even when the wire is snake_case, and the boundary
 * (snake→camel) lives in the HTTP source. UI code never imports
 * `components["schemas"][...]` directly — only through these aliases.
 */

/** ISO-8601 timestamp as the wire publishes it. */
export type IsoDateTime = string;

/** The nine operational states of a cleaning task (R1.5, D5). */
export type CleaningTaskStatus = components["schemas"]["CleaningTaskStatus"];

/** The validation status that the manager writes; the cleaner only reads it. */
export type CleaningValidationStatus =
  components["schemas"]["CleaningValidationStatus"];

/** The single canonical task, as `GET /cleaning-tasks/{id}` returns it (R2.1). */
export interface CleaningTask {
  id: string;
  propertyId: string;
  reservationId: string | null;
  assignedCleanerId: string | null;
  status: CleaningTaskStatus;
  scheduledStart: IsoDateTime | null;
  scheduledEnd: IsoDateTime | null;
  acceptedAt: IsoDateTime | null;
  startedAt: IsoDateTime | null;
  completedAt: IsoDateTime | null;
  validationStatus: CleaningValidationStatus;
  createdAt: IsoDateTime;
}

/**
 * One row of the listing (`CleaningTaskListItemResponse`). It carries the same
 * fields as `CleaningTask` plus the backend's pre-flight verdict — for a
 * cleaner that pre-flight is irrelevant, but the wire shape is one and the row
 * reuses the same mapper for everything that lists.
 */
export type CleaningTaskListItem = CleaningTask;

/**
 * The projection the backend serves for the cleaner's row context (R1.2,
 * R2.2). It carries the six address fields, the timezone and the two instants
 * that bound the work. There is no `access_notes`: the cleaner has no
 * `READ_PROPERTIES` and the projection is what the contract declares.
 */
export interface CleaningTaskContext {
  propertyName: string;
  propertyInternalCode: string;
  addressLine1: string | null;
  addressLine2: string | null;
  city: string | null;
  province: string | null;
  postalCode: string | null;
  country: string;
  timezone: string;
  checkoutAt: IsoDateTime | null;
  nextCheckinDeadline: IsoDateTime | null;
}

/** One item of the checklist (R2.3). */
export interface CleaningChecklistItem {
  itemId: string;
  label: string;
  required: boolean;
  completed: boolean;
  completedAt: IsoDateTime | null;
  completedBy: string | null;
}

/** The full checklist of one task (R2.3). */
export interface CleaningChecklist {
  data: CleaningChecklistItem[];
}

/** One photo category the task's template declares (R2.4). */
export interface PhotoRequirementState {
  photoType: string;
  label: string;
  required: boolean;
  uploaded: boolean;
}

/** The collection of categories the template declares (R2.4). */
export interface PhotoRequirementsResponse {
  data: PhotoRequirementState[];
}

/** One uploaded photo (R2.5). `url` is a signed URL minted for this response. */
export interface CleaningPhoto {
  id: string;
  cleaningTaskId: string;
  photoType: string;
  uploadedBy: string;
  createdAt: IsoDateTime;
  /**
   * Verbatim from the wire — the `<img src>` paints it as is. There is no
   * `storage_key` and no reconstruction here: recovery from a stale signature
   * is re-listing (design D10, R2.5).
   */
  url: string;
}

/**
 * The wire-shaped list envelope. Renamed to camelCase at the boundary.
 *
 * `perPage` is what the UI moves; `totalPages` is what the paginator decides
 * from. Both come from the backend — never derived client-side.
 */
export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
}

/**
 * The shape of `CleanerDataSource.listTasks` — one page, filtered server-side.
 * `status` is a single value (the contract does not admit several, R1.5).
 */
export interface CleaningFilters {
  status?: CleaningTaskStatus;
}

/** Body of `POST /cleaning-tasks/{id}/incidents` (R6.1). */
export interface CleaningIncidentReportInput {
  title: string;
  description: string;
}

/** Acknowledgement of a `201` on `POST /incidents` (R6.3, D8). */
export interface CleaningIncidentReportAck {
  id: string;
  status: components["schemas"]["IncidentStatus"];
  createdAt: IsoDateTime;
}