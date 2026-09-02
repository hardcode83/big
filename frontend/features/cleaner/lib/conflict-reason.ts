import type {
  CleaningChecklist,
  CleaningTask,
  PhotoRequirementsResponse,
} from "../data";

/**
 * Why a `409` refused the cleaner's close, derived from the **refreshed**
 * task state (design D7, R7.3).
 *
 * It is read from the refreshed task and not from the error envelope because
 * the three refusals the backend distinguishes (`CleaningTask.complete()` in
 * `backend/app/cleaning/domain/entities.py`) all share `code: "CONFLICT"` and
 * differ only in an English technical `message`, which R7.3 forbids
 * rendering. The refreshed task is also the more useful answer: it says why
 * the action does not fit *now*.
 *
 * The order is the one the domain decides in `CompletionEvidenceGatherer` —
 * items first, photos second, critical incident third — because that is the
 * order the backend stops looking once it has its reason.
 */
export type ConflictReason =
  | "missing-required-items"
  | "missing-required-photos"
  | "critical-incident";

/**
 * Whether the checklist still has pending required items (R7.3).
 *
 * The backend enumerates the missing items in stable order; we mirror that
 * here against the **post-refresh** checklist the client received.
 */
export function hasMissingRequiredItems(
  checklist: CleaningChecklist,
): boolean {
  return checklist.data.some((item) => item.required && !item.completed);
}

/**
 * Whether the photo requirements still have pending required entries (R7.3).
 */
export function hasMissingRequiredPhotos(
  requirements: PhotoRequirementsResponse,
): boolean {
  return requirements.data.some(
    (entry) => entry.required && !entry.uploaded,
  );
}

/**
 * Decides which of the three clauses the close refused, in the order the
 * domain does.
 *
 * The third clause — `critical-incident` — does not look at the task itself:
 * the task carries no incident list (`CLEANER` has no `READ_INCIDENTS`), and
 * the `409` envelope does not name the incident for the same rule-11 reason.
 * The cleaner UI must simply show the "there's a critical incident" copy
 * without identifying the incident (D7, R7.3).
 */
export function conflictReason(
  checklist: CleaningChecklist,
  requirements: PhotoRequirementsResponse,
): ConflictReason {
  if (hasMissingRequiredItems(checklist)) {
    return "missing-required-items";
  }
  if (hasMissingRequiredPhotos(requirements)) {
    return "missing-required-photos";
  }
  return "critical-incident";
}

/**
 * The set of `item_id`s that the close would refuse for, in the order the
 * backend enumerates them (R7.3). The UI highlights these on the failed
 * close (R7.3): each missing required item is rendered as the actionable
 * thing to fix.
 */
export function pendingRequiredItemIds(
  checklist: CleaningChecklist,
): string[] {
  return checklist.data
    .filter((item) => item.required && !item.completed)
    .map((item) => item.itemId);
}

/**
 * The set of `photo_type`s that the close would refuse for, in the order the
 * backend enumerates them (R7.3).
 */
export function pendingRequiredPhotoTypes(
  requirements: PhotoRequirementsResponse,
): string[] {
  return requirements.data
    .filter((entry) => entry.required && !entry.uploaded)
    .map((entry) => entry.photoType);
}

/**
 * Whether the task is in a status that would refuse a `409` close — i.e. a
 * state mismatch where the backend says "ya no encaja". The view checks this
 * against the refreshed task to decide which copy to render (R3.4, R7.3).
 */
export function taskIsClosed(task: CleaningTask): boolean {
  return (
    task.status === "COMPLETED" ||
    task.status === "REJECTED" ||
    task.status === "CANCELLED" ||
    task.status === "FAILED"
  );
}