import { describe, expect, it } from "vitest";

import { formatDateTime } from "./format";

/**
 * Pinning the format on the expected `Intl.DateTimeFormat` output rather than
 * the rendered string is what makes the test locale-stable: both `es` and
 * `en` accept the same ISO string and the formatter must return the same
 * shape the platform would render.
 */
describe("formatDateTime (R2.6, D17)", () => {
  it("formats an ISO string in Spanish exactly like Intl.DateTimeFormat('es') would", () => {
    const iso = "2026-08-12T18:30:00Z";
    const expected = new Intl.DateTimeFormat("es", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));

    expect(formatDateTime(iso, "es")).toBe(expected);
  });

  it("formats an ISO string in English exactly like Intl.DateTimeFormat('en') would", () => {
    const iso = "2026-08-12T18:30:00Z";
    const expected = new Intl.DateTimeFormat("en", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));

    expect(formatDateTime(iso, "en")).toBe(expected);
  });

  it("renders Spanish and English differently for the same instant", () => {
    const iso = "2026-08-12T18:30:00Z";

    expect(formatDateTime(iso, "es")).not.toBe(formatDateTime(iso, "en"));
  });

  it("returns the em-dash for null", () => {
    expect(formatDateTime(null as unknown as string, "es")).toBe("—");
  });

  it("returns the em-dash for undefined", () => {
    expect(formatDateTime(undefined as unknown as string, "es")).toBe("—");
  });

  it("returns the em-dash for an empty string", () => {
    expect(formatDateTime("", "es")).toBe("—");
  });

  it("returns the raw value for an unparseable date instead of throwing", () => {
    expect(formatDateTime("not-a-date", "es")).toBe("not-a-date");
  });
});