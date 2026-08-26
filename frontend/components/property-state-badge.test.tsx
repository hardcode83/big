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
 * why the exact class strings are pinned here, character for character.
 *
 * Restated rather than imported, deliberately: importing `TONE_BADGE_CLASS`
 * would assert the component against the same constant it renders from, which is
 * a tautology. A second hand-written copy is what makes an accidental edit to
 * the palette fail here.
 *
 * The strings carry no `dark:` variant any more (design D6): the badge colour
 * comes from `--state-*`, which the theme redefines, so one string serves both
 * themes. The variant had to go — Tailwind's `dark:` follows
 * `prefers-color-scheme`, never our `data-theme` attribute, so on a page forced
 * dark over a light system these badges painted their light variant. Confirmed
 * in the browser on `/dashboard` before the fix (R6.5).
 */

const EXPECTED_CLASS: Record<StateColorGroup, string> = {
  green: "bg-state-success/15 text-state-success-text border-state-success/40",
  blue: "bg-state-info/15 text-state-info-text border-state-info/40",
  amber: "bg-state-warning/15 text-state-warning-text border-state-warning/40",
  red: "bg-state-error/15 text-state-error-text border-state-error/40",
  gray: "bg-state-neutral/15 text-state-neutral-text border-state-neutral/40",
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
