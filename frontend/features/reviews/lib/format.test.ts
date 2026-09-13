import { describe, expect, it } from "vitest";

import { fmtDay, fmtRating } from "./format";

/**
 * Pin the two formatter behaviours that the design and proposal call out as
 * load-bearing (design D18, R8.3, R8.4):
 *
 *  - the locale argument changes the decimal separator (ES vs EN);
 *  - `fmtDay` does not shift the date west of UTC, even when the runtime's TZ
 *    is set to America/Los_Angeles.
 *
 * The TZ test is the one a Spanish-only writer misses: `new Date("2026-01-01")`
 * parses as midnight UTC, and `Intl.DateTimeFormat` without `timeZone: "UTC"`
 * would print 31 December in any zone west of UTC.
 */

describe("fmtRating", () => {
  it("uses comma as decimal separator for ES", () => {
    expect(fmtRating("4.5", "es")).toBe("4,5");
  });

  it("uses dot as decimal separator for EN", () => {
    expect(fmtRating("4.5", "en")).toBe("4.5");
  });

  it("returns the original string when not a finite number", () => {
    expect(fmtRating("not-a-number", "es")).toBe("not-a-number");
    expect(fmtRating("abc", "en")).toBe("abc");
  });

  it("does not embed /5 (the suffix travels with the localized label)", () => {
    expect(fmtRating("4.5", "es")).not.toContain("/5");
    expect(fmtRating("4.5", "en")).not.toContain("/5");
  });
});

describe("fmtDay", () => {
  it("formats a YYYY-MM-DD as the locale's medium date", () => {
    // Pick a date that is unambiguous regardless of locale formatting choices.
    const out = fmtDay("2026-08-23", "en");
    expect(out).toMatch(/Aug/i);
    expect(out).toMatch(/23/);
    expect(out).toMatch(/2026/);
  });

  it("does not shift the day west of UTC (TZ simulation)", () => {
    const prev = process.env.TZ;
    process.env.TZ = "America/Los_Angeles";
    try {
      const out = fmtDay("2026-01-01", "en");
      expect(out).toMatch(/Jan/i);
      expect(out).toMatch(/1/);
      expect(out).not.toMatch(/31/);
    } finally {
      if (prev === undefined) {
        delete process.env.TZ;
      } else {
        process.env.TZ = prev;
      }
    }
  });

  it("returns the raw input when unparseable", () => {
    expect(fmtDay("not-a-date", "en")).toBe("not-a-date");
  });
});