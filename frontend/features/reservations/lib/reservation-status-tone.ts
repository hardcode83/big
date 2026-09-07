import type { Tone } from "@/lib/ui/status-tone";

import type { ReservationStatus } from "../data/dto";

/**
 * Tone per reservation lifecycle status.
 *
 * ASSUMPTION: this is not a PRD §9.1 operational-state colour (that palette is
 * reserved for a property's operational state, e.g. `lib/ui/status-tone.ts`'s
 * own consumers) and R2 AC3 forbids reusing that meaning for something else.
 * This reuses the shared *palette* (design D22) with a reading of its own,
 * following the same reasoning `features/pricing/lib/recommendation-status.ts`
 * documents for its five values:
 *   - amber = awaiting a decision (`PENDING` has not been confirmed yet);
 *   - blue = confirmed but not yet under way (`CONFIRMED` is a future stay);
 *   - green = the guest is actively/successfully engaged with the stay
 *     (`CHECKED_IN_ESTIMATED` is in-house now, `COMPLETED` closed the stay
 *     without incident);
 *   - gray = a transitional, not-yet-final state (`CHECKED_OUT_ESTIMATED`
 *     inferred the stay window closed, but nothing has formally closed it);
 *   - red = the stay did not happen as booked (`CANCELLED`, `NO_SHOW`).
 *
 * The `Record` is exhaustive over the generated union, so a sixth status added
 * to the backend fails at **compile time** once the contract is regenerated.
 * That is a build-time guarantee, not a runtime one — `tone()`'s fallback below
 * covers the gap until the frontend is rebuilt.
 */
const STATUS_TONE: Record<ReservationStatus, Tone> = {
  PENDING: "amber",
  CONFIRMED: "blue",
  CANCELLED: "red",
  CHECKED_IN_ESTIMATED: "green",
  CHECKED_OUT_ESTIMATED: "gray",
  COMPLETED: "green",
  NO_SHOW: "red",
};

/**
 * Frozen for the same reason `lib/ui/status-tone.ts` and
 * `recommendation-status.ts` freeze theirs: a module-level singleton every
 * badge indexes, so a stray write would change what every later badge renders.
 */
export const RESERVATION_STATUS_TONE = Object.freeze(STATUS_TONE);

/**
 * Gray for a status the union does not know, so deploy skew never crashes a
 * row. `Object.hasOwn` rather than a bare lookup with `?? "gray"`, for the same
 * reason `recommendation-status.ts` uses it: the key arrives from the wire
 * unvalidated, and a status of `toString` or `constructor` would return an
 * inherited **function**, which `??` does not catch and which is not a `Tone`.
 */
export function reservationStatusTone(status: ReservationStatus): Tone {
  return Object.hasOwn(STATUS_TONE, status) ? STATUS_TONE[status] : "gray";
}
