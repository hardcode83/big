import type { PropertyOperationalState } from "../data";

/**
 * Operational-state color groups from PRD §9.1. The mapping is exhaustive over
 * the canonical `PropertyOperationalState` union, so adding a state without a
 * color is a type error. Rendering (Tailwind classes / CSS variables) is the
 * component's job; this module only assigns the semantic group.
 *
 *   green  → VACANT_READY, READY_FOR_NEXT_GUEST, AWAITING_CHECKIN
 *   blue   → OCCUPIED_ESTIMATED, CLEANING_IN_PROGRESS
 *   amber  → AWAITING_CLEANING, CLEANING_SCHEDULED, MAINTENANCE_REQUIRED
 *   red    → CRITICAL_INCIDENT
 *   gray   → BLOCKED_BY_OWNER, OUT_OF_SERVICE
 */
export type StateColorGroup = "green" | "blue" | "amber" | "red" | "gray";

const STATE_COLOR_GROUP: Record<PropertyOperationalState, StateColorGroup> = {
  VACANT_READY: "green",
  READY_FOR_NEXT_GUEST: "green",
  AWAITING_CHECKIN: "green",
  OCCUPIED_ESTIMATED: "blue",
  CLEANING_IN_PROGRESS: "blue",
  AWAITING_CLEANING: "amber",
  CLEANING_SCHEDULED: "amber",
  MAINTENANCE_REQUIRED: "amber",
  CRITICAL_INCIDENT: "red",
  BLOCKED_BY_OWNER: "gray",
  OUT_OF_SERVICE: "gray",
};

/**
 * Color group for a state. Falls back to `gray` for an unrecognized value, so a
 * new backend state never crashes the card — it renders neutrally until mapped.
 */
export function stateColorGroup(
  state: PropertyOperationalState,
): StateColorGroup {
  return STATE_COLOR_GROUP[state] ?? "gray";
}
