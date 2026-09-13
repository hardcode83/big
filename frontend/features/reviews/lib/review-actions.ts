import type { ReviewAction, ReviewStatus } from "../data";

/**
 * Which of the four actions a row in a given state may offer to a given role
 * (design D5, R3.1, R3.2, R3.3).
 *
 * **This is affordance, not authority.** It duplicates the backend's transition
 * table, and says so for the same reason pricing-web's `decision-moves.ts:1-22`
 * says it: the backend validates before mutating and answers `409` when the move
 * is not legal, and this screen has copy of its own for that `409` (R3.5)
 * precisely because it assumes this map can fall behind. Hiding a button is a
 * convenience; refusing the write is the guarantee.
 *
 * The two `Record`s are exhaustive: a sixth status in `MOVES_BY_STATUS`, a
 * third role in `ROLES`, or a fifth action in `ReviewAction` breaks the build
 * once the contract is regenerated. Until then, `legalActions` answers `[]`
 * for anything it does not recognise, so a row from a newer backend renders
 * with no buttons rather than with the wrong ones.
 *
 * **`EDIT` is removed from the `APPROVED` row** because the
 * `ReviewResponseDraft.edit()` entity method
 * (`backend/app/reviews/domain/entities.py:359-380`) raises
 * `ReviewValidationError` once `approved_at` is set, and
 * `test_edit_after_approval_is_refused` pins that. Offering the button would
 * only deliver a `422` the UI cannot show — the project's policy forbids
 * painting the body of a `422`.
 *
 * **Hiding decision actions from the manager is a UX choice, not an RBAC
 * consequence.** `policy.py:309-316` grants the `PROPERTY_MANAGER` the same
 * four action permissions via `_REVIEW_MANAGE` (R7.2). The frontend mirror
 * narrows what the manager sees — the roadmap's owner-decides / manager-creates
 * split — and the backend still accepts the action if a manager calls the API
 * directly. `pricing-web` adopts the same posture for `MANAGE_PRICE_RECOMMENDATIONS`
 * (D17 of that change).
 */

/**
 * The two roles the frontend distinguishes for reviews. `TENANT_OWNER` sees all
 * actions the status allows; `PROPERTY_MANAGER` sees only `EDIT` in `DRAFTED`.
 * Any other role (CLEANER, TECHNICIAN, SUPER_ADMIN) sees nothing — they never
 * reach this code path because the page itself is hidden from them by the
 * workspace shell, but the function stays total for safety.
 */
export type ReviewerRole = "owner" | "manager" | "other";

const MOVES_BY_STATUS: Record<ReviewStatus, readonly ReviewAction[]> = {
  NEW: Object.freeze([]),
  DRAFTED: Object.freeze(["APPROVE", "IGNORE", "EDIT"]),
  APPROVED: Object.freeze(["MARK_POSTED"]),
  POSTED_MANUALLY: Object.freeze([]),
  IGNORED: Object.freeze([]),
};

/** What the manager sees, by status. `EDIT` is the only thing the manager does. */
const MANAGER_MOVES_BY_STATUS: Record<ReviewStatus, readonly ReviewAction[]> = {
  NEW: Object.freeze([]),
  DRAFTED: Object.freeze(["EDIT"]),
  APPROVED: Object.freeze([]),
  POSTED_MANUALLY: Object.freeze([]),
  IGNORED: Object.freeze([]),
};

const NO_ACTIONS: readonly ReviewAction[] = Object.freeze([]);

function hasOwnAction<T extends PropertyKey>(
  obj: Record<T, readonly ReviewAction[]>,
  key: PropertyKey,
): boolean {
  return Object.hasOwn(obj, key);
}

/**
 * Returns the actions the row should offer to a given role.
 *
 * `Object.hasOwn` instead of a bare lookup with `?? []`: the key crosses the API
 * boundary untouched, so a status of `constructor` or `toString` would return
 * an inherited **function** that `??` does not catch — and the caller's
 * `.map()` would throw, taking the row down. The fallback has to cover the
 * whole key space.
 */
export function legalActions(
  status: ReviewStatus,
  role: ReviewerRole,
): readonly ReviewAction[] {
  if (role === "other") {
    return NO_ACTIONS;
  }
  if (role === "manager") {
    return hasOwnAction(MANAGER_MOVES_BY_STATUS, status)
      ? MANAGER_MOVES_BY_STATUS[status]
      : NO_ACTIONS;
  }
  return hasOwnAction(MOVES_BY_STATUS, status)
    ? MOVES_BY_STATUS[status]
    : NO_ACTIONS;
}