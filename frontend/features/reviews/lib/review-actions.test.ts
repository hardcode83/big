import { describe, expect, it } from "vitest";

import { legalActions } from "./review-actions";

/**
 * Pins the four-state matrix of legal actions by role (design D5, R3.1, R3.2,
 * R3.3). A backend that adds a sixth status breaks the build (the `Record` is
 * exhaustive); an unknown status from a deploy skew returns `[]` instead of
 * throwing or rendering the wrong buttons.
 */

describe("legalActions", () => {
  describe("owner", () => {
    it("NEW: no actions", () => {
      expect(legalActions("NEW", "owner")).toEqual([]);
    });
    it("DRAFTED: APPROVE, IGNORE, EDIT", () => {
      expect(legalActions("DRAFTED", "owner")).toEqual([
        "APPROVE",
        "IGNORE",
        "EDIT",
      ]);
    });
    it("APPROVED: MARK_POSTED only (no EDIT, draft is locked after approval)", () => {
      expect(legalActions("APPROVED", "owner")).toEqual(["MARK_POSTED"]);
    });
    it("POSTED_MANUALLY: no actions (terminal)", () => {
      expect(legalActions("POSTED_MANUALLY", "owner")).toEqual([]);
    });
    it("IGNORED: no actions (terminal)", () => {
      expect(legalActions("IGNORED", "owner")).toEqual([]);
    });
  });

  describe("manager", () => {
    it("NEW: no actions", () => {
      expect(legalActions("NEW", "manager")).toEqual([]);
    });
    it("DRAFTED: EDIT only (decisions are owner's UX split)", () => {
      expect(legalActions("DRAFTED", "manager")).toEqual(["EDIT"]);
    });
    it("APPROVED: no actions (manager doesn't see MARK_POSTED)", () => {
      expect(legalActions("APPROVED", "manager")).toEqual([]);
    });
    it("POSTED_MANUALLY: no actions", () => {
      expect(legalActions("POSTED_MANUALLY", "manager")).toEqual([]);
    });
    it("IGNORED: no actions", () => {
      expect(legalActions("IGNORED", "manager")).toEqual([]);
    });
  });

  describe("other (CLEANER, TECHNICIAN, SUPER_ADMIN)", () => {
    it("never sees any action regardless of status", () => {
      expect(legalActions("NEW", "other")).toEqual([]);
      expect(legalActions("DRAFTED", "other")).toEqual([]);
      expect(legalActions("APPROVED", "other")).toEqual([]);
      expect(legalActions("POSTED_MANUALLY", "other")).toEqual([]);
      expect(legalActions("IGNORED", "other")).toEqual([]);
    });
  });

  describe("deploy-skew unknown status", () => {
    it("returns [] for an unknown status string", () => {
      // Cast past the type because the deploy-skew window is exactly the case
      // where the wire disagrees with the generated union.
      expect(
        legalActions("SOME_FUTURE_STATUS" as never, "owner"),
      ).toEqual([]);
      expect(
        legalActions("SOME_FUTURE_STATUS" as never, "manager"),
      ).toEqual([]);
    });

    it("returns [] for a value that looks like an Object.prototype key", () => {
      // `Object.hasOwn` guards against an inherited function key; this is the
      // case it protects against.
      expect(legalActions("toString" as never, "owner")).toEqual([]);
      expect(legalActions("constructor" as never, "manager")).toEqual([]);
    });
  });
});