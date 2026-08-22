import { describe, expect, it } from "vitest";

import {
  PROPERTY_OPERATIONAL_STATES,
  PropertyStateBadge,
  stateColorGroup,
  type PropertyOperationalState,
  type StateColorGroup,
} from "@/components/property-state-badge";
import { render, screen } from "@/test/render";

/**
 * These assertions are the ONLY net the PRD §9.1 colors have.
 *
 * Verified while designing this change: neither
 * `features/dashboard/components/property-card.test.tsx` nor
 * `dashboard-view.test.tsx` asserts on the badge's Tailwind classes — the first
 * checks text, aria-label/heading structure and href; the second checks
 * `items-stretch`/`h-full` on the grid wrapper. So both would stay green even if
 * the extraction of the two color maps (design D2) got a color wrong. That is
 * why the exact class strings are pinned here, character for character,
 * including the `dark:` variants.
 */

const EXPECTED_CLASS: Record<StateColorGroup, string> = {
  green:
    "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-800",
  blue: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-200 dark:border-blue-800",
  amber:
    "bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-800",
  red: "bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-200 dark:border-red-800",
  gray: "bg-muted text-muted-foreground border-border",
};

/** One representative state per color group, per the PRD §9.1 mapping. */
const REPRESENTATIVE: Record<StateColorGroup, PropertyOperationalState> = {
  green: "VACANT_READY",
  blue: "OCCUPIED_ESTIMATED",
  amber: "AWAITING_CLEANING",
  red: "CRITICAL_INCIDENT",
  gray: "OUT_OF_SERVICE",
};

/**
 * Every color class this component can ever apply, across all five groups.
 *
 * Used to assert an EXACT match instead of mere membership: checking each
 * expected class with `toHaveClass` one by one only proves the expected classes
 * are present, so a badge carrying the right classes *plus* a stray one from
 * another group would pass. Intersecting the rendered class list with this set
 * and comparing it to the expected group catches both a missing class and an
 * extra one.
 */
const ALL_COLOR_CLASSES = new Set(
  Object.values(EXPECTED_CLASS).flatMap((classes) => classes.split(" ")),
);

/** The color classes actually applied to an element, ignoring Badge's own base classes. */
function appliedColorClasses(element: HTMLElement): Set<string> {
  return new Set(
    Array.from(element.classList).filter((className) =>
      ALL_COLOR_CLASSES.has(className),
    ),
  );
}

/**
 * The canonical union as runtime values, from the module's own exported
 * constant — which derives from the color map, so the compiler keeps it
 * complete. Verified against `backend/app/properties/domain/enums.py`.
 */
const ALL_STATES: readonly PropertyOperationalState[] =
  PROPERTY_OPERATIONAL_STATES;

describe("stateColorGroup (PRD §9.1, design D2)", () => {
  it.each([
    ["VACANT_READY", "green"],
    ["READY_FOR_NEXT_GUEST", "green"],
    ["AWAITING_CHECKIN", "green"],
    ["OCCUPIED_ESTIMATED", "blue"],
    ["CLEANING_IN_PROGRESS", "blue"],
    ["AWAITING_CLEANING", "amber"],
    ["CLEANING_SCHEDULED", "amber"],
    ["MAINTENANCE_REQUIRED", "amber"],
    ["CRITICAL_INCIDENT", "red"],
    ["BLOCKED_BY_OWNER", "gray"],
    ["OUT_OF_SERVICE", "gray"],
  ] as const)("maps %s to the %s group", (state, group) => {
    expect(stateColorGroup(state)).toBe(group);
  });

  it("reaches all five PRD §9.1 groups across the canonical union", () => {
    // Deliberately NOT `expect(stateColorGroup(state)).toBeDefined()`: the
    // `?? "gray"` fallback makes that assertion unfailable, so it would pass
    // with a completely broken map. Exhaustiveness over the union is already a
    // compile-time guarantee of `Record<PropertyOperationalState, …>`, enforced
    // by `npm run typecheck`. What is NOT guaranteed anywhere else, and what
    // this pins, is that no group has been collapsed away — if someone mapped
    // CRITICAL_INCIDENT to amber, `red` would vanish and this fails.
    const reached = new Set(ALL_STATES.map((state) => stateColorGroup(state)));
    expect(reached).toEqual(
      new Set<StateColorGroup>(["green", "blue", "amber", "red", "gray"]),
    );
  });

  it("falls back to gray for an unrecognized value instead of returning undefined", () => {
    // A state the backend adds before the frontend maps it must render
    // neutrally, never with `undefined` as its class (design D2).
    const unmapped = "SOME_NEW_BACKEND_STATE" as PropertyOperationalState;
    expect(stateColorGroup(unmapped)).toBe("gray");
  });
});

describe("PropertyStateBadge (design D2, D3)", () => {
  it.each(
    (Object.keys(EXPECTED_CLASS) as StateColorGroup[]).map((group) => [
      group,
      REPRESENTATIVE[group],
      EXPECTED_CLASS[group],
    ]),
  )(
    "applies the exact %s class string for %s",
    (_group, state, expectedClass) => {
      render(<PropertyStateBadge state={state} label="Etiqueta" />);
      const badge = screen.getByText("Etiqueta");
      // Exact match over the color-class vocabulary: catches a missing class
      // AND a stray extra one, which a per-token `toHaveClass` loop cannot.
      expect(appliedColorClasses(badge)).toEqual(
        new Set(expectedClass.split(" ")),
      );
    },
  );

  it("renders the label it is given verbatim and does not translate it", () => {
    // The component owns the color; the caller owns the label (design D10).
    render(
      <PropertyStateBadge state="VACANT_READY" label="Libre y preparada" />,
    );
    expect(screen.getByText("Libre y preparada")).toBeInTheDocument();
  });

  it("applies the gray classes for an unrecognized state", () => {
    const unmapped = "SOME_NEW_BACKEND_STATE" as PropertyOperationalState;
    render(<PropertyStateBadge state={unmapped} label="Desconocido" />);
    const badge = screen.getByText("Desconocido");
    expect(appliedColorClasses(badge)).toEqual(
      new Set(EXPECTED_CLASS.gray.split(" ")),
    );
  });
});
