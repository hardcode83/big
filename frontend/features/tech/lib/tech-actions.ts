import type { IncidentStatus } from "@/features/incidents";

/**
 * The six operations `EXECUTE_INCIDENTS` reaches. `resolve` is the close form
 * of R4 rather than a plain button, but it belongs in this table because what
 * decides whether it is on offer is the status, exactly like the other five.
 */
export type CycleAction =
  | "accept"
  | "reject"
  | "en-route"
  | "wait-parts"
  | "resume"
  | "resolve";

/**
 * Status → the actions on offer (R3.1, design D6). This is the reading of
 * `_TRANSITIONS` in `backend/app/maintenance/domain/entities.py`, narrowed to
 * the six operations the technician's permission reaches.
 *
 * A `Record` over `IncidentStatus` — which comes from the generated contract —
 * so adding a tenth status to the backend breaks the build instead of leaving a
 * phantom button. This is presentation of the contract, not authorization: the
 * backend refuses with a `409` regardless (R6.5).
 */
const ACTIONS: Record<IncidentStatus, readonly CycleAction[]> = {
  ASSIGNED: ["accept", "reject"],
  ACCEPTED: ["en-route", "reject"],
  IN_PROGRESS: ["wait-parts", "resolve"],
  WAITING_EXTERNAL_PARTS: ["resume"],
  AWAITING_OWNER_APPROVAL: [],
  RESOLVED: [],
  CANCELLED: [],
  // Not reachable from this screen: with no assignee they never get here.
  OPEN: [],
  CLASSIFIED: [],
};

export const TECH_ACTIONS: Readonly<Record<IncidentStatus, readonly CycleAction[]>> =
  Object.freeze(ACTIONS);

/**
 * `Object.hasOwn` rather than a bare lookup, following `severityColorGroup`:
 * the status arrives from the wire unvalidated, so a status unknown to the
 * compiled frontend returns "no actions" instead of an `undefined` that would
 * blow up the render.
 */
export function techActions(status: IncidentStatus): readonly CycleAction[] {
  return Object.hasOwn(ACTIONS, status) ? ACTIONS[status] : [];
}
