import { describe, expect, it } from "vitest";

import type { IncidentStatus } from "../data";
import { managerActions, managerStatusNote } from "./manager-actions";

describe("managerActions (R1.3, D6)", () => {
  it.each<[IncidentStatus, readonly string[]]>([
    ["OPEN", ["classify", "triage", "cancel"]],
    ["CLASSIFIED", ["assign", "triage", "cancel"]],
    ["ASSIGNED", ["assign", "triage", "cancel"]],
    ["ACCEPTED", ["assign", "triage", "cancel"]],
    ["IN_PROGRESS", ["assign", "triage", "cancel"]],
    ["WAITING_EXTERNAL_PARTS", ["assign", "triage", "cancel"]],
    ["AWAITING_OWNER_APPROVAL", ["cancel"]],
    ["RESOLVED", []],
    ["CANCELLED", []],
  ])("offers %s -> %o", (status, expected) => {
    expect(managerActions(status)).toEqual(expected);
  });

  it("returns no actions for a status unknown to the compiled frontend", () => {
    expect(managerActions("SOME_FUTURE_STATUS" as IncidentStatus)).toEqual([]);
  });
});

describe("managerStatusNote (R1.4)", () => {
  it.each<[IncidentStatus, "awaiting-owner" | null]>([
    ["OPEN", null],
    ["CLASSIFIED", null],
    ["ASSIGNED", null],
    ["ACCEPTED", null],
    ["IN_PROGRESS", null],
    ["WAITING_EXTERNAL_PARTS", null],
    ["AWAITING_OWNER_APPROVAL", "awaiting-owner"],
    ["RESOLVED", null],
    ["CANCELLED", null],
  ])("reads %s as %s", (status, expected) => {
    expect(managerStatusNote(status)).toBe(expected);
  });

  it("returns null for a status unknown to the compiled frontend", () => {
    expect(managerStatusNote("SOME_FUTURE_STATUS" as IncidentStatus)).toBeNull();
  });
});
