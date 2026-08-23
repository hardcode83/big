import { describe, expect, it } from "vitest";

import type { DecisionStatus, PriceRecommendationStatus } from "../data";
import { legalMoves } from "./decision-moves";

describe("legalMoves (R3.1, R3.2)", () => {
  it("offers Approve and Reject on a RECOMMENDED row", () => {
    expect(legalMoves("RECOMMENDED")).toEqual(["APPROVED", "REJECTED"]);
  });

  it("offers only Mark as published on an APPROVED row (R3.2)", () => {
    // The move that closes Mode 1. Without it an approved row is a dead end.
    expect(legalMoves("APPROVED")).toEqual(["APPLIED_EXTERNAL"]);
  });

  it("offers nothing on DRAFT, APPLIED_EXTERNAL or REJECTED", () => {
    expect(legalMoves("DRAFT")).toEqual([]);
    expect(legalMoves("APPLIED_EXTERNAL")).toEqual([]);
    expect(legalMoves("REJECTED")).toEqual([]);
  });

  it("never offers APPLIED_EXTERNAL from any state other than APPROVED", () => {
    // R3.2 says «SHALL NOT ofrecerla en ningún otro estado», so it is worth
    // asserting across the whole union rather than only where it is expected.
    const others: PriceRecommendationStatus[] = [
      "DRAFT",
      "RECOMMENDED",
      "APPLIED_EXTERNAL",
      "REJECTED",
    ];
    for (const status of others) {
      expect(legalMoves(status)).not.toContain("APPLIED_EXTERNAL");
    }
  });

  it("returns no moves for a status the contract does not declare", () => {
    // Deploy skew: a sixth status arrives over the wire before the frontend is
    // rebuilt. No buttons is the safe answer; the wrong buttons is not.
    const unknown = "SUPERSEDED" as PriceRecommendationStatus;
    expect(legalMoves(unknown)).toEqual([]);
  });

  it("returns no moves for an inherited key, not an inherited function", () => {
    // A bare `TABLE[status] ?? []` hands back `Object.prototype.toString` here —
    // a function, which `??` does not catch and which the caller would `.map()`.
    // The status is passed straight from the wire with no runtime validation.
    for (const key of ["toString", "constructor", "valueOf", "__proto__"]) {
      const moves = legalMoves(key as PriceRecommendationStatus);
      expect(Array.isArray(moves)).toBe(true);
      expect(moves).toEqual([]);
    }
  });

  it("cannot be poisoned by a caller mutating what it returned", () => {
    // One frozen array per status is shared across every row, so a stray push
    // would give every later row a move the backend would refuse.
    const moves = legalMoves("RECOMMENDED") as DecisionStatus[];
    expect(() => moves.push("APPLIED_EXTERNAL")).toThrow();
    expect(legalMoves("RECOMMENDED")).toEqual(["APPROVED", "REJECTED"]);
  });
});
