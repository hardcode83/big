import type { DecisionStatus, PriceRecommendationStatus } from "../data";

/**
 * Which of the three moves a row in a given status may offer (design D13, R3.1,
 * R3.2).
 *
 * **This is affordance, not authority.** It duplicates the backend's transition
 * table, and says so for the same reason `features/cleaning` says it of its own:
 * the backend validates before mutating and answers `409` when the move is not
 * legal, and this screen has copy of its own for that `409` (R3.6) precisely
 * because it assumes this map can fall behind. Hiding a button is a convenience;
 * refusing the write is the guarantee.
 *
 * The `Record` is exhaustive over the generated union, so a sixth status breaks
 * the build once the contract is regenerated — and until then, `legalMoves`
 * answers `[]` for anything it does not recognise, so a row from a newer backend
 * renders with no buttons rather than with the wrong ones.
 *
 * `APPROVED → ["APPLIED_EXTERNAL"]` is the move that closes Mode 1 (R3.2):
 * without it an approved row is a dead end and «I published this price myself»
 * is unsayable.
 */
const MOVES_BY_STATUS: Record<
  PriceRecommendationStatus,
  readonly DecisionStatus[]
> = {
  DRAFT: Object.freeze([]),
  RECOMMENDED: Object.freeze(["APPROVED", "REJECTED"]),
  APPROVED: Object.freeze(["APPLIED_EXTERNAL"]),
  APPLIED_EXTERNAL: Object.freeze([]),
  REJECTED: Object.freeze([]),
};

const NO_MOVES: readonly DecisionStatus[] = Object.freeze([]);

export function legalMoves(
  status: PriceRecommendationStatus,
): readonly DecisionStatus[] {
  // `Object.hasOwn`, not a bare lookup with `?? []`: the key crosses the API
  // boundary untouched (`http-pricing-source.ts` passes `value.status` straight
  // through, and the DTO module is types-only), so a status of `constructor` or
  // `toString` would return an inherited **function** that `??` does not catch —
  // and the caller's `.map()` would throw, taking the row down. The fallback has
  // to cover the whole key space it claims to.
  return Object.hasOwn(MOVES_BY_STATUS, status)
    ? MOVES_BY_STATUS[status]
    : NO_MOVES;
}
