import type { CleaningTaskStatus } from "../data";

/**
 * The seven operations `EXECUTE_CLEANING_TASKS` reaches (design D6, R3.1).
 *
 * `completeChecklistItem` and `uploadPhoto` are per-item/per-entry actions, not
 * header buttons, but they live in this table because what decides whether
 * they are on offer is the status — exactly like the other five. The action
 * bar reads `CLEANER_ACTIONS[status]` and only renders the ones the bar owns
 * (`accept`, `reject`, `start`, `complete`, `reportIncident`); the per-row
 * controls read the rest separately to gate their visibility.
 */
export type CleanerAction =
  | "accept"
  | "reject"
  | "start"
  | "complete"
  | "completeChecklistItem"
  | "uploadPhoto"
  | "reportIncident";

/**
 * Status → the actions on offer (R3.1, design D6). This is the reading of
 * `_TRANS` in the cleaning state machine (`sdd/specs/cleaning.md`), narrowed to
 * the operations the cleaner's permission reaches.
 *
 * A `Record` over `CleaningTaskStatus` — which comes from the generated
 * contract — so adding a tenth status to the backend breaks the build instead
 * of leaving a phantom button. This is presentation of the contract, not
 * authorization: the backend refuses with a `409` regardless (R3.4).
 */
const ACTIONS: Record<CleaningTaskStatus, readonly CleanerAction[]> = {
  CREATED: [],
  ASSIGNED: ["accept", "reject"],
  ACCEPTED: ["start"],
  IN_PROGRESS: [
    "complete",
    "reportIncident",
    "completeChecklistItem",
    "uploadPhoto",
  ],
  PENDING_REVIEW: [],
  COMPLETED: [],
  REJECTED: [],
  CANCELLED: [],
  FAILED: [],
};

export const CLEANER_ACTIONS: Readonly<
  Record<CleaningTaskStatus, readonly CleanerAction[]>
> = Object.freeze(ACTIONS);

/**
 * `Object.hasOwn` rather than a bare lookup: the status arrives from the wire
 * unvalidated, so a status unknown to the compiled frontend returns "no
 * actions" instead of an `undefined` that would blow up the render (same
 * pattern as `tech-actions.ts`).
 */
export function cleanerActions(
  status: CleaningTaskStatus,
): readonly CleanerAction[] {
  return Object.hasOwn(ACTIONS, status) ? ACTIONS[status] : [];
}

/** Why no action is on offer (R3.1, D6). */
export type CleanerNoActionReason =
  | "pendingReview"
  | "completed"
  | "rejected"
  | "cancelled"
  | "failed"
  | "notActionable";

const NO_ACTION_REASON: Record<CleaningTaskStatus, CleanerNoActionReason> = {
  PENDING_REVIEW: "pendingReview",
  COMPLETED: "completed",
  REJECTED: "rejected",
  CANCELLED: "cancelled",
  // The validation is the manager's, not the cleaner's — design D6's table.
  FAILED: "failed",
  CREATED: "notActionable",
  ASSIGNED: "notActionable",
  ACCEPTED: "notActionable",
  IN_PROGRESS: "notActionable",
};

/**
 * `Object.hasOwn` for the same reason `cleanerActions` does — a tenth status
 * degrades to `notActionable` instead of throwing.
 */
export function cleanerNoActionReason(
  status: CleaningTaskStatus,
): CleanerNoActionReason {
  return Object.hasOwn(NO_ACTION_REASON, status)
    ? NO_ACTION_REASON[status]
    : "notActionable";
}

/**
 * Whether the status admits a photo upload (R5.1, D9). A `Record` rather than
 * a loose `string[]`: the action table is the one place that decides what a
 * status offers, and an untyped array is invisible to the compiler.
 */
const ACCEPTS_PHOTO_UPLOAD: Record<CleaningTaskStatus, boolean> = {
  CREATED: false,
  ASSIGNED: false,
  ACCEPTED: false,
  IN_PROGRESS: true,
  PENDING_REVIEW: false,
  COMPLETED: false,
  REJECTED: false,
  CANCELLED: false,
  FAILED: false,
};

export function cleanerAcceptsPhotoUpload(
  status: CleaningTaskStatus,
): boolean {
  return Object.hasOwn(ACCEPTS_PHOTO_UPLOAD, status)
    ? ACCEPTS_PHOTO_UPLOAD[status]
    : false;
}

/**
 * Whether the status admits reporting an incident (R6.1).
 * `INCIDENT_REPORTABLE_STATUSES = { ASSIGNED, ACCEPTED, IN_PROGRESS }`. The
 * 422 from the backend is the authority (R6.5), but this is what decides
 * whether to render the trigger button in the first place.
 */
const INCIDENT_REPORTABLE: Record<CleaningTaskStatus, boolean> = {
  CREATED: false,
  ASSIGNED: true,
  ACCEPTED: true,
  IN_PROGRESS: true,
  PENDING_REVIEW: false,
  COMPLETED: false,
  REJECTED: false,
  CANCELLED: false,
  FAILED: false,
};

export function cleanerAcceptsIncidentReport(
  status: CleaningTaskStatus,
): boolean {
  return Object.hasOwn(INCIDENT_REPORTABLE, status)
    ? INCIDENT_REPORTABLE[status]
    : false;
}

/**
 * Whether the status admits ticking a checklist item (R4.1). Per-item,
 * per-status.
 */
const ACCEPTS_CHECKLIST_ITEM: Record<CleaningTaskStatus, boolean> = {
  CREATED: false,
  ASSIGNED: false,
  ACCEPTED: false,
  IN_PROGRESS: true,
  PENDING_REVIEW: false,
  COMPLETED: false,
  REJECTED: false,
  CANCELLED: false,
  FAILED: false,
};

export function cleanerAcceptsChecklistItem(
  status: CleaningTaskStatus,
): boolean {
  return Object.hasOwn(ACCEPTS_CHECKLIST_ITEM, status)
    ? ACCEPTS_CHECKLIST_ITEM[status]
    : false;
}