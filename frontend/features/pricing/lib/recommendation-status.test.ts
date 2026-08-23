import { describe, expect, it } from "vitest";

import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";

import type { PriceRecommendationStatus } from "../data";
import {
  RECOMMENDATION_STATUS_ORDER,
  RECOMMENDATION_STATUS_TONE,
  recommendationStatusTone,
} from "./recommendation-status";

/**
 * Task 3.2 does not ask for this file, and D15 says the locale contract test of
 * section 6 holds the five values to account. That is true of the *labels* — but
 * task 6.3 only checks that each status has copy in ES and EN, so nothing in the
 * plan would catch someone reordering the record's keys (alphabetically, or by
 * colour) and silently changing what the status filter shows. Raised by the QA
 * panel on section 3; the order is a documented claim, so it gets an assertion.
 */
describe("RECOMMENDATION_STATUS_ORDER (D15, R6.4)", () => {
  it("lists the five statuses in the lifecycle order of PRD §7.18", () => {
    // Not grouped by colour: this is what the filter dropdown shows, and a
    // lifecycle listed out of order reads as arbitrary.
    expect(RECOMMENDATION_STATUS_ORDER).toEqual([
      "DRAFT",
      "RECOMMENDED",
      "APPROVED",
      "APPLIED_EXTERNAL",
      "REJECTED",
    ]);
  });

  it("covers exactly the values the tone map declares, with no extras", () => {
    expect([...RECOMMENDATION_STATUS_ORDER].sort()).toEqual(
      Object.keys(RECOMMENDATION_STATUS_TONE).sort(),
    );
  });
});

describe("RECOMMENDATION_STATUS_TONE (R6.7, D22)", () => {
  it("maps each status to the tone design D22 fixed", () => {
    expect(RECOMMENDATION_STATUS_TONE).toEqual({
      DRAFT: "gray",
      RECOMMENDED: "amber",
      APPROVED: "blue",
      APPLIED_EXTERNAL: "green",
      REJECTED: "red",
    });
  });

  it("only uses tones the shared palette actually defines", () => {
    // The tone is an index into `TONE_BADGE_CLASS`; a typo would render a badge
    // with no classes rather than fail.
    for (const status of RECOMMENDATION_STATUS_ORDER) {
      expect(TONE_BADGE_CLASS).toHaveProperty(
        RECOMMENDATION_STATUS_TONE[status],
      );
    }
  });
});

describe("recommendationStatusTone", () => {
  it("returns the mapped tone for each known status", () => {
    for (const status of RECOMMENDATION_STATUS_ORDER) {
      expect(recommendationStatusTone(status)).toBe(
        RECOMMENDATION_STATUS_TONE[status],
      );
    }
  });

  it("falls back to grey for a status the contract does not declare", () => {
    // Deploy skew: a sixth status arrives before the frontend is rebuilt.
    const unknown = "SUPERSEDED" as PriceRecommendationStatus;
    expect(recommendationStatusTone(unknown)).toBe("gray");
  });

  it("falls back to grey for an inherited key, not to a function", () => {
    // `STATUS_TONE["toString"]` is a function, which `?? "gray"` would not
    // catch. The status crosses the API boundary with no runtime validation.
    for (const key of ["toString", "constructor", "valueOf", "__proto__"]) {
      expect(recommendationStatusTone(key as PriceRecommendationStatus)).toBe(
        "gray",
      );
    }
  });
});
