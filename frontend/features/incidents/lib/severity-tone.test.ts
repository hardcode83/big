import { describe, expect, it } from "vitest";

import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";

import type { IncidentSeverity } from "../data";
import { SEVERITY_TONE, severityColorGroup } from "./severity-tone";

/**
 * The net for the unification of design D7.
 *
 * Nothing else covers it: the two `SEVERITY_COLOR` tables this replaces had no
 * test at all, and the render tests of `incidents-view` and
 * `incident-detail-sections` assert on text and structure, never on the badge's
 * classes. So a tone silently changing meaning — critical rendered blue — would
 * have gone unnoticed in either shape.
 */
describe("SEVERITY_TONE (D7, R6.4)", () => {
  it("maps each severity to the tone the two dead tables already used", () => {
    // The whole point of D7 is that unification changes no colour. These four
    // pairs are the ones the deleted `SEVERITY_COLOR` encoded via raw scales:
    // gray-100, blue-100, amber-100, red-100.
    expect(SEVERITY_TONE).toEqual({
      LOW: "gray",
      MEDIUM: "blue",
      HIGH: "amber",
      CRITICAL: "red",
    });
  });

  it("only uses tones the shared palette defines", () => {
    // The tone indexes `TONE_BADGE_CLASS`; a typo renders a badge with no
    // classes at all rather than failing.
    for (const tone of Object.values(SEVERITY_TONE)) {
      expect(TONE_BADGE_CLASS).toHaveProperty(tone);
    }
  });

  it("is frozen, so no row can rewrite what later rows render", () => {
    expect(Object.isFrozen(SEVERITY_TONE)).toBe(true);
  });
});

describe("severityColorGroup", () => {
  it.each([
    ["LOW", "gray"],
    ["MEDIUM", "blue"],
    ["HIGH", "amber"],
    ["CRITICAL", "red"],
  ] as const)("resolves %s to %s", (severity, tone) => {
    expect(severityColorGroup(severity)).toBe(tone);
  });

  it("falls back to gray for a severity the contract does not know (R6.3)", () => {
    // Deploy skew: the backend can ship a fifth severity before the frontend is
    // rebuilt, and the value arrives over the wire regardless of the union.
    const unmapped = "CATASTROPHIC" as IncidentSeverity;
    expect(severityColorGroup(unmapped)).toBe("gray");
  });

  it("falls back to gray for an inherited key, which `??` would not catch", () => {
    // Why `Object.hasOwn` and not a bare lookup: `SEVERITY_TONE.toString` is a
    // function, so `?? "gray"` would return it and the badge would receive a
    // function as its className.
    for (const inherited of ["toString", "constructor", "__proto__"]) {
      expect(severityColorGroup(inherited as IncidentSeverity)).toBe("gray");
    }
  });
});
