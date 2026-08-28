import { describe, expect, it } from "vitest";

import type { IncidentStatus } from "@/features/incidents";

import { TECH_ACTIONS, techActions, type CycleAction } from "./tech-actions";

describe("TECH_ACTIONS (R3.1, R3.2, D6)", () => {
  it.each<[IncidentStatus, CycleAction[]]>([
    ["ASSIGNED", ["accept", "reject"]],
    ["ACCEPTED", ["en-route", "reject"]],
    ["IN_PROGRESS", ["wait-parts", "resolve"]],
    ["WAITING_EXTERNAL_PARTS", ["resume"]],
    ["AWAITING_OWNER_APPROVAL", []],
    ["RESOLVED", []],
    ["CANCELLED", []],
    ["OPEN", []],
    ["CLASSIFIED", []],
  ])("offers exactly %s → %j", (status, expected) => {
    expect([...techActions(status)]).toEqual(expected);
  });

  it("returns no action for a status unknown to this build (deploy skew)", () => {
    expect([...techActions("TELEPORTED" as IncidentStatus)]).toEqual([]);
  });

  it("returns no action for an inherited property name (Object.hasOwn)", () => {
    expect([...techActions("constructor" as IncidentStatus)]).toEqual([]);
    expect([...techActions("toString" as IncidentStatus)]).toEqual([]);
  });

  it("covers the nine contract statuses and no more", () => {
    expect(Object.keys(TECH_ACTIONS).sort()).toEqual(
      [
        "ACCEPTED",
        "ASSIGNED",
        "AWAITING_OWNER_APPROVAL",
        "CANCELLED",
        "CLASSIFIED",
        "IN_PROGRESS",
        "OPEN",
        "RESOLVED",
        "WAITING_EXTERNAL_PARTS",
      ].sort(),
    );
  });
});
