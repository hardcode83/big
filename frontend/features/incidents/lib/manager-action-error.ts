import { ApiError } from "@/lib/api";

import type { IncidentStatus } from "../data";
import { conflictReason } from "./conflict-reason";
import type { ManagerAction } from "./manager-actions";

/**
 * The bare reason strings `managerActionMessage` can return (design D9). Not
 * full i18n keys — section 5 interpolates one of these into something like
 * `t(\`incidents:manager.conflict.${reason}\`)` for the first four, or
 * `t(\`incidents:manager.errors.${reason}\`)` for the last two, uniformly.
 *
 * `"closed" | "awaiting-owner" | "out-of-order"` are `conflictReason`'s own
 * three values, reused rather than re-declared. `"triage-not-classified"` is
 * the one case this function distinguishes from the generic `"out-of-order"`
 * (see below). `"invalid-technician"` and `"invalid-cost"` are the two `422`
 * cases, one per mutation.
 */
export type ManagerActionErrorReason =
  | "closed"
  | "awaiting-owner"
  | "out-of-order"
  | "triage-not-classified"
  | "invalid-technician"
  | "invalid-cost";

/**
 * Maps a mutation error to a localizable reason (R2.5, R3.4, R6.1, design D9).
 * A pure function with no React/i18n dependency — it returns a translation
 * key **fragment**, never `error.message` (the technical envelope text is
 * NEVER rendered).
 *
 * - `409`: read from the **refreshed** status via `conflictReason`, exactly
 *   like `tech-cycle-actions.tsx`'s `messageFor` — the three refusals all
 *   share `code: "CONFLICT"` on the wire and differ only in an English
 *   `message`. The one nuance (D9): when `action === "triage"` and the
 *   refreshed status is `OPEN`, `conflictReason` would answer
 *   `"out-of-order"` — but that status has *not* changed (this is the only
 *   `409` this change can produce on an incident that is still `OPEN`), so
 *   the generic "the status changed" text would be false. That combination
 *   answers `"triage-not-classified"` instead: category and severity must be
 *   set before a cost can be triaged.
 * - `422` on `assign`: `InvalidTechnicianError` (the chosen user is not an
 *   `ACTIVE` `TECHNICIAN` of the tenant) → `"invalid-technician"`.
 * - `422` on `triage`: `MaintenanceValidationError` (e.g. a negative cost
 *   that slipped past the client guard) → `"invalid-cost"`.
 *   Both 422s share `ErrorCode.VALIDATION_ERROR` on the wire
 *   (`backend/app/maintenance/api/errors.py:46,53`) — `error.code` cannot
 *   tell them apart, so the distinction comes from `action`, not from
 *   inspecting the error.
 * - `403` is not handled here: that hides the whole section (section 5's
 *   job), not a message this function produces.
 * - Anything else (no error, an error this function does not recognize)
 *   returns `undefined` — the caller falls back to a generic message.
 */
export function managerActionMessage(
  error: unknown,
  refreshedStatus: IncidentStatus,
  action: ManagerAction,
): ManagerActionErrorReason | undefined {
  if (!(error instanceof ApiError)) {
    return undefined;
  }
  if (error.status === 409) {
    const reason = conflictReason(refreshedStatus);
    if (action === "triage" && refreshedStatus === "OPEN" && reason === "out-of-order") {
      return "triage-not-classified";
    }
    return reason;
  }
  if (error.status === 422 && action === "assign") {
    return "invalid-technician";
  }
  if (error.status === 422 && action === "triage") {
    return "invalid-cost";
  }
  return undefined;
}
