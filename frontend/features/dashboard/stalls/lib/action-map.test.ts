import { describe, expect, it } from "vitest";

import type { PropertyOperationalState } from "@/components/property-state-badge";

import { actionMapFor, type ClockTrigger } from "./action-map";

/**
 * The card never paints a button that the matrix did not authorise (R1.5).
 * The exhaustive product of `ClockTrigger × PropertyOperationalState` is the
 * only honest test of that promise: one assertion per cell, no `if`s, and
 * the expected value comes from the **table itself** rather than from a
 * re-stated copy — a copy is what would silently drift from the table.
 */

const CLOCK_TRIGGERS: readonly ClockTrigger[] = [
  "CHECKIN_WINDOW_OPENED",
  "CHECKIN_TIME_REACHED",
  "CHECKOUT_TIME_REACHED",
] as const;

const OPERATIONAL_STATES: readonly PropertyOperationalState[] = [
  "VACANT_READY",
  "READY_FOR_NEXT_GUEST",
  "AWAITING_CHECKIN",
  "OCCUPIED_ESTIMATED",
  "CLEANING_IN_PROGRESS",
  "AWAITING_CLEANING",
  "CLEANING_SCHEDULED",
  "MAINTENANCE_REQUIRED",
  "CRITICAL_INCIDENT",
  "BLOCKED_BY_OWNER",
  "OUT_OF_SERVICE",
] as const;

/**
 * The expected table, transcribed once. The test reads from it cell-by-cell
 * so the assertion says what the **table** says, not what a reviewer typed
 * they remembered. The shape mirrors D3 in `design.md`.
 */
const EXPECTED: Record<
  ClockTrigger,
  Partial<Record<PropertyOperationalState, "cancel-cleaning" | "resolve-incident">>
> = {
  CHECKIN_WINDOW_OPENED: {
    AWAITING_CLEANING: "cancel-cleaning",
    CLEANING_IN_PROGRESS: "cancel-cleaning",
    CLEANING_SCHEDULED: "cancel-cleaning",
    MAINTENANCE_REQUIRED: "resolve-incident",
    CRITICAL_INCIDENT: "resolve-incident",
  },
  CHECKIN_TIME_REACHED: {
    AWAITING_CLEANING: "cancel-cleaning",
    CLEANING_IN_PROGRESS: "cancel-cleaning",
    CLEANING_SCHEDULED: "cancel-cleaning",
    MAINTENANCE_REQUIRED: "resolve-incident",
    CRITICAL_INCIDENT: "resolve-incident",
  },
  CHECKOUT_TIME_REACHED: {
    MAINTENANCE_REQUIRED: "resolve-incident",
    CRITICAL_INCIDENT: "resolve-incident",
  },
};

describe("actionMapFor (R1.5)", () => {
  for (const trigger of CLOCK_TRIGGERS) {
    for (const state of OPERATIONAL_STATES) {
      const expected = EXPECTED[trigger][state] ?? null;
      it(`${trigger} × ${state} → ${expected ?? "null"}`, () => {
        expect(actionMapFor(trigger, state)).toBe(expected);
      });
    }
  }

  it("returns null for an unknown trigger", () => {
    expect(actionMapFor("UNKNOWN_TRIGGER", "AWAITING_CLEANING")).toBeNull();
  });

  it("returns null for an unknown blocking_state", () => {
    expect(actionMapFor("CHECKIN_TIME_REACHED", "SOMETHING_NEW")).toBeNull();
  });
});