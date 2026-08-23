import { Badge } from "@/components/ui/badge";
import type { components } from "@/lib/api/generated/openapi";
import { TONE_BADGE_CLASS, type Tone } from "@/lib/ui/status-tone";
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
 * `PropertyOperationalState` → color-group table only. The group → Tailwind
 * table it used to hold privately no longer lives here either: `pricing-web`
 * (design D22) moved it to `lib/ui/status-tone.ts` when a third consumer
 * appeared, so `features/cleaning/lib/task-status.ts` and `features/pricing`
 * now read the same strings instead of copying them. Each enum still keeps its
 * own map to a tone, because what "amber" means belongs to that lifecycle.
 */

/** Re-exported from the generated OpenAPI, never from a feature's hand-written union (design D3). */
export type PropertyOperationalState =
  components["schemas"]["PropertyOperationalState"];

/** Alias of the shared `Tone` (design D22): `features/properties` and this module's test import it by this name. */
export type StateColorGroup = Tone;

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
      className={cn(TONE_BADGE_CLASS[stateColorGroup(state)])}
    >
      {label}
    </Badge>
  );
}
