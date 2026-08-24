import { ApiError } from "@/lib/api";

/**
 * Maps a failed assignment to a translated message key (design D10).
 *
 * The choice is made by HTTP **status** and, within `409`, by the envelope's `code` —
 * never by `ApiError.message`: that message is technical and in English
 * (`lib/api/errors.ts`), so R5.1 forbids painting it. Nothing from the backend's body
 * reaches the screen through here except the code, which is a closed vocabulary the
 * published contract declares as an enum.
 *
 * The four statuses come from `backend/app/cleaning/api/errors.py`:
 *   403 — the caller lacks `MANAGE_CLEANING_TASKS` (R4.4)
 *   404 — `CleaningTaskNotFoundError` (R4.5)
 *   409 — two different causes, which is why this file no longer decides by status alone
 *         (`cleaning-assign-preconditions` R2.1-R2.3, design D7)
 *   422 — `CleaningValidationError`: the chosen person is no longer an active
 *         CLEANER of this tenant. Reachable whenever someone is deactivated while
 *         the cached catalog still offers her, and it is why 422 has its own entry
 *         instead of falling into the generic "it failed" (design D10).
 */
const KEY_BY_STATUS: Record<number, string> = {
  403: "cleaning:assign.error.forbidden",
  404: "cleaning:assign.error.notFound",
  409: "cleaning:assign.error.conflict",
  422: "cleaning:assign.error.invalid",
};

/**
 * Refinement consulted **only** when the status is `409`, the one status two different
 * causes share.
 *
 * Until `cleaning-assign-preconditions` both answered `CONFLICT`, and this file said "that
 * task no longer accepts a change of assignment" for either — which was false exactly when
 * it mattered, because the first assignment of a `CREATED` task is refused by the
 * **property**, not by the task. The backend now separates them and this table is where
 * that separation becomes a different sentence on screen.
 *
 * Anything not listed here — `CONFLICT`, and equally a code this build has never heard of —
 * falls through to the status key, i.e. the message that shipped before. That fallback is
 * the deploy-skew window, not laziness: a frontend older than its backend meets a code it
 * cannot know, and degrades to today's wording instead of showing nothing. Same reasoning
 * as the `?? "gray"` of `lib/task-status.ts`, which already separates a compile-time
 * guarantee from a runtime one.
 */
const KEY_BY_CONFLICT_CODE: Record<string, string> = {
  PROPERTY_STATE_CONFLICT: "cleaning:assign.error.propertyState",
};

export const GENERIC_ASSIGN_ERROR_KEY = "cleaning:assign.error.generic";

export function assignErrorKey(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return GENERIC_ASSIGN_ERROR_KEY;
  }
  if (error.status === 409) {
    const refined = KEY_BY_CONFLICT_CODE[error.code];
    if (refined) {
      return refined;
    }
  }
  return KEY_BY_STATUS[error.status] ?? GENERIC_ASSIGN_ERROR_KEY;
}
