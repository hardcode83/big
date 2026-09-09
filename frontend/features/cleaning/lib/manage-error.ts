import { ApiError } from "@/lib/api";

/**
 * Error-key mapping for the three manager mutations this change adds — create, validate,
 * cancel (design D8) — one table each, resolved the same way `lib/assign-error.ts` resolves
 * assignment failures: by HTTP **status** and, within `409`, by the envelope's `code`, never
 * by `ApiError.message` (technical, in English, `lib/api/errors.ts`). `assign-error.ts` is
 * left untouched (design D8): its 409 refinement is specific to assignment and this file
 * does not generalize over it, it duplicates the small amount of shared shape instead.
 *
 * The four statuses per operation come from `backend/app/cleaning/api/errors.py` and the use
 * cases in `backend/app/cleaning/application/use_cases.py`:
 *
 *   create   — 403 no permission; 404 **ambiguous**: `PropertyNotFoundError` (the property)
 *              and `ChecklistTemplateNotFoundError` (no active checklist template for it)
 *              both answer 404 with the same `ErrorCode.NOT_FOUND`, so the client cannot
 *              tell them apart without a backend change — the copy names both causes instead
 *              of guessing one; 409 `AmbiguousChecklistTemplateError` (`CONFLICT`), the
 *              property matches more than one active template; 422 an invalid request body
 *              (FastAPI validation, not a domain error).
 *   validate — 403 no permission; 404 `CleaningTaskNotFoundError`; 409 the task is no longer
 *              `COMPLETED` (`InvalidCleaningTransitionError`, `CONFLICT`) —
 *              `record_manual_validation` requires `COMPLETED` before recording a verdict.
 *   cancel   — 403 no permission; 404 `CleaningTaskNotFoundError`; 409 two different causes
 *              sharing the status, distinguished by `code` exactly like `assign-error.ts`
 *              distinguishes them for assignment: the task is already terminal
 *              (`InvalidCleaningTransitionError`, `CONFLICT` — `cancel()` only accepts
 *              `LIVE_STATUSES`), or the property's state refuses the transition
 *              (`PropertyStateBlocksCleaningError`, `PROPERTY_STATE_CONFLICT`, raised by
 *              `PropertyStateMachine` while resolving `CLEANING_CANCELLED`).
 */
export interface ManageErrorTable {
  readonly byStatus: Readonly<Record<number, string>>;
  /** Consulted only when the status is 409 — the one status more than one cause shares. */
  readonly byConflictCode?: Readonly<Record<string, string>>;
}

export const CREATE_ERROR_TABLE: ManageErrorTable = {
  byStatus: {
    403: "cleaning:create.error.forbidden",
    404: "cleaning:create.error.notFound",
    409: "cleaning:create.error.ambiguousTemplate",
    422: "cleaning:create.error.invalid",
  },
};
export const GENERIC_CREATE_ERROR_KEY = "cleaning:create.error.generic";

export const VALIDATE_ERROR_TABLE: ManageErrorTable = {
  byStatus: {
    403: "cleaning:validate.error.forbidden",
    404: "cleaning:validate.error.notFound",
    409: "cleaning:validate.error.notCompleted",
  },
};
export const GENERIC_VALIDATE_ERROR_KEY = "cleaning:validate.error.generic";

export const CANCEL_ERROR_TABLE: ManageErrorTable = {
  byStatus: {
    403: "cleaning:cancel.error.forbidden",
    404: "cleaning:cancel.error.notFound",
    409: "cleaning:cancel.error.terminal",
  },
  byConflictCode: {
    PROPERTY_STATE_CONFLICT: "cleaning:cancel.error.propertyState",
  },
};
export const GENERIC_CANCEL_ERROR_KEY = "cleaning:cancel.error.generic";

/**
 * Resolves an error to a translated message key for one of the three tables above.
 *
 * Anything not listed — a `409` `code` this build has never heard of, or a status the
 * table does not cover — falls through to `genericKey`, the same deploy-skew reasoning
 * `assign-error.ts` documents: degrade to a generic wording instead of showing nothing or
 * throwing. An error that is not an `ApiError` at all (a network failure, a bug) is
 * likewise generic.
 */
export function keyForStatus(
  error: unknown,
  table: ManageErrorTable,
  genericKey: string,
): string {
  if (!(error instanceof ApiError)) {
    return genericKey;
  }
  if (error.status === 409 && table.byConflictCode) {
    const refined = table.byConflictCode[error.code];
    if (refined) {
      return refined;
    }
  }
  return table.byStatus[error.status] ?? genericKey;
}
