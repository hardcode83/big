import type { Tone } from "@/lib/ui/status-tone";

import type { IncidentSeverity } from "../data";

/**
 * Tone per incident severity — design D7.
 *
 * The two `SEVERITY_COLOR` tables this replaces lived in
 * `components/detail/incident-detail-sections.tsx` and
 * `components/list/incidents-view.tsx`, byte for byte identical, in breach of
 * `sdd/specs/frontend-foundation.md:38` («keep the badge colour palette in
 * exactly one place»). The class strings now live only in
 * `lib/ui/status-tone.ts`; what lives here is the enum→tone reading, next to its
 * enum, exactly as `STATE_COLOR_GROUP` and `task-status.ts` do.
 *
 * ASSUMPTION: PRD §9.1 fixes colours for a property's **operational state**, not
 * for an incident's severity. Reusing the palette is not merging the
 * vocabularies (R6.4): low = no urgency, medium = worth knowing, high = act
 * soon, critical = act now. The tones are the ones already shipping, so no badge
 * changes colour here — only which stylesheet decides it.
 *
 * `IncidentSeverity` comes from the generated OpenAPI contract, so the `Record`
 * is exhaustive at compile time — something the `Record<string, string>` it
 * replaces could not offer. That is a build-time guarantee: until the frontend
 * is rebuilt, a fifth severity can still arrive over the wire, which is what
 * `severityColorGroup` is for.
 */
const SEVERITY_COLOR_GROUP: Record<IncidentSeverity, Tone> = {
  LOW: "gray",
  MEDIUM: "blue",
  HIGH: "amber",
  CRITICAL: "red",
};

/**
 * Frozen for the reason its sibling `RECOMMENDATION_STATUS_TONE` is: a
 * module-level singleton shared by every row, where one stray write would change
 * what every later badge renders.
 */
export const SEVERITY_TONE = Object.freeze(SEVERITY_COLOR_GROUP);

/**
 * Grey for a severity the union does not know, so deploy skew never blanks a
 * badge (R6.3, and the `?? "gray"` the two dead tables carried).
 *
 * `Object.hasOwn` rather than a bare lookup with `??`, following
 * `recommendation-status.ts`: the key arrives from the wire unvalidated, and a
 * severity of `toString` or `constructor` would resolve to an inherited
 * **function** — which `??` does not catch and which is not a `Tone`.
 */
export function severityColorGroup(severity: IncidentSeverity): Tone {
  return Object.hasOwn(SEVERITY_COLOR_GROUP, severity)
    ? SEVERITY_COLOR_GROUP[severity]
    : "gray";
}
