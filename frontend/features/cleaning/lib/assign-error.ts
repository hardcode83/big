import { ApiError } from "@/lib/api";

/**
 * Maps a failed assignment to a translated message key (design D10).
 *
 * The choice is made by HTTP **status**, never by `ApiError.message`: that message
 * is technical and in English (`lib/api/errors.ts`), so R5.1 forbids painting it.
 * Nothing from the backend's body reaches the screen through here.
 *
 * The four statuses come from `backend/app/cleaning/api/errors.py`:
 *   403 — the caller lacks `MANAGE_CLEANING_TASKS` (R4.4)
 *   404 — `CleaningTaskNotFoundError` (R4.5)
 *   409 — `InvalidCleaningTransitionError`, e.g. assigning an already ACCEPTED task (R4.5)
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

export const GENERIC_ASSIGN_ERROR_KEY = "cleaning:assign.error.generic";

export function assignErrorKey(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return GENERIC_ASSIGN_ERROR_KEY;
  }
  return KEY_BY_STATUS[error.status] ?? GENERIC_ASSIGN_ERROR_KEY;
}
