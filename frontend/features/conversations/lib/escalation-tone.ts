import type { Tone } from "@/lib/ui/status-tone";

import type { ConversationEscalationStatus } from "../data";

/**
 * Tone per conversation escalation status — design D7.
 *
 * The class strings live only in `frontend/lib/ui/status-tone.ts`
 * (`TONE_BADGE_CLASS`); what lives here is the enum→tone reading next to the
 * enum, exactly as `severity-tone.ts`, `recommendation-status.ts`, and
 * `task-status.ts` do. The local `ESCALATION_BADGE` table this replaces was a
 * byte-for-byte duplicate of that pattern (and breached
 * `sdd/specs/frontend-foundation.md:38` — keep the badge palette in exactly one
 * place), so the routing through `TONE_BADGE_CLASS` is what closes that gap.
 *
 * `ConversationEscalationStatus` comes from the generated OpenAPI contract, so
 * the `Record` is exhaustive at compile time — until the frontend is rebuilt,
 * a fifth escalation can still arrive over the wire, which is what
 * `escalationTone` is for.
 */
const ESCALATION_TONE_GROUP: Record<ConversationEscalationStatus, Tone> = {
  NONE: "gray",
  PENDING_HUMAN: "amber",
  HUMAN_HANDLING: "blue",
  RESOLVED: "green",
};

/**
 * Frozen for the reason its siblings are: a module-level singleton read by every
 * row of the inbox list and every thread header, where one stray write would
 * change what every badge renders.
 */
export const ESCALATION_TONE = Object.freeze(ESCALATION_TONE_GROUP);

/**
 * Grey for an escalation status the union does not know, so deploy skew never
 * blanks a badge (R6.3, mirroring `severityColorGroup`).
 *
 * `Object.hasOwn` rather than a bare lookup with `??`: the key arrives from the
 * wire unvalidated, and a status of `toString` or `constructor` would resolve to
 * an inherited function — which `??` does not catch and which is not a `Tone`.
 */
export function escalationTone(
  status: ConversationEscalationStatus,
): Tone {
  return Object.hasOwn(ESCALATION_TONE_GROUP, status)
    ? ESCALATION_TONE_GROUP[status]
    : "gray";
}