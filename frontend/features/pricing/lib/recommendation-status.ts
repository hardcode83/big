import type { Tone } from "@/lib/ui/status-tone";

import type { PriceRecommendationStatus } from "../data";

/**
 * Tone per recommendation status, and the canonical order of the five values
 * (design D15).
 *
 * ASSUMPTION: PRD §9.1 fixes colours for a **property's operational state**, not
 * for a recommendation. R6.7 forbids reusing that meaning, and this does not: it
 * reuses the shared *palette* (`lib/ui/status-tone.ts`, design D22) with a reading
 * of its own — amber = waiting for a decision, blue = decided but not yet
 * published, green = closed, red = refused, grey = not offered yet. It is the same
 * kind of reuse `features/cleaning/lib/task-status.ts` already declares as an
 * ASSUMPTION, and it is annotated the same way.
 *
 * The `Record` is exhaustive over the generated union, so a sixth status in the
 * backend fails **at compile time** once the contract is regenerated. That is a
 * build-time guarantee, not a runtime one: until the frontend is rebuilt, such a
 * status can still arrive over the wire, which is what `tone()`'s fallback is for.
 */
const STATUS_TONE: Record<PriceRecommendationStatus, Tone> = {
  DRAFT: "gray",
  RECOMMENDED: "amber",
  APPROVED: "blue",
  APPLIED_EXTERNAL: "green",
  REJECTED: "red",
};

/**
 * Frozen for the same reason `decision-moves.ts` freezes its arrays: this is a
 * module-level singleton shared by every row, so a stray write would change what
 * every later badge renders. Symmetry with the neighbouring table, noted by the
 * security panel on section 3.
 */
export const RECOMMENDATION_STATUS_TONE = Object.freeze(STATUS_TONE);

/**
 * The five values as runtime data, derived from the map above rather than
 * transcribed.
 *
 * Order is PRD §7.18's lifecycle order — `DRAFT`, `RECOMMENDED`, `APPROVED`,
 * `APPLIED_EXTERNAL`, `REJECTED` — not grouped by colour: this is what the status
 * filter's `<option>` list shows, and a dropdown that lists a lifecycle out of
 * order reads as arbitrary.
 *
 * Deriving it from an exhaustive `Record` is the point (design D15): a
 * hand-written array validates the label catalog against itself, so a status the
 * backend adds and the list misses would look covered. The locale contract test
 * reads this constant for exactly that reason.
 */
export const RECOMMENDATION_STATUS_ORDER = Object.keys(
  STATUS_TONE,
) as readonly PriceRecommendationStatus[];

/**
 * Grey for a status the union does not know, so deploy skew never crashes a row.
 *
 * `Object.hasOwn` rather than a bare lookup with `?? "gray"`, for the same reason
 * `legalMoves` uses it: the key arrives from the wire unvalidated, and a status of
 * `toString` or `constructor` would return an inherited **function**, which `??`
 * does not catch and which is not a `Tone`.
 */
export function recommendationStatusTone(
  status: PriceRecommendationStatus,
): Tone {
  return Object.hasOwn(STATUS_TONE, status) ? STATUS_TONE[status] : "gray";
}
