import type { IncidentStatus } from "../data";

/**
 * The four operations `MANAGE_INCIDENTS` reaches (R1.1-R1.5, design D6):
 * relaunch the classifier, assign/reassign a technician, triage (correct
 * category/severity/estimated cost) and cancel.
 */
export type ManagerAction = "classify" | "assign" | "triage" | "cancel";

/**
 * Status → the actions on offer (R1.3, design D6). Mirrors `TECH_ACTIONS` in
 * `features/tech/lib/tech-actions.ts`: a `Record` over `IncidentStatus` —
 * which comes from the generated contract — so a tenth backend status breaks
 * the build instead of leaving a phantom button.
 *
 * This is presentation of the contract, not authorization (R1.6): the
 * backend refuses with `403`/`409` regardless of what this table offers.
 */
const ACTIONS: Record<IncidentStatus, readonly ManagerAction[]> = {
  OPEN: ["classify", "triage", "cancel"],
  CLASSIFIED: ["assign", "triage", "cancel"],
  ASSIGNED: ["assign", "triage", "cancel"],
  ACCEPTED: ["assign", "triage", "cancel"],
  IN_PROGRESS: ["assign", "triage", "cancel"],
  WAITING_EXTERNAL_PARTS: ["assign", "triage", "cancel"],
  AWAITING_OWNER_APPROVAL: ["cancel"],
  RESOLVED: [],
  CANCELLED: [],
};

export const MANAGER_ACTIONS: Readonly<Record<IncidentStatus, readonly ManagerAction[]>> =
  Object.freeze(ACTIONS);

/**
 * `Object.hasOwn` rather than a bare lookup, following `techActions`: the
 * status arrives from the wire unvalidated, so a status unknown to the
 * compiled frontend returns "no actions" instead of an `undefined` that would
 * blow up the render.
 */
export function managerActions(status: IncidentStatus): readonly ManagerAction[] {
  return Object.hasOwn(ACTIONS, status) ? ACTIONS[status] : [];
}

/**
 * The bare reason string behind R1.4's text — `null` everywhere except
 * `AWAITING_OWNER_APPROVAL`, where the incident is waiting on the owner's
 * reply in `/approvals` and only `cancel` is on offer. Not a full i18n key:
 * the caller (section 5) interpolates it, e.g.
 * `t(\`incidents:manager.statusNote.${note}\`)`, matching how
 * `techNoActionReason` returns a bare reason rather than a full key.
 *
 * A `Record` over `IncidentStatus` for the same reason `ACTIONS` is one: a
 * tenth backend status breaks the build instead of silently inheriting
 * somebody else's copy.
 */
const STATUS_NOTE: Record<IncidentStatus, "awaiting-owner" | null> = {
  OPEN: null,
  CLASSIFIED: null,
  ASSIGNED: null,
  ACCEPTED: null,
  IN_PROGRESS: null,
  WAITING_EXTERNAL_PARTS: null,
  AWAITING_OWNER_APPROVAL: "awaiting-owner",
  RESOLVED: null,
  CANCELLED: null,
};

export function managerStatusNote(status: IncidentStatus): "awaiting-owner" | null {
  return Object.hasOwn(STATUS_NOTE, status) ? STATUS_NOTE[status] : null;
}
