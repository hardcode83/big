import { describe, expect, it } from "vitest";

import { TONE_BADGE_CLASS, type Tone } from "./status-tone";

/**
 * The palette's own net.
 *
 * `app/globals.contrast.test.ts` measures what these strings resolve to and
 * `components/property-state-badge.test.tsx` pins them character for character,
 * but neither covers the object's own integrity — raised by the section-7 panel,
 * which found `SEVERITY_TONE` frozen while the table it indexes was not.
 */
describe("TONE_BADGE_CLASS", () => {
  it("is frozen, so no consumer can change what every later badge renders", () => {
    expect(Object.isFrozen(TONE_BADGE_CLASS)).toBe(true);
  });

  it("covers the five tones and nothing else", () => {
    expect(Object.keys(TONE_BADGE_CLASS).sort()).toEqual([
      "amber",
      "blue",
      "gray",
      "green",
      "red",
    ] satisfies Tone[]);
  });

  it("gives every tone a distinct string, so two tones cannot alias", () => {
    // A copy-paste that left two tones on the same anchor would still satisfy
    // the shape assertions in the contrast audit.
    const strings = Object.values(TONE_BADGE_CLASS);
    expect(new Set(strings).size).toBe(strings.length);
  });
});
