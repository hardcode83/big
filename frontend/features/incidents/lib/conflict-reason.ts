import type { IncidentStatus } from "../data";

/**
 * Why a `409` refused an action, derived from the incident's **refreshed**
 * status (design D7).
 *
 * It is read from the status and not from the error because the three refusals
 * the backend distinguishes all share `code: "CONFLICT"`
 * (`backend/app/maintenance/api/errors.py`) and differ only in an English
 * technical `message`, which R6.2 forbids rendering. The refreshed status is
 * also the more useful answer: it says why the action does not fit *now*.
 */
export type ConflictReason = "closed" | "awaiting-owner" | "out-of-order";

const CLOSED_STATUSES: readonly IncidentStatus[] = ["RESOLVED", "CANCELLED"];

/**
 * The order is the one the domain decides in
 * `Incident._refuse_if_closed_or_awaiting_owner`: closed first, waiting for the
 * owner second, out of sequence for whatever survives both. The same function
 * serves the cycle and the photo upload, whose three cases are the same three
 * in the same order (`Incident.ensure_accepts_photo`).
 */
export function conflictReason(status: IncidentStatus): ConflictReason {
  if (CLOSED_STATUSES.includes(status)) {
    return "closed";
  }
  if (status === "AWAITING_OWNER_APPROVAL") {
    return "awaiting-owner";
  }
  return "out-of-order";
}
