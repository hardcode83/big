import { describe, expect, it } from "vitest";

import { formatNotificationDate } from "./format";

const ISO = "2026-08-29T14:05:00Z";

describe("formatNotificationDate (R4.4)", () => {
  it("formats in Spanish and in English, and the two differ", () => {
    const es = formatNotificationDate(ISO, "es");
    const en = formatNotificationDate(ISO, "en");

    expect(es).toBe(
      new Intl.DateTimeFormat("es", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(ISO)),
    );
    expect(en).toBe(
      new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(ISO)),
    );
    expect(es).not.toBe(en);
  });

  it("keeps the time, so two notices of the same day are distinguishable", () => {
    const morning = formatNotificationDate("2026-08-29T08:00:00Z", "es");
    const afternoon = formatNotificationDate("2026-08-29T17:00:00Z", "es");

    expect(morning).not.toBe(afternoon);
  });

  it("never renders the raw ISO string", () => {
    for (const locale of ["es", "en"]) {
      expect(formatNotificationDate(ISO, locale)).not.toContain("2026-08-29T");
    }
  });
});
