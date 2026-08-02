import { describe, expect, it } from "vitest";

import type { PropertyOperationalState } from "../data";
import { stateColorGroup } from "./state-color";

describe("stateColorGroup (R5, PRD §9.1)", () => {
  const cases: Array<[PropertyOperationalState, string]> = [
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
  ];

  it.each(cases)("maps %s to the %s group", (state, group) => {
    expect(stateColorGroup(state)).toBe(group);
  });

  it("covers all five PRD §9.1 color groups", () => {
    const groups = new Set(cases.map(([, group]) => group));
    expect(groups).toEqual(new Set(["green", "blue", "amber", "red", "gray"]));
  });

  it("falls back to gray for an unrecognized state", () => {
    expect(
      stateColorGroup("SOMETHING_NEW" as PropertyOperationalState),
    ).toBe("gray");
  });
});
