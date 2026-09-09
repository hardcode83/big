import type { PropertyOperationalState } from "../data";

/**
 * The only operational state that admits `CLEANER_ASSIGNED` today (design D2).
 *
 * Derived, by hand, from `PropertyStateMachine._POLICY`
 * (`backend/app/properties/domain/state_machine.py`): the single row whose trigger is
 * `CLEANER_ASSIGNED` reads
 * `(PropertyOperationalState.AWAITING_CLEANING, PropertyStateTrigger.CLEANER_ASSIGNED)`.
 * There is no runtime link between this array and that table — **a second row added to
 * `_POLICY` with the same trigger and a different source state derives this constant
 * stale and silently**: the backend would then accept an assignment this frontend still
 * warns against (or vice versa), and nothing here would fail to compile or fail a test,
 * because both sides are hand-written constants that happen to agree today. Whoever adds
 * such a row owns updating this file too.
 *
 * The type is aliased from the generated OpenAPI contract (`dto.ts`), so renaming a state
 * on the backend breaks this file's typecheck — but adding a state, or adding a second
 * `CLEANER_ASSIGNED`-admitting one, does not.
 */
export const ASSIGNABLE_PROPERTY_STATES: readonly PropertyOperationalState[] = [
  "AWAITING_CLEANING",
];

/**
 * Whether to show the manager a courtesy "this task cannot be assigned yet" notice for a
 * chosen property (R2.1).
 *
 * **Fail-open** (design D2, R2.3): an `undefined` state — the property's operational state
 * could not be resolved — returns `false`, i.e. no warning, exactly the policy
 * `assignment_blocker` documents for `property_state is None`. The warning is courtesy
 * only: the backend refuses the assignment again on its own terms regardless of what this
 * function answers, and creation is never blocked by it (R2.2).
 */
export function warnsNotAssignable(
  state: PropertyOperationalState | undefined,
): boolean {
  if (state === undefined) {
    return false;
  }
  return !ASSIGNABLE_PROPERTY_STATES.includes(state);
}
