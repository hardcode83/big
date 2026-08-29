import { describe, expect, it } from "vitest";

import type { IncidentStatus } from "@/features/incidents";

import {
  TECH_ACTIONS,
  techAcceptsPhotoUpload,
  techActions,
  techNoActionReason,
  type CycleAction,
} from "./tech-actions";

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

/**
 * R3.2 asks the screen to say *why* nothing is on offer. The previous code
 * picked "closed" for everything that was not `AWAITING_OWNER_APPROVAL`, which
 * made `OPEN` and `CLASSIFIED` claim a closure that had not happened.
 */
describe("techNoActionReason (R3.2)", () => {
  it.each([
    ["AWAITING_OWNER_APPROVAL", "awaiting-owner"],
    ["RESOLVED", "closed"],
    ["CANCELLED", "closed"],
    ["OPEN", "not-actionable"],
    ["CLASSIFIED", "not-actionable"],
  ] as const)("explains %s as %s", (status, expected) => {
    expect(techNoActionReason(status as IncidentStatus)).toBe(expected);
  });

  it("does not call an unassigned incident closed", () => {
    expect(techNoActionReason("OPEN" as IncidentStatus)).not.toBe("closed");
    expect(techNoActionReason("CLASSIFIED" as IncidentStatus)).not.toBe(
      "closed",
    );
  });

  it("falls back to not-actionable for a status unknown to this build", () => {
    expect(techNoActionReason("TELEPORTED" as IncidentStatus)).toBe(
      "not-actionable",
    );
  });
});

/**
 * R5.3: the upload is offered in exactly two states. This lived in the view as
 * an untyped `string[]`, invisible to the compiler; D6 wants one
 * compile-time-exhaustive table per status decision.
 */
describe("techAcceptsPhotoUpload (R5.3, D11)", () => {
  it.each<[IncidentStatus, boolean]>([
    ["IN_PROGRESS", true],
    ["WAITING_EXTERNAL_PARTS", true],
    ["ASSIGNED", false],
    ["ACCEPTED", false],
    ["AWAITING_OWNER_APPROVAL", false],
    ["RESOLVED", false],
    ["CANCELLED", false],
    ["OPEN", false],
    ["CLASSIFIED", false],
  ])("%s → %s", (status, expected) => {
    expect(techAcceptsPhotoUpload(status)).toBe(expected);
  });

  it("refuses a status unknown to this build (deploy skew)", () => {
    expect(techAcceptsPhotoUpload("TELEPORTED" as IncidentStatus)).toBe(false);
  });
});
