import { describe, expect, it } from "vitest";

import esCleaning from "@/locales/es/cleaning.json";
import enCleaning from "@/locales/en/cleaning.json";

import type { CleaningTaskStatus } from "../data";
import {
  CLEANING_TASK_STATUSES,
  STATUS_BADGE_CLASS,
  statusColorGroup,
} from "./task-status";

/**
 * The nine values are written out here on purpose rather than derived from the
 * module under test: this list is what pins the module to the generated union, so
 * a tenth backend status fails here in red (R1.6).
 */
const NINE_STATUSES: readonly CleaningTaskStatus[] = [
  "CREATED",
  "ASSIGNED",
  "ACCEPTED",
  "REJECTED",
  "IN_PROGRESS",
  "PENDING_REVIEW",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
];

describe("statusColorGroup (R1.6, design D12)", () => {
  it("covers exactly the nine canonical statuses, in the canonical order", () => {
    // Order, not just membership: this array is what feeds the status filter's
    // options, so a lifecycle listed out of order is a defect the test must catch.
    expect(CLEANING_TASK_STATUSES).toEqual(NINE_STATUSES);
  });

  it.each(NINE_STATUSES)("gives %s a colour group with a badge class", (status) => {
    const group = statusColorGroup(status);
    expect(group).toBeDefined();
    expect(STATUS_BADGE_CLASS[group]).toBeTruthy();
  });

  it.each(NINE_STATUSES)("has an i18n label for %s in both locales", (status) => {
    expect(typeof esCleaning.status[status]).toBe("string");
    expect(esCleaning.status[status]).not.toBe("");
    expect(typeof enCleaning.status[status]).toBe("string");
    expect(enCleaning.status[status]).not.toBe("");
  });

  it("never renders the raw enum identifier as the label", () => {
    for (const status of NINE_STATUSES) {
      expect(esCleaning.status[status]).not.toBe(status);
    }
  });

  it("groups the lifecycle as design D12 describes", () => {
    expect(statusColorGroup("CREATED")).toBe("amber");
    expect(statusColorGroup("ASSIGNED")).toBe("amber");
    expect(statusColorGroup("PENDING_REVIEW")).toBe("amber");
    expect(statusColorGroup("ACCEPTED")).toBe("blue");
    expect(statusColorGroup("IN_PROGRESS")).toBe("blue");
    expect(statusColorGroup("COMPLETED")).toBe("green");
    expect(statusColorGroup("REJECTED")).toBe("red");
    expect(statusColorGroup("FAILED")).toBe("red");
    expect(statusColorGroup("CANCELLED")).toBe("gray");
  });

  it("falls back to grey for a status the union does not know", () => {
    expect(statusColorGroup("SOMETHING_NEW" as CleaningTaskStatus)).toBe("gray");
  });
});
