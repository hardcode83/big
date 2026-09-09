import { describe, expect, it } from "vitest";

import type { PropertyOperationalState } from "../data";

import {
  ASSIGNABLE_PROPERTY_STATES,
  warnsNotAssignable,
} from "./assignable-property-state";

/** Every literal of the generated `PropertyOperationalState` union (design D2). */
const ALL_STATES: readonly PropertyOperationalState[] = [
  "VACANT_READY",
  "AWAITING_CHECKIN",
  "OCCUPIED_ESTIMATED",
  "AWAITING_CLEANING",
  "CLEANING_SCHEDULED",
  "CLEANING_IN_PROGRESS",
  "READY_FOR_NEXT_GUEST",
  "MAINTENANCE_REQUIRED",
  "CRITICAL_INCIDENT",
  "BLOCKED_BY_OWNER",
  "OUT_OF_SERVICE",
];

describe("ASSIGNABLE_PROPERTY_STATES (design D2)", () => {
  it("admits exactly AWAITING_CLEANING — the single _POLICY row for CLEANER_ASSIGNED", () => {
    expect(ASSIGNABLE_PROPERTY_STATES).toEqual(["AWAITING_CLEANING"]);
  });
});

describe("warnsNotAssignable (R2.1, R2.3, design D2)", () => {
  it.each(ALL_STATES)("resolves %s against the constant", (state) => {
    expect(warnsNotAssignable(state)).toBe(state !== "AWAITING_CLEANING");
  });

  it("does not warn for AWAITING_CLEANING", () => {
    expect(warnsNotAssignable("AWAITING_CLEANING")).toBe(false);
  });

  it.each(ALL_STATES.filter((state) => state !== "AWAITING_CLEANING"))(
    "warns for %s",
    (state) => {
      expect(warnsNotAssignable(state)).toBe(true);
    },
  );

  it("fails open (does not warn) when the state could not be resolved — R2.3", () => {
    expect(warnsNotAssignable(undefined)).toBe(false);
  });
});
