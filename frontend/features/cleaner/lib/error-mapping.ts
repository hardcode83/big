import { ApiError } from "@/lib/api";

/**
 * The cleaner's twelve error "kinds". Each is a single source of a refused
 * request — read, mutation, file upload, form post — and each maps to its own
 * localized copy via the `cleaner` namespace (R5.5, R6.5, R7.3, R8.2).
 *
 * The `kind` discriminator is what lets the i18n key be specific per source:
 * a `409` on a `completeChecklistItem` is a different copy from a `409` on a
 * `complete`. Same status, different surface, different message.
 */
export type CleanerErrorKind =
  | "task"
  | "context"
  | "checklist"
  | "photoRequirements"
  | "photos"
  | "accept"
  | "reject"
  | "start"
  | "complete"
  | "completeChecklistItem"
  | "uploadPhoto"
  | "reportIncident";

export type CleanerViewState = "loading" | "empty" | "error" | "not-found";

export interface CleanerErrorMap {
  state: CleanerViewState;
  messageKey: string;
}

/**
 * What the screen does with a refused request (D12, R5.5, R6.5, R7.3, R8.2).
 *
 * `401` keeps the loading branch (the auth flow owns session expiration).
 * `404` is the "task not available" branch: an unknown id, another tenant's
 * task and another cleaner's task are all answered this way, indistinguishably
 * — the view offers «Volver a mis tareas» instead of pretending the task
 * exists (R2.8).
 *
 * `409` does NOT carry a specific copy here — that belongs to the
 * `conflictReason` helper (D7). The conflict branch is decided by the view
 * from the refreshed task, not from the envelope (R7.3). What this function
 * owns is the **generic** "the action no longer fits" copy that R3.4 / R5.5
 * / R6.5 require.
 *
 * The function NEVER returns the raw envelope `message` (R6.5 / R7.3).
 */
export function mapCleanerError(
  error: unknown,
  kind: CleanerErrorKind,
): CleanerErrorMap {
  if (!(error instanceof ApiError)) {
    return genericError(kind);
  }
  // 401 — let the auth flow own it.
  if (error.status === 401) {
    return { state: "loading", messageKey: "errors.unauthorized" };
  }
  // 404 — task not available. Same copy across every read kind.
  if (error.status === 404) {
    if (
      kind === "task" ||
      kind === "context" ||
      kind === "checklist" ||
      kind === "photoRequirements" ||
      kind === "photos"
    ) {
      return {
        state: "not-found",
        messageKey: "detail.unavailable.title",
      };
    }
    // For mutation kinds, a 404 is the "this entry no longer exists" case
    // (e.g. a checklist item id that was edited away while the cleaner worked
    // — R4.3). The mutation hook refreshes the checklist and the screen
    // re-renders; no ErrorState needed.
    if (kind === "completeChecklistItem") {
      return {
        state: "error",
        messageKey: "checklist.errors.notFound",
      };
    }
    return genericError(kind);
  }
  // 413 — too large (R5.5).
  if (error.status === 413 && kind === "uploadPhoto") {
    return {
      state: "error",
      messageKey: "upload.errors.tooLarge",
    };
  }
  // 422 — validation error. Photo upload names the supported formats (R5.5);
  // incident report refers to title/description length bounds (R6.2).
  if (error.status === 422) {
    if (kind === "uploadPhoto") {
      return {
        state: "error",
        messageKey: "upload.errors.unsupportedFormat",
      };
    }
    if (kind === "reportIncident") {
      return {
        state: "error",
        messageKey: "incidentReport.errors.titleTooLong",
      };
    }
    return genericError(kind);
  }
  // 502 — storage failure on photo upload (R5.5).
  if (error.status === 502 && kind === "uploadPhoto") {
    return {
      state: "error",
      messageKey: "upload.errors.storage",
    };
  }
  // 409 — conflict: this branch is decided by the view from the refreshed
  // task, not from the envelope (R7.3). The mutation hooks invalidate the
  // detail so the consumer can read the post-refresh status; this helper
  // surfaces the generic conflict copy that R3.4 / R5.5 / R6.5 require.
  if (error.status === 409) {
    if (kind === "uploadPhoto") {
      return {
        state: "error",
        messageKey: "upload.errors.conflict",
      };
    }
    if (kind === "reportIncident") {
      return {
        state: "error",
        messageKey: "incidentReport.errors.conflict",
      };
    }
    if (
      kind === "accept" ||
      kind === "reject" ||
      kind === "start" ||
      kind === "complete" ||
      kind === "completeChecklistItem"
    ) {
      return {
        state: "error",
        messageKey: "actions.errors.conflict",
      };
    }
    return genericError(kind);
  }
  return genericError(kind);
}

function genericError(kind: CleanerErrorKind): CleanerErrorMap {
  // Reads on a list whose first page failed — R1.7 says "no retry on 4xx" but
  // the message copy is shared with the action bar generic copy for everything
  // else.
  switch (kind) {
    case "task":
      return {
        state: "error",
        messageKey: "list.error.title",
      };
    case "context":
    case "checklist":
    case "photoRequirements":
    case "photos":
      return {
        state: "error",
        messageKey: "detail.error.title",
      };
    default:
      return {
        state: "error",
        messageKey: "actions.errors.generic",
      };
  }
}