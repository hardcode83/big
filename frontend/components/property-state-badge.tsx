import { Badge } from "@/components/ui/badge";
import type { components } from "@/lib/api/generated/openapi";
import { cn } from "@/lib/utils";

/**
 * Shared operational-state badge (PRD §9.1). It owns the only copy of the
 * `PropertyOperationalState` color table in the tree: both the state → semantic
 * group map and the group → Tailwind class map used to live privately inside
 * `features/dashboard` (`lib/state-color.ts` plus `STATE_BADGE_CLASS` in
 * `components/property-card.tsx`), which meant any second screen painting the
 * same states had to copy them. `features/properties` is that second screen, so
 * design D2 moved both maps here instead.
 *
 * The component owns the color and receives the label already translated: the
 * eleven state labels live in the `dashboard` i18n namespace (design D10) and
 * this module deliberately knows nothing about i18n.
 *
 * Scope of the "single table" claim (design D2): this unifies the
 * `PropertyOperationalState` table only. `features/cleaning/lib/task-status.ts`
 * holds a separate table with the same Tailwind values for `CleaningTaskStatus`
 * — a different enum, kept on purpose by that change, and not touched here.
 */

/** Re-exported from the generated OpenAPI, never from a feature's hand-written union (design D3). */
export type PropertyOperationalState =
  components["schemas"]["PropertyOperationalState"];

export type StateColorGroup = "green" | "blue" | "amber" | "red" | "gray";

/**
 * Operational-state color groups from PRD §9.1. The mapping is exhaustive over
 * the canonical union, so adding a state without a color is a type error.
 *
 *   green  → VACANT_READY, READY_FOR_NEXT_GUEST, AWAITING_CHECKIN
 *   blue   → OCCUPIED_ESTIMATED, CLEANING_IN_PROGRESS
 *   amber  → AWAITING_CLEANING, CLEANING_SCHEDULED, MAINTENANCE_REQUIRED
 *   red    → CRITICAL_INCIDENT
 *   gray   → BLOCKED_BY_OWNER, OUT_OF_SERVICE
 */
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
 * The eleven canonical states, as runtime values, derived from the color map
 * above rather than re-transcribed.
 *
 * This is the single runtime source for callers that need to enumerate the
 * states — the filter's `<option>` list, and the tests. Hand-writing the list a
 * second time is the failure mode design D10 names for label catalogs («dos
 * catálogos del mismo enum es como divergen») and it applies just as well to
 * the values: a manual list has no exhaustiveness check, so if the backend adds
 * a twelfth state the filter would silently stop offering it and nothing would
 * go red. Deriving it from `STATE_COLOR_GROUP` inherits that map's
 * compiler-enforced exhaustiveness (`Record<PropertyOperationalState, …>`).
 *
 * Order is the map's declaration order, which is grouped by color on purpose
 * (green → blue → amber → red → gray) and is the order the filter shows.
 */
export const PROPERTY_OPERATIONAL_STATES = Object.keys(
  STATE_COLOR_GROUP,
) as PropertyOperationalState[];

/**
 * Color group for a state. Falls back to `gray` for an unrecognized value, so a
 * new backend state never crashes the screen — it renders neutrally until
 * mapped. Preserving this fallback was an explicit requirement of the move
 * (design D2): without it an unmapped value yields `undefined` as the class.
 */
export function stateColorGroup(
  state: PropertyOperationalState,
): StateColorGroup {
  return STATE_COLOR_GROUP[state] ?? "gray";
}

const STATE_BADGE_CLASS: Record<StateColorGroup, string> = {
  green:
    "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-800",
  blue: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-200 dark:border-blue-800",
  amber:
    "bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-800",
  red: "bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-200 dark:border-red-800",
  gray: "bg-muted text-muted-foreground border-border",
};

export function PropertyStateBadge({
  state,
  label,
}: {
  state: PropertyOperationalState;
  label: string;
}) {
  return (
    <Badge
      variant="outline"
      className={cn(STATE_BADGE_CLASS[stateColorGroup(state)])}
    >
      {label}
    </Badge>
  );
}
